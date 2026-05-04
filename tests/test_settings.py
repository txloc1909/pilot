"""Tests for settings management."""

import json
import tempfile
from pathlib import Path

import pytest

from pilot.settings.manager import (
    FileSettingsStorage,
    InMemorySettingsStorage,
    SettingsManager,
    _deep_merge_settings,
)
from pilot.settings.types import Settings


def test_deep_merge_settings():
    """Test deep merging of settings."""
    base = {
        "theme": "dark",
        "compaction": {"enabled": True, "reserveTokens": 1000},
        "list": [1, 2],
    }
    overrides = {
        "theme": "light",
        "compaction": {"reserveTokens": 2000},
        "newField": "value",
    }

    merged = _deep_merge_settings(base, overrides)

    # Override wins for simple fields
    assert merged["theme"] == "light"
    # Nested objects merge
    assert merged["compaction"]["enabled"] is True
    assert merged["compaction"]["reserveTokens"] == 2000
    # New field added
    assert merged["newField"] == "value"
    # Arrays replace (don't merge)
    assert merged["list"] == [1, 2]


def test_file_settings_storage():
    """Test file-based settings storage with locking."""
    with tempfile.TemporaryDirectory() as tmpdir:
        agent_dir = Path(tmpdir) / "agent"
        agent_dir.mkdir()

        storage = FileSettingsStorage(cwd=tmpdir, agent_dir=str(agent_dir))

        # Test with lock
        def write_settings(current: str) -> str:
            settings = json.loads(current) if current else {}
            settings["theme"] = "dark"
            return json.dumps(settings)

        storage.with_lock("global", write_settings)

        # Check file was created
        settings_path = agent_dir / "settings.json"
        assert settings_path.exists()

        content = settings_path.read_text()
        data = json.loads(content)
        assert data["theme"] == "dark"


def test_in_memory_settings_storage():
    """Test in-memory settings storage."""
    storage = InMemorySettingsStorage()

    def write_settings(current: str) -> str:
        settings = json.loads(current) if current else {}
        settings["theme"] = "light"
        return json.dumps(settings)

    storage.with_lock("global", write_settings)

    # Verify by reading back
    read_content: str = None
    
    def capture_content(current: str) -> None:
        nonlocal read_content
        read_content = current
        return None
    
    storage.with_lock("global", capture_content)
    assert read_content is not None
    data = json.loads(read_content)
    assert data["theme"] == "light"


def test_settings_manager_create():
    """Test creating a SettingsManager from files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        agent_dir = Path(tmpdir) / "agent"
        agent_dir.mkdir()

        manager = SettingsManager.create(cwd=tmpdir, agent_dir=str(agent_dir))

        # Check paths
        assert manager.get_default_provider() is None
        assert manager.get_theme() is None


def test_settings_manager_in_memory():
    """Test in-memory SettingsManager."""
    settings = {"theme": "dark", "defaultProvider": "openai"}
    manager = SettingsManager.in_memory(settings)

    assert manager.get_theme() == "dark"
    assert manager.get_default_provider() == "openai"


def test_settings_get_set():
    """Test getting and setting various settings."""
    manager = SettingsManager.in_memory({})

    # Default values
    assert manager.get_steering_mode() == "one-at-a-time"
    assert manager.get_follow_up_mode() == "one-at-a-time"
    assert manager.get_compaction_enabled() is True
    assert manager.get_compaction_reserve_tokens() == 16384
    assert manager.get_retry_enabled() is True
    assert manager.get_image_width_cells() == 60
    assert manager.get_show_images() is True

    # Set and get
    manager.set_theme("light")
    assert manager.get_theme() == "light"

    manager.set_default_provider("openai")
    assert manager.get_default_provider() == "openai"

    manager.set_compaction_enabled(False)
    assert manager.get_compaction_enabled() is False


def test_settings_merge():
    """Test global + project settings merge."""
    with tempfile.TemporaryDirectory() as tmpdir:
        agent_dir = Path(tmpdir) / "agent"
        agent_dir.mkdir()

        # Write global settings
        global_path = agent_dir / "settings.json"
        global_path.write_text(json.dumps({"theme": "dark", "steeringMode": "all"}))

        # Write project settings
        project_dir = Path(tmpdir) / ".pi"
        project_dir.mkdir()
        project_path = project_dir / "settings.json"
        project_path.write_text(json.dumps({"theme": "light"}))

        manager = SettingsManager.create(cwd=tmpdir, agent_dir=str(agent_dir))

        # Project overrides global
        assert manager.get_theme() == "light"
        # Global is still accessible
        assert manager.get_steering_mode() == "all"


def test_settings_compaction():
    """Test compaction-related settings."""
    manager = SettingsManager.in_memory({})

    assert manager.get_compaction_settings() == {
        "enabled": True,
        "reserveTokens": 16384,
        "keepRecentTokens": 20000,
    }

    manager.set_compaction_enabled(False)
    assert manager.get_compaction_settings()["enabled"] is False


def test_settings_retry():
    """Test retry settings."""
    manager = SettingsManager.in_memory({})

    settings = manager.get_retry_settings()
    assert settings["enabled"] is True
    assert settings["maxRetries"] == 3
    assert settings["baseDelayMs"] == 2000

    provider_settings = manager.get_provider_retry_settings()
    assert provider_settings["maxRetryDelayMs"] == 60000


def test_settings_terminal():
    """Test terminal settings."""
    manager = SettingsManager.in_memory({})

    assert manager.get_image_width_cells() == 60
    assert manager.get_clear_on_shrink() is False
    assert manager.get_show_terminal_progress() is False

    manager.set_show_images(False)
    assert manager.get_show_images() is False

    manager.set_image_width_cells(80)
    assert manager.get_image_width_cells() == 80


def test_settings_paths():
    """Test settings related to paths."""
    manager = SettingsManager.in_memory({"sessionDir": "~/sessions"})

    # Should expand ~
    session_dir = manager.get_session_dir()
    assert session_dir is not None
    assert "~" not in session_dir


def test_settings_save_and_reload(tmp_path):
    """Test saving and reloading settings."""
    agent_dir = tmp_path / "agent"
    agent_dir.mkdir()

    manager = SettingsManager.create(cwd=str(tmp_path), agent_dir=str(agent_dir))

    # Modify settings
    manager.set_theme("dark")
    manager.set_default_provider("openai")

    # Manually save (normally done automatically)
    # The manager auto-saves on set_* calls

    # Create new manager and reload
    manager2 = SettingsManager.create(cwd=str(tmp_path), agent_dir=str(agent_dir))

    # Check persisted settings
    assert manager2.get_theme() == "dark"
    assert manager2.get_default_provider() == "openai"
