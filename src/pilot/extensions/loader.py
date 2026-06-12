"""Extension loader — discovers and loads Python extension modules.

Ported from pi-coding-agent/dist/core/extensions/loader.ts.

Uses Python's native import mechanisms instead of jiti:
- `importlib.util.spec_from_file_location()` for .py files
- `importlib.metadata.entry_points()` for installed packages
- Directory extensions via pyproject.toml or pilot-extension.toml config
"""

from __future__ import annotations

import importlib
import importlib.metadata
import importlib.util
import logging
import sys
import tomllib
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

from pilot.config import CONFIG_DIR_NAME, get_agent_dir
from pilot.extensions.event_bus import EventBus, EventBusController, create_event_bus
from pilot.extensions.types import (
    Extension,
    ExtensionAPI,
    ExtensionFactory,
    ExtensionFlag,
    ExtensionRuntime,
    ExtensionRuntimeState,
    LoadExtensionsResult,
    RegisteredCommand,
    RegisteredTool,
    create_synthetic_source_info,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Runtime creation
# ---------------------------------------------------------------------------


def create_extension_runtime() -> ExtensionRuntime:
    """Create a runtime with throwing stubs for action methods.

    Runner.bind_core() replaces these with real implementations.
    """

    def _not_initialized(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError(
            "Extension runtime not initialized. "
            "Action methods cannot be called during extension loading."
        )

    state = ExtensionRuntimeState()

    runtime = ExtensionRuntime(
        state=state,
        send_message=_not_initialized,
        send_user_message=_not_initialized,
        append_entry=_not_initialized,
        set_session_name=_not_initialized,
        get_session_name=_not_initialized,
        set_label=_not_initialized,
        get_active_tools=_not_initialized,
        get_all_tools=_not_initialized,
        set_active_tools=_not_initialized,
        refresh_tools=lambda: None,
        get_commands=_not_initialized,
        set_model=lambda *a, **kw: None,
        get_thinking_level=_not_initialized,
        set_thinking_level=_not_initialized,
        register_provider=lambda *a, **kw: _queue_provider_registration(runtime, *a, **kw),
        unregister_provider=lambda *a, **kw: _remove_queued_registration(runtime, *a, **kw),
    )

    return runtime


def _queue_provider_registration(
    runtime: ExtensionRuntime, name: str, config: Any, extension_path: str = "<unknown>"
) -> None:
    """Queue provider registration during loading."""
    runtime.state.pending_provider_registrations.append(
        {"name": name, "config": config, "extension_path": extension_path}
    )


def _remove_queued_registration(runtime: ExtensionRuntime, name: str, **kw: Any) -> None:
    """Remove a queued provider registration."""
    runtime.state.pending_provider_registrations = [
        r for r in runtime.state.pending_provider_registrations if r["name"] != name
    ]


# ---------------------------------------------------------------------------
# Extension creation
# ---------------------------------------------------------------------------


def _create_extension(extension_path: str, resolved_path: str) -> Extension:
    """Create an Extension object with empty collections."""
    source = "local"
    if extension_path.startswith("<") and extension_path.endswith(">"):
        source = extension_path[1:-1].split(":")[0] or "temporary"

    base_dir = str(Path(resolved_path).parent) if not extension_path.startswith("<") else None

    return Extension(
        path=extension_path,
        resolved_path=resolved_path,
        source_info=create_synthetic_source_info(
            extension_path, source=source, base_dir=base_dir
        ),
        handlers={},
        tools={},
        commands={},
        flags={},
    )


def _create_extension_api(
    extension: Extension,
    runtime: ExtensionRuntime,
    cwd: str,
    event_bus: EventBus,
) -> ExtensionAPI:
    """Create the ExtensionAPI for an extension.

    Registration methods write to the extension object.
    Action methods delegate to the shared runtime.
    """

    class _ExtensionAPIImpl:
        """Concrete ExtensionAPI implementation."""

        def on(self, event: str, handler: Callable[..., Any]) -> None:
            _assert_active(runtime)
            handlers = extension.handlers.get(event, [])
            handlers.append(handler)
            extension.handlers[event] = handlers

        def register_tool(self, tool: ToolDefinition) -> None:
            _assert_active(runtime)
            extension.tools[tool.name] = RegisteredTool(
                definition=tool,
                source_info=extension.source_info,
            )
            if runtime.refresh_tools:
                runtime.refresh_tools()

        def register_command(self, name: str, options: Dict[str, Any]) -> None:
            _assert_active(runtime)
            handler = options.get("handler")
            if not handler:
                raise ValueError(f"Command '{name}' must have a handler")
            extension.commands[name] = RegisteredCommand(
                name=name,
                source_info=extension.source_info,
                description=options.get("description"),
                handler=handler,
            )

        def register_flag(self, name: str, options: Dict[str, Any]) -> None:
            _assert_active(runtime)
            extension.flags[name] = ExtensionFlag(
                name=name,
                description=options.get("description"),
                type=options.get("type", "boolean"),
                default=options.get("default"),
                extension_path=extension.path,
            )
            if options.get("default") is not None and name not in runtime.state.flag_values:
                runtime.state.flag_values[name] = options["default"]

        def get_flag(self, name: str) -> Optional[Union[bool, str]]:
            _assert_active(runtime)
            if name not in extension.flags:
                return None
            return runtime.state.flag_values.get(name)

        def send_message(
            self, message: Dict[str, Any], options: Optional[Dict[str, Any]] = None
        ) -> None:
            _assert_active(runtime)
            if runtime.send_message:
                runtime.send_message(message, options)

        def send_user_message(
            self,
            content: Union[str, list],
            options: Optional[Dict[str, Any]] = None,
        ) -> None:
            _assert_active(runtime)
            if runtime.send_user_message:
                runtime.send_user_message(content, options)

        def append_entry(self, custom_type: str, data: Any = None) -> None:
            _assert_active(runtime)
            if runtime.append_entry:
                runtime.append_entry(custom_type, data)

        def set_session_name(self, name: str) -> None:
            _assert_active(runtime)
            if runtime.set_session_name:
                runtime.set_session_name(name)

        def get_session_name(self) -> Optional[str]:
            _assert_active(runtime)
            if runtime.get_session_name:
                return runtime.get_session_name()
            return None

        def set_label(self, entry_id: str, label: Optional[str]) -> None:
            _assert_active(runtime)
            if runtime.set_label:
                runtime.set_label(entry_id, label)

        async def exec(
            self,
            command: str,
            args: List[str],
            options: Optional[Dict[str, Any]] = None,
        ) -> Dict[str, Any]:
            _assert_active(runtime)
            import asyncio

            proc_cwd = options.get("cwd", cwd) if options else cwd
            timeout = options.get("timeout") if options else None

            try:
                proc = await asyncio.create_subprocess_exec(
                    command,
                    *args,
                    cwd=proc_cwd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                if timeout:
                    stdout, stderr = await asyncio.wait_for(
                        proc.communicate(), timeout=timeout / 1000
                    )
                else:
                    stdout, stderr = await proc.communicate()

                return {
                    "stdout": stdout.decode(errors="replace"),
                    "stderr": stderr.decode(errors="replace"),
                    "code": proc.returncode,
                    "killed": False,
                }
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                return {"stdout": "", "stderr": "Timed out", "code": -1, "killed": True}

        def get_active_tools(self) -> List[str]:
            _assert_active(runtime)
            if runtime.get_active_tools:
                return runtime.get_active_tools()
            return []

        def get_all_tools(self) -> List[Dict[str, Any]]:
            _assert_active(runtime)
            if runtime.get_all_tools:
                return runtime.get_all_tools()
            return []

        def set_active_tools(self, tool_names: List[str]) -> None:
            _assert_active(runtime)
            if runtime.set_active_tools:
                runtime.set_active_tools(tool_names)

        def get_commands(self) -> List[Dict[str, Any]]:
            _assert_active(runtime)
            if runtime.get_commands:
                return runtime.get_commands()
            return []

        async def set_model(self, model: Any) -> bool:
            _assert_active(runtime)
            if runtime.set_model:
                return await runtime.set_model(model)
            return False

        def get_thinking_level(self) -> str:
            _assert_active(runtime)
            if runtime.get_thinking_level:
                return runtime.get_thinking_level()
            return "off"

        def set_thinking_level(self, level: str) -> None:
            _assert_active(runtime)
            if runtime.set_thinking_level:
                runtime.set_thinking_level(level)

        @property
        def events(self) -> EventBus:
            return event_bus

    return _ExtensionAPIImpl()  # type: ignore[return-value]


def _assert_active(runtime: ExtensionRuntime) -> None:
    """Check that the runtime is not stale."""
    if runtime.state.stale_message:
        raise RuntimeError(runtime.state.stale_message)


# ---------------------------------------------------------------------------
# Extension loading
# ---------------------------------------------------------------------------


def _load_file_extension(
    file_path: Path,
    cwd: str,
    event_bus: EventBus,
    runtime: ExtensionRuntime,
) -> Tuple[Optional[Extension], Optional[str]]:
    """Load an extension from a single .py file."""
    resolved = str(file_path.resolve())
    try:
        spec = importlib.util.spec_from_file_location(file_path.stem, resolved)
        if not spec or not spec.loader:
            return None, f"Cannot load module spec from {file_path}"

        module = importlib.util.module_from_spec(spec)
        # Add to sys.modules temporarily for relative imports within the extension
        sys.modules[file_path.stem] = module
        try:
            spec.loader.exec_module(module)
        finally:
            sys.modules.pop(file_path.stem, None)

        # Look for factory function
        factory = _find_factory(module, file_path)
        if not factory:
            return None, f"Extension does not export a valid factory function: {file_path}"

        extension = _create_extension(str(file_path), resolved)
        api = _create_extension_api(extension, runtime, cwd, event_bus)
        _run_factory(factory, api)

        return extension, None
    except Exception as err:
        return None, f"Failed to load extension {file_path}: {err}"


def _load_directory_extension(
    dir_path: Path,
    cwd: str,
    event_bus: EventBus,
    runtime: ExtensionRuntime,
) -> Tuple[Optional[Extension], Optional[str]]:
    """Load an extension from a directory."""
    # Check for config files
    config_path = dir_path / "pyproject.toml"
    if not config_path.exists():
        config_path = dir_path / "pilot-extension.toml"

    if config_path.exists():
        entry_point_str = _parse_extension_config(config_path)
        if entry_point_str:
            return _load_entry_point_string(entry_point_str, str(dir_path), cwd, event_bus, runtime)

    # Check for __init__.py
    init_path = dir_path / "__init__.py"
    if init_path.exists():
        return _load_file_extension(init_path, cwd, event_bus, runtime)

    return None, f"No entry points found in {dir_path}"


def _load_entry_point_string(
    entry_point_str: str,
    base_path: str,
    cwd: str,
    event_bus: EventBus,
    runtime: ExtensionRuntime,
) -> Tuple[Optional[Extension], Optional[str]]:
    """Load an extension from an entry point string like 'module:func'."""
    try:
        if ":" not in entry_point_str:
            return None, f"Invalid entry point format (expected 'module:func'): {entry_point_str}"

        module_name, func_name = entry_point_str.split(":", 1)

        # Add base_path to sys.path temporarily
        if base_path not in sys.path:
            sys.path.insert(0, base_path)
        try:
            module = importlib.import_module(module_name)
        finally:
            if base_path in sys.path:
                sys.path.remove(base_path)

        func = getattr(module, func_name, None)
        if not func:
            return None, f"Module '{module_name}' has no attribute '{func_name}'"

        extension = _create_extension(f"<{base_path}>", base_path)
        api = _create_extension_api(extension, runtime, cwd, event_bus)
        _run_factory(func, api)

        return extension, None
    except Exception as err:
        return None, f"Failed to load extension from {base_path}: {err}"


def _find_factory(module: Any, file_path: Path) -> Optional[Callable[..., Any]]:
    """Find the extension factory function in a module.

    Checks for:
    1. register_extension(api) function
    2. default export that is callable
    """
    # Preferred: explicit register_extension function
    if hasattr(module, "register_extension") and callable(module.register_extension):
        return module.register_extension

    # Fallback: default export (for compatibility with TS-style extensions)
    if hasattr(module, "default") and callable(module.default):
        return module.default

    return None


def _run_factory(factory: Callable[..., Any], api: ExtensionAPI) -> None:
    """Run an extension factory function, handling both sync and async."""
    import asyncio

    result = factory(api)
    # If the factory returns a coroutine, await it
    if asyncio.iscoroutine(result):
        try:
            loop = asyncio.get_running_loop()
            # We're in an async context — cannot use loop.run_until_complete()
            # Schedule as a task and hope the caller awaits it
            # For synchronous loading, this is a limitation
            logger.warning(
                "Async extension factory detected in synchronous context. "
                "Use sync factory or load extensions in an async context."
            )
        except RuntimeError:
            # No event loop running — we can run it
            asyncio.run(result)


def _parse_extension_config(config_path: Path) -> Optional[str]:
    """Parse extension config to find entry point.

    Supports:
    - pyproject.toml: [project.entry-points."pilot.extensions"]
    - pilot-extension.toml: entry_point = "module:func"
    """
    try:
        with config_path.open("rb") as f:
            config = tomllib.load(f)

        # pyproject.toml format
        if "project" in config:
            entry_points = (
                config.get("project", {})
                .get("entry-points", {})
                .get("pilot.extensions", {})
            )
            if entry_points:
                return next(iter(entry_points.values()), None)

        # pilot-extension.toml format
        return config.get("entry_point")
    except Exception as err:
        logger.warning(f"Failed to parse {config_path}: {err}")
        return None


# ---------------------------------------------------------------------------
# Extension discovery
# ---------------------------------------------------------------------------


def _is_extension_file(name: str) -> bool:
    """Check if a filename is an extension file."""
    return name.endswith(".py") and not name.startswith("_")


def discover_extensions_in_dir(dir_path: Union[str, Path]) -> List[str]:
    """Discover extension entry points in a directory.

    Discovery rules:
    1. Direct files: `extensions/*.py` → load
    2. Subdirectory with __init__.py: `extensions/*/ __init__.py` → load
    3. Subdirectory with pyproject.toml: `extensions/*/pyproject.toml` with entry point → load

    No recursion beyond one level.
    """
    dir_path = Path(dir_path)
    if not dir_path.exists():
        return []

    discovered: List[str] = []

    try:
        entries = sorted(dir_path.iterdir())
    except PermissionError:
        return []

    for entry in entries:
        if entry.name.startswith("_") or entry.name.startswith("."):
            continue

        # Direct .py files
        if entry.is_file() and _is_extension_file(entry.name):
            discovered.append(str(entry.resolve()))
            continue

        # Subdirectories
        if entry.is_dir():
            # Check for pyproject.toml or pilot-extension.toml
            config_path = entry / "pyproject.toml"
            if not config_path.exists():
                config_path = entry / "pilot-extension.toml"

            if config_path.exists():
                ep_str = _parse_extension_config(config_path)
                if ep_str:
                    discovered.append(str(entry.resolve()))
                    continue

            # Check for __init__.py
            init_path = entry / "__init__.py"
            if init_path.exists():
                discovered.append(str(entry.resolve()))

    return discovered


# ---------------------------------------------------------------------------
# Entry point discovery
# ---------------------------------------------------------------------------


def _discover_entry_point_extensions() -> List[Tuple[str, Callable[..., Any]]]:
    """Discover extensions registered via entry points (group='pilot.extensions')."""
    discovered = []
    try:
        eps = importlib.metadata.entry_points()
        # Python 3.12+ has .select()
        if hasattr(eps, "select"):
            pilot_eps = eps.select(group="pilot.extensions")
        else:
            pilot_eps = eps.get("pilot.extensions", [])

        for ep in pilot_eps:
            try:
                factory = ep.load()
                discovered.append((ep.name, factory))
            except Exception as err:
                logger.error(f"Failed to load entry point extension {ep.name}: {err}")
    except Exception as err:
        logger.warning(f"Failed to discover entry point extensions: {err}")

    return discovered


# ---------------------------------------------------------------------------
# Main loading functions
# ---------------------------------------------------------------------------


def load_extensions(
    paths: List[str],
    cwd: str,
    event_bus: Optional[EventBusController] = None,
    runtime: Optional[ExtensionRuntime] = None,
) -> LoadExtensionsResult:
    """Load extensions from a list of file/directory paths."""
    from pathlib import Path

    extensions: List[Extension] = []
    errors: List[Dict[str, str]] = []

    resolved_cwd = str(Path(cwd).resolve())
    resolved_event_bus = event_bus or create_event_bus()
    resolved_runtime = runtime or create_extension_runtime()

    for ext_path in paths:
        path = Path(ext_path)
        extension: Optional[Extension] = None
        error: Optional[str] = None

        if path.is_file() and path.suffix == ".py":
            extension, error = _load_file_extension(
                path, resolved_cwd, resolved_event_bus, resolved_runtime
            )
        elif path.is_dir():
            extension, error = _load_directory_extension(
                path, resolved_cwd, resolved_event_bus, resolved_runtime
            )
        else:
            error = f"Extension path is not a .py file or directory: {ext_path}"

        if error:
            errors.append({"path": ext_path, "error": error})
            continue

        if extension:
            extensions.append(extension)

    return LoadExtensionsResult(
        extensions=extensions,
        errors=errors,
        runtime=resolved_runtime,
    )


def _load_inline_factory(
    factory: ExtensionFactory,
    cwd: str,
    event_bus: EventBusController,
    runtime: ExtensionRuntime,
    extension_path: str = "<inline>",
) -> Extension:
    """Create an Extension from an inline factory function."""
    extension = _create_extension(extension_path, extension_path)
    api = _create_extension_api(extension, runtime, cwd, event_bus)
    _run_factory(factory, api)
    return extension


def discover_and_load_extensions(
    configured_paths: List[str],
    cwd: str,
    agent_dir: Optional[str] = None,
    event_bus: Optional[EventBusController] = None,
) -> LoadExtensionsResult:
    """Discover and load extensions from standard locations.

    Discovery order:
    1. Project-local: cwd/.pi/extensions/
    2. Global: agent_dir/extensions/
    3. Explicitly configured paths from settings
    4. Entry points (pilot.extensions group)
    """
    from pathlib import Path

    resolved_cwd = str(Path(cwd).resolve())
    resolved_agent_dir = str(Path(agent_dir or get_agent_dir()).resolve())

    all_paths: List[str] = []
    seen: set[str] = set()

    def _add_paths(paths: List[str]) -> None:
        for p in paths:
            resolved = str(Path(p).resolve())
            if resolved not in seen:
                seen.add(resolved)
                all_paths.append(p)

    # 1. Project-local extensions: cwd/.pi/extensions/
    local_ext_dir = Path(resolved_cwd) / CONFIG_DIR_NAME / "extensions"
    _add_paths(discover_extensions_in_dir(local_ext_dir))

    # 2. Global extensions: agentDir/extensions/
    global_ext_dir = Path(resolved_agent_dir) / "extensions"
    _add_paths(discover_extensions_in_dir(global_ext_dir))

    # 3. Explicitly configured paths
    for p in configured_paths:
        resolved = str(Path(p).resolve())
        path = Path(resolved)
        if path.exists() and path.is_dir():
            # Discover in directory
            _add_paths(discover_extensions_in_dir(path))
        elif path.exists() and path.suffix == ".py":
            _add_paths([resolved])

    # 4. Entry point extensions
    ep_extensions = _discover_entry_point_extensions()
    # Entry points are loaded differently — they have their own factories

    # Load file/directory extensions
    resolved_event_bus = event_bus or create_event_bus()
    resolved_runtime = create_extension_runtime()

    result = load_extensions(all_paths, cwd, resolved_event_bus, resolved_runtime)

    # Load entry point extensions
    for ep_name, factory in ep_extensions:
        try:
            extension = _load_inline_factory(
                factory, cwd, resolved_event_bus, resolved_runtime, f"<entrypoint:{ep_name}>"
            )
            result.extensions.append(extension)
        except Exception as err:
            result.errors.append({
                "path": f"<entrypoint:{ep_name}>",
                "error": str(err),
            })

    return result
