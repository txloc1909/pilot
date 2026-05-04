"""Tests for auth storage."""

import json
import tempfile
from pathlib import Path

import pytest

from pilot.auth.storage import AuthStorage, FileAuthStorageBackend, InMemoryAuthStorageBackend
from pilot.auth.types import ApiKeyCredential, AuthCredential


def test_in_memory_auth_storage():
    """Test in-memory auth storage."""
    storage = AuthStorage.in_memory()

    # Set a credential
    cred = ApiKeyCredential(key="test-key")
    storage.set("openai", cred)

    # Retrieve it
    retrieved = storage.get("openai")
    assert retrieved is not None
    assert retrieved.key == "test-key"

    # List providers
    assert "openai" in storage.list()


def test_file_auth_storage():
    """Test file-based auth storage with locking."""
    with tempfile.TemporaryDirectory() as tmpdir:
        auth_path = Path(tmpdir) / "auth.json"
        storage = AuthStorage.create(str(auth_path.parent))

        # Set a credential
        cred = ApiKeyCredential(key="test-key")
        storage.set("openai", cred)

        # Check file was created
        assert auth_path.exists()

        # Read and verify
        content = auth_path.read_text()
        data = json.loads(content)
        assert data["openai"]["type"] == "api_key"
        assert data["openai"]["key"] == "test-key"


def test_auth_has_auth():
    """Test has_auth method."""
    storage = AuthStorage.in_memory()

    assert storage.has_auth("openai") is False

    storage.set("openai", ApiKeyCredential(key="test-key"))
    assert storage.has_auth("openai") is True


def test_auth_get_auth_status():
    """Test auth status method."""
    storage = AuthStorage.in_memory()

    # No auth
    status = storage.get_auth_status("openai")
    assert status.configured is False

    # With auth
    storage.set("openai", ApiKeyCredential(key="test-key"))
    status = storage.get_auth_status("openai")
    assert status.configured is True
    assert status.source == "stored"


def test_auth_remove():
    """Test removing credentials."""
    storage = AuthStorage.in_memory()

    storage.set("openai", ApiKeyCredential(key="test-key"))
    assert "openai" in storage.list()

    storage.remove("openai")
    assert "openai" not in storage.list()


def test_auth_runtime_override():
    """Test runtime API key override."""
    storage = AuthStorage.in_memory()

    # Set runtime override
    storage.set_runtime_api_key("openai", "runtime-key")

    # Get should return override
    # (Note: this depends on async get_api_key, testing sync for now)

    # Remove override
    storage.remove_runtime_api_key("openai")


def test_auth_fallback_resolver():
    """Test fallback resolver."""
    storage = AuthStorage.in_memory()

    def resolver(provider: str) -> str:
        if provider == "custom":
            return "fallback-key"
        return None

    storage.set_fallback_resolver(resolver)
    assert storage.has_auth("custom") is True


def test_auth_list():
    """Test listing providers."""
    storage = AuthStorage.in_memory()

    assert storage.list() == []

    storage.set("openai", ApiKeyCredential(key="key1"))
    storage.set("anthropic", ApiKeyCredential(key="key2"))

    providers = storage.list()
    assert "openai" in providers
    assert "anthropic" in providers
    assert len(providers) == 2


def test_auth_drain_errors():
    """Test draining errors."""
    storage = AuthStorage.in_memory()

    # No errors initially
    errors = storage.drain_errors()
    assert len(errors) == 0


def test_auth_in_memory_with_data():
    """Test in-memory storage with initial data."""
    initial_data = {
        "openai": ApiKeyCredential(key="initial-key")
    }
    storage = AuthStorage.in_memory(initial_data)

    # Should have the initial credential
    cred = storage.get("openai")
    assert cred is not None
    assert cred.key == "initial-key"


def test_auth_file_backend_acquire_lock():
    """Test file backend lock acquisition."""
    with tempfile.TemporaryDirectory() as tmpdir:
        auth_path = Path(tmpdir) / "auth.json"
        backend = FileAuthStorageBackend(str(auth_path.parent))

        # Test that lock can be acquired
        def test_fn(current):
            return "test-result", json.dumps({"test": "data"})

        result = backend.with_lock(test_fn)
        assert result == "test-result"
        assert auth_path.exists()
