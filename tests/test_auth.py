"""Tests for auth storage with class-based grouping and fixtures."""

import json
from pathlib import Path

import pytest

from pilot.auth.storage import AuthStorage, FileAuthStorageBackend, InMemoryAuthStorageBackend
from pilot.auth.types import ApiKeyCredential, ApiKeyCredential


class TestInMemoryAuthStorageBackend:
    """Tests for in-memory auth storage backend."""

    def test_with_lock_writes_data(self):
        """Test that writing with lock persists data."""
        backend = InMemoryAuthStorageBackend()

        def write_fn(current):
            return ("result", json.dumps({"test": "data"}))

        result = backend.with_lock(write_fn)
        assert result == "result"
        assert backend._value == json.dumps({"test": "data"})

    def test_with_lock_reads_data(self):
        """Test that reading with lock retrieves data."""
        backend = InMemoryAuthStorageBackend()
        backend._value = json.dumps({"test": "data"})

        read_result = None

        def read_fn(current):
            nonlocal read_result
            read_result = current
            return (None, None)

        backend.with_lock(read_fn)
        assert read_result == json.dumps({"test": "data"})


class TestFileAuthStorageBackend:
    """Tests for file-based auth storage backend."""

    def test_with_lock_creates_file(self, temp_dir):
        """Test that file is created when writing."""
        backend = FileAuthStorageBackend(str(temp_dir))

        def write_fn(current):
            return ("result", json.dumps({"test": "data"}))

        result = backend.with_lock(write_fn)
        assert result == "result"

        auth_file = temp_dir / "auth.json"
        assert auth_file.exists()

        content = json.loads(auth_file.read_text())
        assert content["test"] == "data"


class TestAuthStorage:
    """Tests for AuthStorage with fixtures."""

    def test_in_memory_basic(self, auth_storage):
        """Test basic in-memory auth storage operations."""
        # Initially empty
        assert auth_storage.list() == []

        # Set a credential
        cred = ApiKeyCredential(key="test-key")
        auth_storage.set("openai", cred)

        # Should be in list
        assert "openai" in auth_storage.list()

        # Should be retrievable
        retrieved = auth_storage.get("openai")
        assert retrieved is not None
        assert retrieved.key == "test-key"

    def test_has_auth(self, auth_storage):
        """Test has_auth method."""
        assert not auth_storage.has_auth("openai")

        auth_storage.set("openai", ApiKeyCredential(key="key"))
        assert auth_storage.has_auth("openai")

    def test_get_auth_status(self, auth_storage):
        """Test get_auth_status method."""
        status = auth_storage.get_auth_status("openai")
        assert not status.configured

        auth_storage.set("openai", ApiKeyCredential(key="key"))
        status = auth_storage.get_auth_status("openai")
        assert status.configured
        assert status.source == "stored"

    def test_remove_credential(self, auth_storage):
        """Test removing a credential."""
        auth_storage.set("openai", ApiKeyCredential(key="key"))
        assert "openai" in auth_storage.list()

        auth_storage.remove("openai")
        assert "openai" not in auth_storage.list()

    def test_runtime_override(self, auth_storage):
        """Test runtime API key override."""
        auth_storage.set_runtime_api_key("test-provider", "runtime-key")

        # Override should be checked first
        # (get_api_key is async, so we just check the override is stored)
        assert "test-provider" in auth_storage._runtime_overrides

    def test_in_memory_with_initial_data(self):
        """Test creating in-memory storage with initial data."""
        initial_data = {
            "openai": ApiKeyCredential(key="initial-key")
        }
        storage = AuthStorage.in_memory(initial_data)

        # Should have the initial credential
        cred = storage.get("openai")
        assert cred is not None
        assert cred.key == "initial-key"

    def test_file_backend_with_temp_dir(self, temp_dir):
        """Test file backend with temporary directory."""
        backend = FileAuthStorageBackend(str(temp_dir))

        def write_fn(current):
            return ("result", json.dumps({"openai": {"type": "api_key", "key": "test"}}))

        backend.with_lock(write_fn)

        auth_file = temp_dir / "auth.json"
        assert auth_file.exists()

        data = json.loads(auth_file.read_text())
        assert data["openai"]["type"] == "api_key"
        assert data["openai"]["key"] == "test"
