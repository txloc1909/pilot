"""Settings manager — multi-scope settings with file persistence.

Maps to pi's ``settings-manager.ts``.

Supports global (~/.pi/agent/settings.json) and per-project (.pi/settings.json)
settings with deep merge (project overrides global). Uses file locking for
safe concurrent access.
"""

from __future__ import annotations

import json
import os
import time
from copy import deepcopy
from pathlib import Path
from typing import Callable, Dict, List, Optional, Protocol, Set, Tuple

from pilot.config import get_agent_dir, get_project_settings_path
from pilot.settings.types import (
    BranchSummarySettings,
    CompactionSettings,
    ImageSettings,
    MarkdownSettings,
    PackageSource,
    PackageSourceInput,
    ProviderRetrySettings,
    RetrySettings,
    Settings,
    SettingsError,
    SettingsScope,
    TerminalSettings,
    ThinkingBudgetsSettings,
    WarningSettings,
)


# ---------------------------------------------------------------------------
# Lock helper
# ---------------------------------------------------------------------------


def _acquire_file_lock_sync(path: Path, max_attempts: int = 10, delay_ms: int = 20) -> None:
    """Acquire an exclusive lock on a file using flock (POSIX).

    Retries on EBUSY/EAGAIN with exponential backoff.
    Raises IOError if lock cannot be acquired.
    """
    import fcntl

    fd = path.open("rb")
    for attempt in range(1, max_attempts + 1):
        try:
            fcntl.flock(fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return  # Lock acquired; caller is responsible for closing fd
        except (IOError, OSError) as e:
            if e.errno not in (errno.EAGAIN, errno.EBUSY) or attempt == max_attempts:
                raise
            time.sleep(delay_ms / 1000.0)
    raise IOError(f"Failed to acquire lock on {path}")


def _release_lock(fd) -> None:
    """Release a flock."""
    import fcntl

    try:
        fcntl.flock(fd.fileno(), fcntl.LOCK_UN)
    finally:
        fd.close()


# ---------------------------------------------------------------------------
# Deep merge helper
# ---------------------------------------------------------------------------


def _deep_merge_settings(base: dict, overrides: dict) -> dict:
    """Deep merge settings: project/overrides take precedence, nested objects merge recursively."""
    result = dict(base)
    for key, override_value in overrides.items():
        if override_value is None:
            continue
        base_value = base.get(key)
        if (
            isinstance(override_value, dict)
            and isinstance(base_value, dict)
        ):
            result[key] = _deep_merge_settings(base_value, override_value)
        else:
            result[key] = override_value
    return result


# ---------------------------------------------------------------------------
# Settings storage protocol
# ---------------------------------------------------------------------------


class SettingsStorage(Protocol):
    def with_lock(
        self, scope: SettingsScope, fn: Callable[[Optional[str]], Optional[str]]
    ) -> None: ...


# ---------------------------------------------------------------------------
# File settings storage
# ---------------------------------------------------------------------------


class FileSettingsStorage:
    """File-backed settings storage with POSIX file locking."""

    def __init__(self, cwd: str, agent_dir: str = "") -> None:
        agent_dir = agent_dir or get_agent_dir()
        self._global_path = Path(agent_dir) / "settings.json"
        self._project_path = Path(get_project_settings_path(cwd))

    def _acquire_lock_with_retry(self, path: Path, max_attempts: int = 10, delay_ms: int = 20) -> int:
        """Open file and acquire exclusive lock. Returns file descriptor."""
        import errno
        import fcntl

        fd = os.open(str(path), os.O_RDWR | os.O_CREAT, 0o644)
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

    def with_lock(
        self, scope: SettingsScope, fn: Callable[[Optional[str]], Optional[str]]
    ) -> None:
        path = self._global_path if scope == "global" else self._project_path
        parent = path.parent

        # Check if file exists
        file_exists = path.exists()

        fd: Optional[int] = None
        try:
            if file_exists:
                fd = self._acquire_lock_with_retry(path)

            current: Optional[str] = None
            if file_exists:
                with open(path, "r") as f:
                    current = f.read()

            next_content = fn(current)

            if next_content is not None:
                parent.mkdir(parents=True, exist_ok=True)
                if fd is None:
                    fd = self._acquire_lock_with_retry(path)
                with open(path, "w") as f:
                    f.write(next_content)
        finally:
            if fd is not None:
                try:
                    import fcntl
                    fcntl.flock(fd, fcntl.LOCK_UN)
                except (IOError, OSError):
                    pass
                os.close(fd)


# ---------------------------------------------------------------------------
# In-memory settings storage
# ---------------------------------------------------------------------------


class InMemorySettingsStorage:
    """In-memory settings storage (no file I/O)."""

    def __init__(self) -> None:
        self._global: Optional[str] = None
        self._project: Optional[str] = None

    def with_lock(
        self, scope: SettingsScope, fn: Callable[[Optional[str]], Optional[str]]
    ) -> None:
        current = self._global if scope == "global" else self._project
        next_content = fn(current)
        if next_content is not None:
            if scope == "global":
                self._global = next_content
            else:
                self._project = next_content


# ---------------------------------------------------------------------------
# Settings manager
# ---------------------------------------------------------------------------


class SettingsManager:
    """Multi-scope settings manager.

    Layers:
    1. Global settings (~/.pi/agent/settings.json)
    2. Project settings (<cwd>/.pi/settings.json) — overrides global

    Modified fields are tracked and persisted incrementally on save.
    """

    def __init__(
        self,
        storage: SettingsStorage,
        global_settings: dict,
        project_settings: dict,
        global_load_error: Optional[Exception] = None,
        project_load_error: Optional[Exception] = None,
        initial_errors: Optional[List[SettingsError]] = None,
    ) -> None:
        self._storage = storage
        self._global_settings = global_settings
        self._project_settings = project_settings
        self._global_load_error = global_load_error
        self._project_load_error = project_load_error
        self._errors: List[SettingsError] = list(initial_errors or [])
        self._settings: dict = _deep_merge_settings(global_settings, project_settings)

        # Track modified fields for incremental persistence
        self._modified_fields: Set[str] = set()
        self._modified_nested_fields: Dict[str, Set[str]] = {}
        self._modified_project_fields: Set[str] = set()
        self._modified_project_nested_fields: Dict[str, Set[str]] = {}
        self._write_queue_immediate = False

    # ---- Factory constructors ----

    @classmethod
    def create(cls, cwd: str, agent_dir: str = "") -> SettingsManager:
        """Create a SettingsManager that loads from files."""
        storage = FileSettingsStorage(cwd, agent_dir)
        return cls._from_storage(storage)

    @classmethod
    def _from_storage(cls, storage: SettingsStorage) -> SettingsManager:
        global_load = cls._try_load_from_storage(storage, "global")
        project_load = cls._try_load_from_storage(storage, "project")
        initial_errors: List[SettingsError] = []
        if global_load[1]:
            initial_errors.append(SettingsError(scope="global", error=str(global_load[1])))
        if project_load[1]:
            initial_errors.append(SettingsError(scope="project", error=str(project_load[1])))
        return cls(
            storage,
            global_load[0],
            project_load[0],
            global_load[1],
            project_load[1],
            initial_errors,
        )

    @classmethod
    def in_memory(cls, settings: Optional[dict] = None) -> SettingsManager:
        """Create an in-memory SettingsManager (no file I/O)."""
        storage = InMemorySettingsStorage()
        initial = cls._migrate_settings(deepcopy(settings or {}))
        storage.with_lock("global", lambda _: json.dumps(initial, indent=2))
        return cls._from_storage(storage)

    @classmethod
    def _load_from_storage(cls, storage: SettingsStorage, scope: SettingsScope) -> dict:
        content: Optional[str] = None
        
        def capture_content(current: Optional[str]) -> Optional[str]:
            nonlocal content
            content = current
            return None  # Return None to indicate no update
        
        storage.with_lock(scope, capture_content)
        if not content:
            return {}
        return cls._migrate_settings(json.loads(content))

    @classmethod
    def _try_load_from_storage(
        cls, storage: SettingsStorage, scope: SettingsScope
    ) -> Tuple[dict, Optional[Exception]]:
        try:
            return cls._load_from_storage(storage, scope), None
        except Exception as e:
            return {}, e

    @staticmethod
    def _migrate_settings(settings: dict) -> dict:
        """Migrate old settings format to new format."""
        s = deepcopy(settings)

        # Migrate queueMode -> steeringMode
        if "queueMode" in s and "steeringMode" not in s:
            s["steeringMode"] = s.pop("queueMode")

        # Migrate websockets boolean -> transport
        if "transport" not in s and "websockets" in s:
            s["transport"] = "websocket" if s.pop("websockets") else "sse"

        # Migrate old skills object to array
        if "skills" in s and isinstance(s["skills"], dict) and not isinstance(s["skills"], list):
            skills_obj = s.pop("skills")
            if "enableSkillCommands" in skills_obj:
                s.setdefault("enableSkillCommands", skills_obj["enableSkillCommands"])
            if skills_obj.get("customDirectories"):
                s["skills"] = skills_obj["customDirectories"]
            else:
                s.pop("skills", None)

        # Migrate retry.maxDelayMs -> retry.provider.maxRetryDelayMs
        if "retry" in s and isinstance(s["retry"], dict):
            retry = s["retry"]
            if isinstance(retry.get("maxDelayMs"), (int, float)):
                provider = retry.get("provider", {})
                if not isinstance(provider, dict):
                    provider = {}
                if "maxRetryDelayMs" not in provider:
                    provider["maxRetryDelayMs"] = retry.pop("maxDelayMs")
                retry["provider"] = provider

        return s

    # ---- Public API ----

    def get_global_settings(self) -> dict:
        return deepcopy(self._global_settings)

    def get_project_settings(self) -> dict:
        return deepcopy(self._project_settings)

    async def reload(self) -> None:
        global_load = self._try_load_from_storage(self._storage, "global")
        if not global_load[1]:
            self._global_settings = global_load[0]
            self._global_load_error = None
        else:
            self._global_load_error = global_load[1]
            self._record_error("global", str(global_load[1]))

        self._modified_fields.clear()
        self._modified_nested_fields.clear()
        self._modified_project_fields.clear()
        self._modified_project_nested_fields.clear()

        project_load = self._try_load_from_storage(self._storage, "project")
        if not project_load[1]:
            self._project_settings = project_load[0]
            self._project_load_error = None
        else:
            self._project_load_error = project_load[1]
            self._record_error("project", str(project_load[1]))

        self._settings = _deep_merge_settings(self._global_settings, self._project_settings)

    def apply_overrides(self, overrides: dict) -> None:
        self._settings = _deep_merge_settings(self._settings, overrides)

    def drain_errors(self) -> List[SettingsError]:
        drained = list(self._errors)
        self._errors.clear()
        return drained

    # ---- Internal helpers ----

    def _mark_modified(self, field: str, nested_key: Optional[str] = None) -> None:
        self._modified_fields.add(field)
        if nested_key:
            self._modified_nested_fields.setdefault(field, set()).add(nested_key)

    def _mark_project_modified(self, field: str, nested_key: Optional[str] = None) -> None:
        self._modified_project_fields.add(field)
        if nested_key:
            self._modified_project_nested_fields.setdefault(field, set()).add(nested_key)

    def _record_error(self, scope: SettingsScope, error: str) -> None:
        self._errors.append(SettingsError(scope=scope, error=error))

    def _clear_modified_scope(self, scope: SettingsScope) -> None:
        if scope == "global":
            self._modified_fields.clear()
            self._modified_nested_fields.clear()
        else:
            self._modified_project_fields.clear()
            self._modified_project_nested_fields.clear()

    def _persist_scoped_settings(
        self,
        scope: SettingsScope,
        snapshot: dict,
        modified_fields: Set[str],
        modified_nested: Dict[str, Set[str]],
    ) -> None:
        def persist(current: Optional[str]) -> Optional[str]:
            current_file = self._migrate_settings(json.loads(current)) if current else {}
            merged = dict(current_file)
            for field in modified_fields:
                value = snapshot.get(field)
                if field in modified_nested and isinstance(value, dict):
                    nested_modified = modified_nested[field]
                    base_nested = current_file.get(field, {})
                    if not isinstance(base_nested, dict):
                        base_nested = {}
                    nested_merged = dict(base_nested)
                    for nk in nested_modified:
                        if nk in value:
                            nested_merged[nk] = value[nk]
                    merged[field] = nested_merged
                else:
                    merged[field] = value
            return json.dumps(merged, indent=2)

        self._storage.with_lock(scope, persist)

    def _save(self) -> None:
        self._settings = _deep_merge_settings(self._global_settings, self._project_settings)

        if self._global_load_error:
            return

        snapshot = deepcopy(self._global_settings)
        modified_fields = set(self._modified_fields)
        modified_nested = {k: set(v) for k, v in self._modified_nested_fields.items()}

        self._persist_scoped_settings("global", snapshot, modified_fields, modified_nested)
        self._clear_modified_scope("global")

    def _save_project_settings(self, settings: dict) -> None:
        self._project_settings = deepcopy(settings)
        self._settings = _deep_merge_settings(self._global_settings, self._project_settings)

        if self._project_load_error:
            return

        snapshot = deepcopy(settings)
        modified_fields = set(self._modified_project_fields)
        modified_nested = {k: set(v) for k, v in self._modified_project_nested_fields.items()}

        self._persist_scoped_settings("project", snapshot, modified_fields, modified_nested)
        self._clear_modified_scope("project")

    # ---- Getters / Setters ----

    @property
    def _s(self) -> dict:
        return self._settings

    def get_last_changelog_version(self) -> Optional[str]:
        return self._s.get("lastChangelogVersion")

    def set_last_changelog_version(self, version: str) -> None:
        self._global_settings["lastChangelogVersion"] = version
        self._mark_modified("lastChangelogVersion")
        self._save()

    def get_session_dir(self) -> Optional[str]:
        sd = self._s.get("sessionDir")
        if sd is None:
            return None
        if sd == "~":
            return str(Path.home())
        if sd.startswith("~/"):
            return str(Path.home() / sd[2:])
        return sd

    def get_default_provider(self) -> Optional[str]:
        return self._s.get("defaultProvider")

    def get_default_model(self) -> Optional[str]:
        return self._s.get("defaultModel")

    def set_default_provider(self, provider: str) -> None:
        self._global_settings["defaultProvider"] = provider
        self._mark_modified("defaultProvider")
        self._save()

    def set_default_model(self, model_id: str) -> None:
        self._global_settings["defaultModel"] = model_id
        self._mark_modified("defaultModel")
        self._save()

    def set_default_model_and_provider(self, provider: str, model_id: str) -> None:
        self._global_settings["defaultProvider"] = provider
        self._global_settings["defaultModel"] = model_id
        self._mark_modified("defaultProvider")
        self._mark_modified("defaultModel")
        self._save()

    def get_steering_mode(self) -> str:
        return self._s.get("steeringMode") or "one-at-a-time"

    def set_steering_mode(self, mode: str) -> None:
        self._global_settings["steeringMode"] = mode
        self._mark_modified("steeringMode")
        self._save()

    def get_follow_up_mode(self) -> str:
        return self._s.get("followUpMode") or "one-at-a-time"

    def set_follow_up_mode(self, mode: str) -> None:
        self._global_settings["followUpMode"] = mode
        self._mark_modified("followUpMode")
        self._save()

    def get_theme(self) -> Optional[str]:
        return self._s.get("theme")

    def set_theme(self, theme: str) -> None:
        self._global_settings["theme"] = theme
        self._mark_modified("theme")
        self._save()

    def get_default_thinking_level(self) -> Optional[str]:
        return self._s.get("defaultThinkingLevel")

    def set_default_thinking_level(self, level: str) -> None:
        self._global_settings["defaultThinkingLevel"] = level
        self._mark_modified("defaultThinkingLevel")
        self._save()

    def get_transport(self) -> str:
        return self._s.get("transport") or "auto"

    def set_transport(self, transport: str) -> None:
        self._global_settings["transport"] = transport
        self._mark_modified("transport")
        self._save()

    def get_compaction_enabled(self) -> bool:
        comp = self._s.get("compaction")
        if isinstance(comp, dict):
            return comp.get("enabled", True)
        return True

    def set_compaction_enabled(self, enabled: bool) -> None:
        if "compaction" not in self._global_settings or not isinstance(self._global_settings["compaction"], dict):
            self._global_settings["compaction"] = {}
        self._global_settings["compaction"]["enabled"] = enabled
        self._mark_modified("compaction", "enabled")
        self._save()

    def get_compaction_reserve_tokens(self) -> int:
        comp = self._s.get("compaction")
        if isinstance(comp, dict):
            return comp.get("reserveTokens", 16384)
        return 16384

    def get_compaction_keep_recent_tokens(self) -> int:
        comp = self._s.get("compaction")
        if isinstance(comp, dict):
            return comp.get("keepRecentTokens", 20000)
        return 20000

    def get_compaction_settings(self) -> dict:
        return {
            "enabled": self.get_compaction_enabled(),
            "reserveTokens": self.get_compaction_reserve_tokens(),
            "keepRecentTokens": self.get_compaction_keep_recent_tokens(),
        }

    def get_branch_summary_settings(self) -> dict:
        bs = self._s.get("branchSummary", {})
        if not isinstance(bs, dict):
            bs = {}
        return {
            "reserveTokens": bs.get("reserveTokens", 16384),
            "skipPrompt": bs.get("skipPrompt", False),
        }

    def get_branch_summary_skip_prompt(self) -> bool:
        bs = self._s.get("branchSummary", {})
        if isinstance(bs, dict):
            return bs.get("skipPrompt", False)
        return False

    def get_retry_enabled(self) -> bool:
        retry = self._s.get("retry")
        if isinstance(retry, dict):
            return retry.get("enabled", True)
        return True

    def set_retry_enabled(self, enabled: bool) -> None:
        if "retry" not in self._global_settings or not isinstance(self._global_settings["retry"], dict):
            self._global_settings["retry"] = {}
        self._global_settings["retry"]["enabled"] = enabled
        self._mark_modified("retry", "enabled")
        self._save()

    def get_retry_settings(self) -> dict:
        retry = self._s.get("retry", {})
        if not isinstance(retry, dict):
            retry = {}
        return {
            "enabled": retry.get("enabled", True),
            "maxRetries": retry.get("maxRetries", 3),
            "baseDelayMs": retry.get("baseDelayMs", 2000),
        }

    def get_provider_retry_settings(self) -> dict:
        retry = self._s.get("retry", {})
        if not isinstance(retry, dict):
            retry = {}
        provider = retry.get("provider", {})
        if not isinstance(provider, dict):
            provider = {}
        return {
            "timeoutMs": provider.get("timeoutMs"),
            "maxRetries": provider.get("maxRetries"),
            "maxRetryDelayMs": provider.get("maxRetryDelayMs", 60000),
        }

    def get_hide_thinking_block(self) -> bool:
        return bool(self._s.get("hideThinkingBlock", False))

    def set_hide_thinking_block(self, hide: bool) -> None:
        self._global_settings["hideThinkingBlock"] = hide
        self._mark_modified("hideThinkingBlock")
        self._save()

    def get_shell_path(self) -> Optional[str]:
        return self._s.get("shellPath")

    def set_shell_path(self, path: Optional[str]) -> None:
        self._global_settings["shellPath"] = path
        self._mark_modified("shellPath")
        self._save()

    def get_quiet_startup(self) -> bool:
        return bool(self._s.get("quietStartup", False))

    def set_quiet_startup(self, quiet: bool) -> None:
        self._global_settings["quietStartup"] = quiet
        self._mark_modified("quietStartup")
        self._save()

    def get_shell_command_prefix(self) -> Optional[str]:
        return self._s.get("shellCommandPrefix")

    def set_shell_command_prefix(self, prefix: Optional[str]) -> None:
        self._global_settings["shellCommandPrefix"] = prefix
        self._mark_modified("shellCommandPrefix")
        self._save()

    def get_npm_command(self) -> Optional[List[str]]:
        cmd = self._s.get("npmCommand")
        return list(cmd) if cmd else None

    def set_npm_command(self, command: Optional[List[str]]) -> None:
        self._global_settings["npmCommand"] = list(command) if command else None
        self._mark_modified("npmCommand")
        self._save()

    def get_collapse_changelog(self) -> bool:
        return bool(self._s.get("collapseChangelog", False))

    def set_collapse_changelog(self, collapse: bool) -> None:
        self._global_settings["collapseChangelog"] = collapse
        self._mark_modified("collapseChangelog")
        self._save()

    def get_enable_install_telemetry(self) -> bool:
        return bool(self._s.get("enableInstallTelemetry", True))

    def set_enable_install_telemetry(self, enabled: bool) -> None:
        self._global_settings["enableInstallTelemetry"] = enabled
        self._mark_modified("enableInstallTelemetry")
        self._save()

    def get_packages(self) -> List[PackageSourceInput]:
        pkgs = self._s.get("packages", [])
        return list(pkgs) if pkgs else []

    def set_packages(self, packages: List[PackageSourceInput]) -> None:
        self._global_settings["packages"] = list(packages)
        self._mark_modified("packages")
        self._save()

    def set_project_packages(self, packages: List[PackageSourceInput]) -> None:
        proj = deepcopy(self._project_settings)
        proj["packages"] = list(packages)
        self._mark_project_modified("packages")
        self._save_project_settings(proj)

    def get_extension_paths(self) -> List[str]:
        exts = self._s.get("extensions", [])
        return list(exts) if exts else []

    def set_extension_paths(self, paths: List[str]) -> None:
        self._global_settings["extensions"] = list(paths)
        self._mark_modified("extensions")
        self._save()

    def set_project_extension_paths(self, paths: List[str]) -> None:
        proj = deepcopy(self._project_settings)
        proj["extensions"] = list(paths)
        self._mark_project_modified("extensions")
        self._save_project_settings(proj)

    def get_skill_paths(self) -> List[str]:
        skills = self._s.get("skills", [])
        return list(skills) if skills else []

    def set_skill_paths(self, paths: List[str]) -> None:
        self._global_settings["skills"] = list(paths)
        self._mark_modified("skills")
        self._save()

    def set_project_skill_paths(self, paths: List[str]) -> None:
        proj = deepcopy(self._project_settings)
        proj["skills"] = list(paths)
        self._mark_project_modified("skills")
        self._save_project_settings(proj)

    def get_prompt_template_paths(self) -> List[str]:
        prompts = self._s.get("prompts", [])
        return list(prompts) if prompts else []

    def set_prompt_template_paths(self, paths: List[str]) -> None:
        self._global_settings["prompts"] = list(paths)
        self._mark_modified("prompts")
        self._save()

    def set_project_prompt_template_paths(self, paths: List[str]) -> None:
        proj = deepcopy(self._project_settings)
        proj["prompts"] = list(paths)
        self._mark_project_modified("prompts")
        self._save_project_settings(proj)

    def get_theme_paths(self) -> List[str]:
        themes = self._s.get("themes", [])
        return list(themes) if themes else []

    def set_theme_paths(self, paths: List[str]) -> None:
        self._global_settings["themes"] = list(paths)
        self._mark_modified("themes")
        self._save()

    def set_project_theme_paths(self, paths: List[str]) -> None:
        proj = deepcopy(self._project_settings)
        proj["themes"] = list(paths)
        self._mark_project_modified("themes")
        self._save_project_settings(proj)

    def get_enable_skill_commands(self) -> bool:
        return bool(self._s.get("enableSkillCommands", True))

    def set_enable_skill_commands(self, enabled: bool) -> None:
        self._global_settings["enableSkillCommands"] = enabled
        self._mark_modified("enableSkillCommands")
        self._save()

    def get_thinking_budgets(self) -> Optional[dict]:
        return self._s.get("thinkingBudgets")

    def get_show_images(self) -> bool:
        term = self._s.get("terminal", {})
        if isinstance(term, dict):
            return bool(term.get("showImages", True))
        return True

    def set_show_images(self, show: bool) -> None:
        if "terminal" not in self._global_settings or not isinstance(self._global_settings["terminal"], dict):
            self._global_settings["terminal"] = {}
        self._global_settings["terminal"]["showImages"] = show
        self._mark_modified("terminal", "showImages")
        self._save()

    def get_image_width_cells(self) -> int:
        term = self._s.get("terminal", {})
        if isinstance(term, dict):
            w = term.get("imageWidthCells")
            if isinstance(w, (int, float)) and w > 0:
                return max(1, int(w))
        return 60

    def set_image_width_cells(self, width: int) -> None:
        if "terminal" not in self._global_settings or not isinstance(self._global_settings["terminal"], dict):
            self._global_settings["terminal"] = {}
        self._global_settings["terminal"]["imageWidthCells"] = max(1, int(width))
        self._mark_modified("terminal", "imageWidthCells")
        self._save()

    def get_clear_on_shrink(self) -> bool:
        term = self._s.get("terminal", {})
        if isinstance(term, dict) and "clearOnShrink" in term:
            return bool(term["clearOnShrink"])
        return os.environ.get("PILOT_CLEAR_ON_SHRINK") == "1"

    def set_clear_on_shrink(self, enabled: bool) -> None:
        if "terminal" not in self._global_settings or not isinstance(self._global_settings["terminal"], dict):
            self._global_settings["terminal"] = {}
        self._global_settings["terminal"]["clearOnShrink"] = enabled
        self._mark_modified("terminal", "clearOnShrink")
        self._save()

    def get_show_terminal_progress(self) -> bool:
        term = self._s.get("terminal", {})
        if isinstance(term, dict):
            return bool(term.get("showTerminalProgress", False))
        return False

    def set_show_terminal_progress(self, enabled: bool) -> None:
        if "terminal" not in self._global_settings or not isinstance(self._global_settings["terminal"], dict):
            self._global_settings["terminal"] = {}
        self._global_settings["terminal"]["showTerminalProgress"] = enabled
        self._mark_modified("terminal", "showTerminalProgress")
        self._save()

    def get_image_auto_resize(self) -> bool:
        images = self._s.get("images", {})
        if isinstance(images, dict):
            return bool(images.get("autoResize", True))
        return True

    def set_image_auto_resize(self, enabled: bool) -> None:
        if "images" not in self._global_settings or not isinstance(self._global_settings["images"], dict):
            self._global_settings["images"] = {}
        self._global_settings["images"]["autoResize"] = enabled
        self._mark_modified("images", "autoResize")
        self._save()

    def get_block_images(self) -> bool:
        images = self._s.get("images", {})
        if isinstance(images, dict):
            return bool(images.get("blockImages", False))
        return False

    def set_block_images(self, blocked: bool) -> None:
        if "images" not in self._global_settings or not isinstance(self._global_settings["images"], dict):
            self._global_settings["images"] = {}
        self._global_settings["images"]["blockImages"] = blocked
        self._mark_modified("images", "blockImages")
        self._save()

    def get_enabled_models(self) -> Optional[List[str]]:
        return self._s.get("enabledModels")

    def set_enabled_models(self, patterns: Optional[List[str]]) -> None:
        self._global_settings["enabledModels"] = patterns
        self._mark_modified("enabledModels")
        self._save()

    def get_double_escape_action(self) -> str:
        return self._s.get("doubleEscapeAction", "tree")

    def set_double_escape_action(self, action: str) -> None:
        self._global_settings["doubleEscapeAction"] = action
        self._mark_modified("doubleEscapeAction")
        self._save()

    def get_tree_filter_mode(self) -> str:
        mode = self._s.get("treeFilterMode", "default")
        valid = {"default", "no-tools", "user-only", "labeled-only", "all"}
        return mode if mode in valid else "default"

    def set_tree_filter_mode(self, mode: str) -> None:
        self._global_settings["treeFilterMode"] = mode
        self._mark_modified("treeFilterMode")
        self._save()

    def get_show_hardware_cursor(self) -> bool:
        val = self._s.get("showHardwareCursor")
        if val is not None:
            return bool(val)
        return os.environ.get("PILOT_HARDWARE_CURSOR") == "1"

    def set_show_hardware_cursor(self, enabled: bool) -> None:
        self._global_settings["showHardwareCursor"] = enabled
        self._mark_modified("showHardwareCursor")
        self._save()

    def get_editor_padding_x(self) -> int:
        return self._s.get("editorPaddingX", 0)

    def set_editor_padding_x(self, padding: int) -> None:
        self._global_settings["editorPaddingX"] = max(0, min(3, int(padding)))
        self._mark_modified("editorPaddingX")
        self._save()

    def get_autocomplete_max_visible(self) -> int:
        return self._s.get("autocompleteMaxVisible", 5)

    def set_autocomplete_max_visible(self, max_visible: int) -> None:
        self._global_settings["autocompleteMaxVisible"] = max(3, min(20, int(max_visible)))
        self._mark_modified("autocompleteMaxVisible")
        self._save()

    def get_code_block_indent(self) -> str:
        md = self._s.get("markdown", {})
        if isinstance(md, dict):
            return md.get("codeBlockIndent", "  ")
        return "  "

    def get_warnings(self) -> dict:
        warnings = self._s.get("warnings", {})
        if isinstance(warnings, dict):
            return dict(warnings)
        return {}

    def set_warnings(self, warnings: dict) -> None:
        self._global_settings["warnings"] = dict(warnings)
        self._mark_modified("warnings")
        self._save()
