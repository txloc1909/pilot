# pilot-toy-ext

A toy extension for pilot that demonstrates
the Python extension system.

## What it registers

| Type | Name | Description |
|------|------|-------------|
| Tool | `toy_echo` | Echoes a message back |
| Tool | `toy_counter` | Stateful counter (increment/reset/get) with session persistence |
| Command | `/greet` | Interactive greeting via `ctx.ui.input()` |
| Flag | `verbose` | Boolean flag, default `false` |

## Event logging

Every lifecycle event (`session_start`, `agent_start`, `agent_end`,
`tool_call`, `tool_result`, `session_shutdown`) is appended to
`pilot_toy_ext.handlers.EVENT_LOG` so tests can verify the extension
observed the expected lifecycle.

## Installation

```bash
cd examples/toy-extension
pip install -e .
```

The entry point is declared in `pyproject.toml`:

```toml
[project.entry-points."pilot.extensions"]
toy-ext = "pilot_toy_ext:register_extension"
```

Pilot's loader discovers it automatically via
`importlib.metadata.entry_points(group="pilot.extensions")`.

## Usage

After installation, pilot loads the extension automatically. The `toy_echo`
and `toy_counter` tools appear in the tool list, `/greet` is available as
a slash command, and `verbose` can be toggled via `api.get_flag("verbose")`.
