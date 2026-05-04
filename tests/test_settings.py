"""Tests for settings management with class-based grouping and fixtures."""

import json
from pathlib import Path

import pytest

from pilot.settings.manager import (
    FileSettingsStorage,
    InMemorySettingsStorage,
    SettingsManager,
    _deep_merge_settings,
)


class TestDeepMergeSettings:
    """Tests for deep merge functionality."""

    def test_merge_simple_values(self):
        """Test merging simple key-value pairs."""
        base = {"theme": "dark", "steeringMode": "all"}
        overrides = {"theme": "light", "followUpMode": "one-at-a-time"}

        merged = _deep_merge_settings(base, overrides)

        assert merged["theme"] == "light"
        assert merged["steeringMode"] == "all"
        assert merged["followUpMode"] == "one-at-a-time"

    def test_merge_nested_objects(self):
        """Test merging nested configuration objects."""
        base = {
            "theme": "dark",
            "compaction": {"enabled": True, "reserveTokens": 1000},
        }
        overrides = {
            "compaction": {"reserveTokens": 2000},
        }

        merged = _deep_merge_settings(base, overrides)

        assert merged["compaction"]["enabled"] is True
        assert merged["compaction"]["reserveTokens"] == 2000

    def test_merge_with_none_values(self):
        """Test that None values in overrides are skipped."""
        base = {"theme": "dark"}
        overrides = {"theme": None, "newField": "value"}

        merged = _deep_merge_settings(base, overrides)

        # None should be skipped, so theme stays dark
        assert merged["theme"] == "dark"
        assert merged["newField"] == "value"


class TestInMemorySettingsStorage:
    """Tests for in-memory settings storage."""

    def test_basic_write_read(self):
        """Test writing and reading settings."""
        storage = InMemorySettingsStorage()

        def write_settings(current):
            settings = json.loads(current) if current else {}
            settings["theme"] = "dark"
            return json.dumps(settings)

        storage.with_lock("global", write_settings)

        # Read back
        read_content = None

        def capture_content(current):
            nonlocal read_content
            read_content = current
            return None

        storage.with_lock("global", capture_content)
        assert read_content is not None
        data = json.loads(read_content)
        assert data["theme"] == "dark"

    def test_project_settings_separate(self):
        """Test that project settings are stored separately."""
        storage = InMemorySettingsStorage()

        storage.with_lock("global", lambda _: json.dumps({"theme": "dark"}))
        storage.with_lock("project", lambda _: json.dumps({"theme": "light"}))

        # Verify they're different
        global_content = None
        project_content = None

        def capture_global(current):
            nonlocal global_content
            global_content = current
            return None

        def capture_project(current):
            nonlocal project_content
            project_content = current
            return None

        storage.with_lock("global", capture_global)
        storage.with_lock("project", capture_project)

        assert json.loads(global_content)["theme"] == "dark"
        assert json.loads(project_content)["theme"] == "light"


class TestFileSettingsStorage:
    """Tests for file-based settings storage."""

    def test_write_creates_file(self, temp_dir):
        """Test that settings file is created when writing."""
        agent_dir = temp_dir / "agent"
        agent_dir.mkdir()

        storage = FileSettingsStorage(cwd=str(temp_dir), agent_dir=str(agent_dir))

        def write_settings(current):
            return json.dumps({"theme": "dark"})

        storage.with_lock("global", write_settings)

        settings_file = agent_dir / "settings.json"
        assert settings_file.exists()

        data = json.loads(settings_file.read_text())
        assert data["theme"] == "dark"

    def test_project_settings_path(self, temp_dir):
        """Test project settings are stored in correct location."""
        agent_dir = temp_dir / "agent"
        agent_dir.mkdir()

        storage = FileSettingsStorage(cwd=str(temp_dir), agent_dir=str(agent_dir))

        def write_settings(current):
            return json.dumps({"theme": "light"})

        storage.with_lock("project", write_settings)

        project_file = temp_dir / ".pi" / "settings.json"
        assert project_file.exists()

        data = json.loads(project_file.read_text())
        assert data["theme"] == "light"


class TestSettingsManager:
    """Tests for SettingsManager with fixtures."""

    def test_in_memory_basic(self):
        """Test basic in-memory settings manager."""
        manager = SettingsManager.in_memory({"theme": "dark"})

        assert manager.get_theme() == "dark"
        assert manager.get_default_provider() is None

    def test_get_set_methods(self, settings_manager):
        """Test various getter and setter methods."""
        # Test theme
        settings_manager.set_theme("light")
        assert settings_manager.get_theme() == "light"

        # Test provider
        settings_manager.set_default_provider("openai")
        assert settings_manager.get_default_provider() == "openai"

        # Test compaction
        settings_manager.set_compaction_enabled(False)
        assert settings_manager.get_compaction_enabled() is False

        # Test retry
        settings_manager.set_retry_enabled(False)
        assert settings_manager.get_retry_enabled() is False

    def test_global_and_project_settings_merge(self, temp_dir):
        """Test that project settings override global settings."""
        agent_dir = temp_dir / "agent"
        agent_dir.mkdir()

        # Write global settings
        global_path = agent_dir / "settings.json"
        global_path.write_text(json.dumps({"theme": "dark", "steeringMode": "all"}))

        # Write project settings
        project_dir = temp_dir / ".pi"
        project_dir.mkdir()
        project_path = project_dir / "settings.json"
        project_path.write_text(json.dumps({"theme": "light"}))

        manager = SettingsManager.create(cwd=str(temp_dir), agent_dir=str(agent_dir))

        # Project overrides global
        assert manager.get_theme() == "light"
        # Global still accessible
        assert manager.get_steering_mode() == "all"

    def test_compaction_settings(self, settings_manager):
        """Test compaction-related settings."""
        settings = settings_manager.get_compaction_settings()
        assert settings["enabled"] is True
        assert settings["reserveTokens"] == 16384
        assert settings["keepRecentTokens"] == 20000

    def test_terminal_settings(self, settings_manager):
        """Test terminal-related settings."""
        assert settings_manager.get_image_width_cells() == 60
        assert settings_manager.get_show_images() is True

        settings_manager.set_show_images(False)
        assert settings_manager.get_show_images() is False

        settings_manager.set_image_width_cells(80)
        assert settings_manager.get_image_width_cells() == 80
