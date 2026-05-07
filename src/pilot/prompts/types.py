"""Type definitions for prompt templates and system prompt building."""

from typing import Any, List, Optional
from pydantic import BaseModel, Field

from pilot_core.types import Skill


class SourceInfo(BaseModel):
    """Information about the source of a prompt template."""
    source: str = Field(..., description="Source type (local, remote, etc.)")
    scope: Optional[str] = Field(None, description="Scope of the source (user, project, etc.)")
    baseDir: Optional[str] = Field(None, description="Base directory for the source")
    filePath: Optional[str] = Field(None, description="Full path to the file")


class PromptTemplate(BaseModel):
    """Represents a prompt template loaded from a markdown file."""
    name: str = Field(..., description="Name of the template (used in /name invocation)")
    description: str = Field(..., description="Short description of the template")
    argumentHint: Optional[str] = Field(None, description="Hint about expected arguments")
    content: str = Field(..., description="The actual template content")
    sourceInfo: SourceInfo = Field(..., description="Information about the template source")
    filePath: str = Field(..., description="Full path to the template file")


class LoadPromptTemplatesOptions(BaseModel):
    """Options for loading prompt templates."""
    cwd: str = Field(..., description="Working directory for project-local templates")
    agentDir: Optional[str] = Field(None, description="Agent config directory for global templates")
    promptPaths: List[str] = Field(default_factory=list, description="Explicit prompt template paths")
    includeDefaults: bool = Field(True, description="Include default prompt directories")


class BuildSystemPromptOptions(BaseModel):
    """Options for building the system prompt."""
    customPrompt: Optional[str] = Field(None, description="Custom system prompt (replaces default)")
    selectedTools: Optional[List[str]] = Field(None, description="Tools to include in prompt")
    toolSnippets: Optional[dict[str, str]] = Field(None, description="One-line tool snippets keyed by tool name")
    promptGuidelines: Optional[List[str]] = Field(None, description="Additional guideline bullets")
    appendSystemPrompt: Optional[str] = Field(None, description="Text to append to system prompt")
    cwd: str = Field(..., description="Working directory")
    contextFiles: Optional[List[dict[str, Any]]] = Field(None, description="Pre-loaded context files")
    skills: Optional[List[Skill]] = Field(None, description="Pre-loaded skills")
