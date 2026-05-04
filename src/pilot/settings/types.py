"""Settings type definitions.

Maps to pi's settings types.
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, Field


class CompactionSettings(BaseModel):
    enabled: Optional[bool] = None
    reserve_tokens: Optional[int] = None
    keep_recent_tokens: Optional[int] = None


class BranchSummarySettings(BaseModel):
    reserve_tokens: Optional[int] = None
    skip_prompt: Optional[bool] = None


class ProviderRetrySettings(BaseModel):
    timeout_ms: Optional[int] = None
    max_retries: Optional[int] = None
    max_retry_delay_ms: Optional[int] = None


class RetrySettings(BaseModel):
    enabled: Optional[bool] = None
    max_retries: Optional[int] = None
    base_delay_ms: Optional[int] = None
    provider: Optional[ProviderRetrySettings] = None


class TerminalSettings(BaseModel):
    show_images: Optional[bool] = None
    image_width_cells: Optional[int] = None
    clear_on_shrink: Optional[bool] = None
    show_terminal_progress: Optional[bool] = None


class ImageSettings(BaseModel):
    auto_resize: Optional[bool] = None
    block_images: Optional[bool] = None


class ThinkingBudgetsSettings(BaseModel):
    minimal: Optional[int] = None
    low: Optional[int] = None
    medium: Optional[int] = None
    high: Optional[int] = None


class MarkdownSettings(BaseModel):
    code_block_indent: Optional[str] = None


class WarningSettings(BaseModel):
    anthropic_extra_usage: Optional[bool] = None


class PackageSource(BaseModel):
    """Package source for npm/git packages."""
    source: str
    extensions: Optional[List[str]] = None
    skills: Optional[List[str]] = None
    prompts: Optional[List[str]] = None
    themes: Optional[List[str]] = None


# Raw package source can be a string or an object
PackageSourceInput = Union[str, PackageSource]


class ThinkingLevels(BaseModel):
    off: Optional[str] = None
    minimal: Optional[str] = None
    low: Optional[str] = None
    medium: Optional[str] = None
    high: Optional[str] = None
    xhigh: Optional[str] = None


class Settings(BaseModel):
    """Top-level settings model matching pi's settings.json structure."""
    last_changelog_version: Optional[str] = None
    default_provider: Optional[str] = None
    default_model: Optional[str] = None
    default_thinking_level: Optional[Literal["off", "minimal", "low", "medium", "high", "xhigh"]] = None
    transport: Optional[str] = None
    steering_mode: Optional[Literal["all", "one-at-a-time"]] = None
    follow_up_mode: Optional[Literal["all", "one-at-a-time"]] = None
    theme: Optional[str] = None
    compaction: Optional[CompactionSettings] = None
    branch_summary: Optional[BranchSummarySettings] = None
    retry: Optional[RetrySettings] = None
    hide_thinking_block: Optional[bool] = None
    shell_path: Optional[str] = None
    quiet_startup: Optional[bool] = None
    shell_command_prefix: Optional[str] = None
    npm_command: Optional[List[str]] = None
    collapse_changelog: Optional[bool] = None
    enable_install_telemetry: Optional[bool] = None
    packages: Optional[List[PackageSourceInput]] = None
    extensions: Optional[List[str]] = None
    skills: Optional[List[str]] = None
    prompts: Optional[List[str]] = None
    themes: Optional[List[str]] = None
    enable_skill_commands: Optional[bool] = None
    terminal: Optional[TerminalSettings] = None
    images: Optional[ImageSettings] = None
    enabled_models: Optional[List[str]] = None
    double_escape_action: Optional[Literal["fork", "tree", "none"]] = None
    tree_filter_mode: Optional[Literal["default", "no-tools", "user-only", "labeled-only", "all"]] = None
    thinking_budgets: Optional[ThinkingBudgetsSettings] = None
    editor_padding_x: Optional[int] = None
    autocomplete_max_visible: Optional[int] = None
    show_hardware_cursor: Optional[bool] = None
    markdown: Optional[MarkdownSettings] = None
    warnings: Optional[WarningSettings] = None
    session_dir: Optional[str] = None


class SettingsError(BaseModel):
    scope: Literal["global", "project"]
    error: str


SettingsScope = Literal["global", "project"]
