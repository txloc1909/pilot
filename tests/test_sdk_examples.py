"""Tests for SDK examples.

Validates that example files are syntactically correct and can be imported.
Execution tests are simplified since examples require API keys.
"""

from __future__ import annotations

import importlib
import importlib.util
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pilot.sdk import AgentSession, create_agent_session


# =====================================================================
# Tests: Example imports
# =====================================================================


class TestExampleImports:
    """Tests for example file imports."""

    def test_01_minimal_importable(self) -> None:
        """01_minimal example can be imported."""
        spec = importlib.util.spec_from_file_location(
            "sdk.01_minimal",
            str(Path(__file__).parent.parent / "examples" / "sdk" / "01_minimal.py"),
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        assert hasattr(module, "main")
        assert callable(module.main)

    def test_02_custom_model_importable(self) -> None:
        """02_custom_model example can be imported."""
        spec = importlib.util.spec_from_file_location(
            "sdk.02_custom_model",
            str(Path(__file__).parent.parent / "examples" / "sdk" / "02_custom_model.py"),
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        assert hasattr(module, "main")
        assert callable(module.main)

    def test_03_read_only_importable(self) -> None:
        """03_read_only example can be imported."""
        spec = importlib.util.spec_from_file_location(
            "sdk.03_read_only",
            str(Path(__file__).parent.parent / "examples" / "sdk" / "03_read_only.py"),
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        assert hasattr(module, "main")
        assert callable(module.main)

    def test_04_in_memory_importable(self) -> None:
        """04_in_memory example can be imported."""
        spec = importlib.util.spec_from_file_location(
            "sdk.04_in_memory",
            str(Path(__file__).parent.parent / "examples" / "sdk" / "04_in_memory.py"),
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        assert hasattr(module, "main")
        assert callable(module.main)


# =====================================================================
# Tests: Example structure validation
# =====================================================================


class TestExampleStructure:
    """Tests for example file structure."""

    def test_examples_have_async_main(self) -> None:
        """All examples have async main() function."""
        import asyncio

        examples_dir = Path(__file__).parent.parent / "examples" / "sdk"
        for py_file in sorted(examples_dir.glob("*.py")):
            if py_file.name.startswith("__"):
                continue

            spec = importlib.util.spec_from_file_location(
                f"sdk.{py_file.stem}",
                str(py_file),
            )
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            assert hasattr(module, "main"), f"{py_file.name} missing main()"
            assert asyncio.iscoroutinefunction(module.main), f"{py_file.name}.main() is not async"

    def test_examples_use_create_agent_session(self) -> None:
        """All examples use create_agent_session."""
        examples_dir = Path(__file__).parent.parent / "examples" / "sdk"
        for py_file in sorted(examples_dir.glob("*.py")):
            if py_file.name.startswith("__"):
                continue

            content = py_file.read_text()
            assert "create_agent_session" in content, (
                f"{py_file.name} does not use create_agent_session"
            )

    def test_examples_call_dispose(self) -> None:
        """All examples call dispose() in finally block."""
        examples_dir = Path(__file__).parent.parent / "examples" / "sdk"
        for py_file in sorted(examples_dir.glob("*.py")):
            if py_file.name.startswith("__"):
                continue

            content = py_file.read_text()
            assert "session.dispose()" in content, (
                f"{py_file.name} does not call session.dispose()"
            )


# =====================================================================
# Tests: Example file syntax
# =====================================================================


class TestExampleSyntax:
    """Tests for example file syntax."""

    def test_all_examples_compile(self) -> None:
        """All example files compile without syntax errors."""
        examples_dir = Path(__file__).parent.parent / "examples" / "sdk"
        for py_file in examples_dir.glob("*.py"):
            try:
                compile(py_file.read_text(), py_file.name, "exec")
            except SyntaxError as e:
                pytest.fail(f"Syntax error in {py_file.name}: {e}")
