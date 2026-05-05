"""Prompt templates and system prompt building functionality."""

from .prompt_templates import (
    expand_prompt_template,
    load_prompt_templates,
    parse_command_args,
    substitute_args,
)
from .system_prompt import build_system_prompt
from .types import (
    BuildSystemPromptOptions,
    LoadPromptTemplatesOptions,
    PromptTemplate,
    SourceInfo,
)

__all__ = [
    # Types
    "PromptTemplate",
    "SourceInfo",
    "LoadPromptTemplatesOptions",
    "BuildSystemPromptOptions",
    # Functions
    "parse_command_args",
    "substitute_args",
    "load_prompt_templates",
    "expand_prompt_template",
    "build_system_prompt",
]
