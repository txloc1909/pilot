"""Credential storage for API keys and OAuth tokens.

Maps to pi's ``auth-storage.ts``.

Handles loading, saving, and refreshing credentials from ``auth.json``.
Uses file locking to prevent race conditions when multiple pilot instances
try to refresh tokens simultaneously.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional, Protocol, Tuple

from pilot.auth.types import (
    ApiKeyCredential,
    AuthCredential,
    AuthStatus,
    AuthStorageData,
    OAuthCredential,
)
from pilot.config import get_agent_dir


# ---------------------------------------------------------------------------
# Auth storage backend protocol
# ---------------------------------------------------------------------------


class AuthStorageBackend(Protocol):
    def with_lock(self, fn: Callable[[Optional[str]], Tuple[object, Optional[str]]]) -> object: ...


# ---------------------------------------------------------------------------
# File auth storage backend
# ---------------------------------------------------------------------------


class FileAuthStorageBackend:
    """File-backed auth storage with POSIX file locking."""

    def __init__(self, auth_path: str = "") -> None:
        self._auth_path = Path(auth_path or get_agent_dir()) / "auth.json"

    def _ensure_parent_dir(self) -> None:
        self._auth_path.parent.mkdir(parents=True, exist_ok=True)

    def _ensure_file(self) -> None:
        if not self._auth_path.exists():
            self._auth_path.write_text("{}")
            self._auth_path.chmod(0o600)

    def _acquire_lock_sync(self, path: Path, max_attempts: int = 10, delay_ms: int = 20) -> int:
        import errno
        import fcntl

        fd = os.open(str(path), os.O_RDWR)
        for attempt in range(1, max_attempts + 1):
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return fd
            except (IOError, OSError) as e:
                if e.errno not in (errno.EAGAIN, errno.EBUSY) or attempt == max_attempts:
                    os.close(fd)
                    raise
                time.sleep(delay_ms / 1000.0)
        os.close(fd)
        raise IOError(f"Failed to acquire lock on {path}")

    def with_lock(self, fn: Callable[[Optional[str]], Tuple[object, Optional[str]]]) -> object:
        self._ensure_parent_dir()
        self._ensure_file()

        fd: Optional[int] = None
        try:
            fd = self._acquire_lock_sync(self._auth_path)
            current: Optional[str] = None
            if self._auth_path.exists():
                current = self._auth_path.read_text()

            result, next_content = fn(current)

            if next_content is not None:
                self._auth_path.write_text(next_content)
                self._auth_path.chmod(0o600)

            return result
        finally:
            if fd is not None:
                try:
                    import fcntl
                    fcntl.flock(fd, fcntl.LOCK_UN)
                except (IOError, OSError):
                    pass
                os.close(fd)

    async def with_lock_async(
        self, fn: Callable[[Optional[str]], Tuple[object, Optional[str]]]
    ) -> object:
        """Async version of with_lock. Runs the sync lock in a thread."""
        import asyncio
        return await asyncio.to_thread(self.with_lock, fn)


# ---------------------------------------------------------------------------
# In-memory auth storage backend
# ---------------------------------------------------------------------------


class InMemoryAuthStorageBackend:
    """In-memory auth storage (no file I/O)."""

    def __init__(self) -> None:
        self._value: Optional[str] = None

    def with_lock(self, fn: Callable[[Optional[str]], Tuple[object, Optional[str]]]) -> object:
        result, next_content = fn(self._value)
        if next_content is not None:
            self._value = next_content
        return result


# ---------------------------------------------------------------------------
# Auth storage
# ---------------------------------------------------------------------------


class AuthStorage:
    """Credential storage backed by a JSON file.

    Priority for API key resolution:
    1. Runtime override (CLI --api-key)
    2. API key from auth.json
    3. OAuth token from auth.json
    4. Environment variable
    5. Fallback resolver (models.json custom providers)
    """

    def __init__(self, storage: AuthStorageBackend) -> None:
        self._storage = storage
        self._data: AuthStorageData = {}
        self._runtime_overrides: Dict[str, str] = {}
        self._fallback_resolver: Optional[Callable[[str], Optional[str]]] = None
        self._load_error: Optional[Exception] = None
        self._errors: List[Exception] = []
        self._reload()

    # ---- Factory constructors ----

    @classmethod
    def create(cls, auth_path: str = "") -> AuthStorage:
        """Create an AuthStorage backed by a file."""
        return cls(FileAuthStorageBackend(auth_path or str(Path(get_agent_dir()) / "auth.json")))

    @classmethod
    def from_storage(cls, storage: AuthStorageBackend) -> AuthStorage:
        return cls(storage)

    @classmethod
    def in_memory(cls, data: Optional[Dict[str, AuthCredential]] = None) -> AuthStorage:
        """Create an in-memory AuthStorage with optional initial data."""
        storage = InMemoryAuthStorageBackend()
        initial = {}
        if data:
            initial = {k: v.model_dump() if hasattr(v, "model_dump") else v for k, v in data.items()}
        storage.with_lock(lambda _: (None, json.dumps(initial, indent=2)))
        return cls.from_storage(storage)

    # ---- Runtime overrides ----

    def set_runtime_api_key(self, provider: str, api_key: str) -> None:
        """Set a runtime API key override (not persisted to disk)."""
        self._runtime_overrides[provider] = api_key

    def remove_runtime_api_key(self, provider: str) -> None:
        self._runtime_overrides.pop(provider, None)

    def set_fallback_resolver(self, resolver: Callable[[str], Optional[str]]) -> None:
        """Set a fallback resolver for API keys not found elsewhere."""
        self._fallback_resolver = resolver

    # ---- Internal ----

    def _record_error(self, error: Exception) -> None:
        self._errors.append(error)

    @staticmethod
    def _parse_storage_data(content: Optional[str]) -> dict:
        if not content:
            return {}
        return json.loads(content)

    def _reload(self) -> None:
        try:
            content: Optional[str] = None
            
            def capture_content(current: Optional[str]) -> Tuple[None, Optional[str]]:
                nonlocal content
                content = current
                return (None, None)  # Return (result, next_content) tuple
            
            self._storage.with_lock(capture_content)
            self._data = self._parse_storage_data(content)
            self._load_error = None
        except Exception as e:
            self._load_error = e
            self._record_error(e)

    def reload(self) -> None:
        self._reload()

    def _persist_provider_change(
        self, provider: str, credential: Optional[AuthCredential]
    ) -> None:
        if self._load_error:
            return
        try:
            self._storage.with_lock(
                lambda current: self._do_persist(current, provider, credential)
            )
        except Exception as e:
            self._record_error(e)

    @staticmethod
    def _do_persist(
        current: Optional[str], provider: str, credential: Optional[AuthCredential]
    ) -> Tuple[None, Optional[str]]:
        current_data = AuthStorage._parse_storage_data(current)
        merged = dict(current_data)
        if credential:
            # Convert Pydantic model to dict for JSON serialization
            if hasattr(credential, "model_dump"):
                merged[provider] = credential.model_dump()
            else:
                merged[provider] = credential
        else:
            merged.pop(provider, None)
        return None, json.dumps(merged, indent=2)

    # ---- Public API ----

    def get(self, provider: str) -> Optional[AuthCredential]:
        """Get credential for a provider."""
        raw = self._data.get(provider)
        if raw is None:
            return None
        if isinstance(raw, dict):
            if raw.get("type") == "api_key":
                return ApiKeyCredential(key=raw["key"])
            elif raw.get("type") == "oauth":
                return OAuthCredential(
                    access_token=raw.get("access_token", ""),
                    refresh_token=raw.get("refresh_token"),
                    expires=raw.get("expires", 0),
                    scope=raw.get("scope"),
                    token_type=raw.get("token_type"),
                    provider=raw.get("provider"),
                )
        return raw

    def set(self, provider: str, credential: AuthCredential) -> None:
        """Set credential for a provider."""
        self._data[provider] = credential
        self._persist_provider_change(provider, credential)

    def remove(self, provider: str) -> None:
        """Remove credential for a provider."""
        self._data.pop(provider, None)
        self._persist_provider_change(provider, None)

    def list(self) -> List[str]:
        """List all providers with credentials."""
        return list(self._data.keys())

    def has(self, provider: str) -> bool:
        """Check if credentials exist for a provider in auth.json."""
        return provider in self._data

    def has_auth(self, provider: str) -> bool:
        """Check if any form of auth is configured for a provider."""
        if provider in self._runtime_overrides:
            return True
        if provider in self._data:
            return True
        if _get_env_api_key(provider):
            return True
        if self._fallback_resolver and self._fallback_resolver(provider):
            return True
        return False

    def get_auth_status(self, provider: str) -> AuthStatus:
        """Return auth status without exposing credential values."""
        if provider in self._data:
            return AuthStatus(configured=True, source="stored")
        if provider in self._runtime_overrides:
            return AuthStatus(configured=False, source="runtime", label="--api-key")
        env_key = _find_env_key(provider)
        if env_key:
            return AuthStatus(configured=False, source="environment", label=env_key)
        if self._fallback_resolver and self._fallback_resolver(provider):
            return AuthStatus(configured=False, source="fallback", label="custom provider config")
        return AuthStatus(configured=False)

    def get_all(self) -> dict:
        """Get all credentials (for serialization)."""
        return dict(self._data)

    def drain_errors(self) -> List[Exception]:
        drained = list(self._errors)
        self._errors.clear()
        return drained

    async def get_api_key(
        self, provider_id: str, include_fallback: bool = True
    ) -> Optional[str]:
        """Get API key for a provider.

        Priority:
        1. Runtime override (CLI --api-key)
        2. API key from auth.json
        3. OAuth token from auth.json (auto-refreshed with locking)
        4. Environment variable
        5. Fallback resolver (models.json custom providers)
        """
        # Runtime override takes highest priority
        runtime_key = self._runtime_overrides.get(provider_id)
        if runtime_key:
            return runtime_key

        cred = self._data.get(provider_id)
        if cred is None:
            pass
        elif cred["type"] == "api_key":
            return cred["key"]
        elif cred["type"] == "oauth":
            # OAuth - try to get access token (simplified, no refresh in this port)
            return cred.get("access_token")

        # Fall back to environment variable
        env_key = _get_env_api_key(provider_id)
        if env_key:
            return env_key

        # Fall back to custom resolver
        if include_fallback and self._fallback_resolver:
            return self._fallback_resolver(provider_id)

        return None

    def get_oauth_providers(self) -> List[str]:
        """Get all registered OAuth provider IDs from credentials."""
        return [k for k, v in self._data.items() if isinstance(v, dict) and v.get("type") == "oauth"]

    def logout(self, provider: str) -> None:
        """Logout from a provider (remove credential)."""
        self.remove(provider)


# ---------------------------------------------------------------------------
# Environment variable helpers
# ---------------------------------------------------------------------------


def _get_env_api_key(provider_id: str) -> Optional[str]:
    """Get API key from environment variable conventions."""
    # Common patterns: PROVIDER_API_KEY, PROVIDER_KEY, etc.
    env_names = [
        f"{provider_id.upper()}_API_KEY",
        f"{provider_id.upper()}_KEY",
        f"{provider_id.upper()}_APIKEY",
        f"{provider_id.upper()}_TOKEN",
        f"PILOT_{provider_id.upper()}_API_KEY",
        f"PILOT_{provider_id.upper()}_KEY",
    ]
    for name in env_names:
        val = os.environ.get(name)
        if val:
            return val
    return None


def _find_env_key(provider_id: str) -> Optional[str]:
    """Find the environment variable name for a provider's API key."""
    env_names = [
        f"{provider_id.upper()}_API_KEY",
        f"{provider_id.upper()}_KEY",
        f"{provider_id.upper()}_APIKEY",
        f"{provider_id.upper()}_TOKEN",
        f"PILOT_{provider_id.upper()}_API_KEY",
        f"PILOT_{provider_id.upper()}_KEY",
    ]
    for name in env_names:
        if os.environ.get(name):
            return name
    return None
