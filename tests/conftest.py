"""Shared pytest fixtures for the test suite."""

import json
import tempfile
from pathlib import Path

import pytest

from pilot.auth.storage import AuthStorage
from pilot.auth.types import ApiKeyCredential
from pilot.models.registry import ModelRegistry
from pilot.settings.manager import SettingsManager
from pilot.session.manager import SessionManager
from pilot_provider.types import AssistantMessage, UserMessage


@pytest.fixture
def temp_dir():
    """Create a temporary directory for tests."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def auth_storage():
    """Create an in-memory auth storage for tests."""
    return AuthStorage.in_memory()


@pytest.fixture
def auth_storage_with_key():
    """Create an in-memory auth storage with a test API key."""
    storage = AuthStorage.in_memory()
    storage.set("test-provider", ApiKeyCredential(key="test-key-123"))
    return storage


@pytest.fixture
def settings_manager():
    """Create an in-memory settings manager."""
    return SettingsManager.in_memory({})


@pytest.fixture
def session_manager(temp_dir):
    """Create a session manager with a temporary directory."""
    session_dir = temp_dir / "sessions"
    session_dir.mkdir()
    return SessionManager.create(cwd="/test", session_dir=str(session_dir))


@pytest.fixture
def session_manager_with_messages(session_manager):
    """Create a session manager with test messages."""
    msg1 = UserMessage(role="user", content="Hello", timestamp=1000000)
    msg2 = AssistantMessage(
        role="assistant",
        content=[],
        timestamp=1000001,
        api="test",
        provider="test",
        model="test",
    )
    session_manager.append_message(msg1)
    session_manager.append_message(msg2)
    return session_manager


@pytest.fixture
def model_registry(auth_storage):
    """Create a model registry with in-memory auth storage."""
    return ModelRegistry.in_memory(auth_storage)


@pytest.fixture
def models_json_path(temp_dir):
    """Create a models.json file for testing."""
    models_path = temp_dir / "models.json"
    models_path.write_text(json.dumps({
        "providers": {
            "test": {
                "baseUrl": "http://test.com",
                "apiKey": "test-key",
                "models": [
                    {
                        "id": "test/model-1",
                        "name": "Test Model 1",
                        "reasoning": False,
                        "input": ["text"],
                        "cost": {"input": 0.5, "output": 1.0},
                        "contextWindow": 8192,
                        "maxTokens": 2048,
                    }
                ]
            }
        }
    }))
    return models_path
