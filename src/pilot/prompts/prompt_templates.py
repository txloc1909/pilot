"""Prompt template loading, parsing, and expansion functionality."""

import os
from pathlib import Path
from typing import List, Optional, Tuple

from .types import LoadPromptTemplatesOptions, PromptTemplate, SourceInfo


def parse_command_args(args_string: str) -> List[str]:
    """
    Parse command arguments respecting quoted strings (bash-style).
    Returns array of arguments.
    
    Examples:
        'foo bar "baz qux"' -> ['foo', 'bar', 'baz qux']
        "a 'b c' d" -> ['a', 'b c', 'd']
    """
    args = []
    current = ""
    in_quote = None
    
    for char in args_string:
        if in_quote:
            if char == in_quote:
                in_quote = None
            else:
                current += char
        elif char == '"' or char == "'":
            in_quote = char
        elif char == " " or char == "\t":
            if current:
                args.append(current)
                current = ""
        else:
            current += char
    
    if current:
        args.append(current)
    
    return args


def substitute_args(content: str, args: List[str]) -> str:
    """
    Substitute argument placeholders in template content.
    
    Supports:
    - $1, $2, ... for positional args
    - $@ and $ARGUMENTS for all args
    - ${@:N} for args from Nth onwards (bash-style slicing)
    - ${@:N:L} for L args starting from Nth
    
    Note: Replacement happens on the template string only. Argument values
    containing patterns like $1, $@, or $ARGUMENTS are NOT recursively substituted.
    """
    import re
    
    result = content
    
    # Replace $1, $2, etc. with positional args FIRST (before wildcards)
    # This prevents wildcard replacement values containing $<digit> patterns from being re-substituted
    result = re.sub(r'\$(\d+)', lambda m: args[int(m.group(1)) - 1] if int(m.group(1)) - 1 < len(args) else "", result)
    
    # Replace ${@:start} or ${@:start:length} with sliced args (bash-style)
    # Process BEFORE simple $@ to avoid conflicts
    def replace_sliced(match):
        start_str = match.group(1)
        length_str = match.group(2)
        start = int(start_str) - 1  # Convert to 0-indexed (user provides 1-indexed)
        # Treat 0 as 1 (bash convention: args start at 1)
        if start < 0:
            start = 0
        if length_str:
            length = int(length_str)
            return " ".join(args[start:start + length])
        return " ".join(args[start:])
    
    result = re.sub(r'\$\{@:(\d+)(?::(\d+))?\}', replace_sliced, result)
    
    # Pre-compute all args joined (optimization)
    all_args = " ".join(args)
    
    # Replace $ARGUMENTS with all args joined (new syntax, aligns with Claude, Codex, OpenCode)
    result = result.replace("$ARGUMENTS", all_args)
    
    # Replace $@ with all args joined (existing syntax)
    result = result.replace("$@", all_args)
    
    return result


def _parse_frontmatter(content: str) -> Tuple[dict, str]:
    """
    Parse YAML frontmatter from markdown content.
    Returns (frontmatter_dict, body_content).
    """
    if content.startswith("---"):
        end_marker = content.find("\n---", 3)
        if end_marker != -1:
            frontmatter_text = content[3:end_marker].strip()
            body = content[end_marker + 4:].lstrip()
            
            # Simple YAML parsing (key: value format)
            frontmatter = {}
            for line in frontmatter_text.split("\n"):
                if ":" in line:
                    key, value = line.split(":", 1)
                    frontmatter[key.strip()] = value.strip()
            
            return frontmatter, body
    
    return {}, content


def _load_template_from_file(file_path: Path, source_info: SourceInfo) -> Optional[PromptTemplate]:
    """
    Load a single prompt template from a markdown file.
    """
    try:
        content = file_path.read_text(encoding="utf-8")
        frontmatter, body = _parse_frontmatter(content)
        
        name = file_path.stem  # Remove .md extension
        
        # Get description from frontmatter or first non-empty line
        description = frontmatter.get("description", "")
        if not description:
            first_line = body.strip().split("\n")[0] if body.strip() else ""
            if first_line:
                # Truncate if too long
                description = first_line[:60]
                if len(first_line) > 60:
                    description += "..."
        
        template = PromptTemplate(
            name=name,
            description=description,
            argumentHint=frontmatter.get("argument-hint"),
            content=body,
            sourceInfo=source_info,
            filePath=str(file_path),
        )
        return template
    except Exception:
        return None


def _load_templates_from_dir(
    dir_path: Path,
    get_source_info: callable
) -> List[PromptTemplate]:
    """
    Scan a directory for .md files (non-recursive) and load them as prompt templates.
    """
    templates = []
    
    if not dir_path.exists() or not dir_path.is_dir():
        return templates
    
    try:
        for entry in dir_path.iterdir():
            if entry.is_file() and entry.suffix == ".md":
                template = _load_template_from_file(entry, get_source_info(entry))
                if template:
                    templates.append(template)
    except Exception:
        pass
    
    return templates


def _normalize_path(input_path: str) -> str:
    """
    Normalize a path that may start with ~ (home directory).
    """
    trimmed = input_path.strip()
    if trimmed == "~":
        return str(Path.home())
    if trimmed.startswith("~/"):
        return str(Path.home() / trimmed[2:])
    if trimmed.startswith("~"):
        return str(Path.home() / trimmed[1:])
    return trimmed


def _resolve_prompt_path(prompt_path: str, cwd: str) -> Path:
    """
    Resolve a prompt path relative to the working directory.
    """
    normalized = _normalize_path(prompt_path)
    path = Path(normalized)
    if path.is_absolute():
        return path
    return Path(cwd) / normalized


def _is_under_path(target: Path, root: Path) -> bool:
    """
    Check if target path is under the root path.
    """
    try:
        normalized_root = root.resolve()
        target_resolved = target.resolve()
        if target_resolved == normalized_root:
            return True
        # Check if target is a subdirectory of root
        return str(target_resolved).startswith(str(normalized_root) + os.sep)
    except Exception:
        return False


def load_prompt_templates(options: LoadPromptTemplatesOptions) -> List[PromptTemplate]:
    """
    Load all prompt templates from:
    1. Global: agentDir/prompts/
    2. Project: cwd/.pi/prompts/
    3. Explicit prompt paths
    
    Args:
        options: Configuration options for loading templates
        
    Returns:
        List of loaded prompt templates
    """
    templates = []
    
    resolved_cwd = Path(options.cwd)
    resolved_agent_dir = Path(options.agentDir) if options.agentDir else None
    prompt_paths = options.promptPaths
    include_defaults = options.includeDefaults
    
    # Define prompt directories
    global_prompts_dir = None
    if resolved_agent_dir:
        global_prompts_dir = resolved_agent_dir / "prompts"
    
    project_prompts_dir = resolved_cwd / ".pi" / "prompts"
    
    # Helper function to create source info for a path
    def get_source_info(file_path: Path) -> SourceInfo:
        if global_prompts_dir and _is_under_path(file_path, global_prompts_dir):
            return SourceInfo(
                source="local",
                scope="user",
                baseDir=str(global_prompts_dir),
                filePath=str(file_path),
            )
        if _is_under_path(file_path, project_prompts_dir):
            return SourceInfo(
                source="local",
                scope="project",
                baseDir=str(project_prompts_dir),
                filePath=str(file_path),
            )
        return SourceInfo(
            source="local",
            baseDir=str(file_path.parent) if file_path.is_file() else str(file_path),
            filePath=str(file_path),
        )
    
    # 1. Load default global templates
    if include_defaults:
        if global_prompts_dir:
            templates.extend(_load_templates_from_dir(global_prompts_dir, get_source_info))
        templates.extend(_load_templates_from_dir(project_prompts_dir, get_source_info))
    
    # 2. Load explicit prompt paths
    for raw_path in prompt_paths:
        resolved_path = _resolve_prompt_path(raw_path, str(resolved_cwd))
        
        if not resolved_path.exists():
            continue
        
        try:
            if resolved_path.is_dir():
                templates.extend(_load_templates_from_dir(resolved_path, get_source_info))
            elif resolved_path.is_file() and resolved_path.suffix == ".md":
                template = _load_template_from_file(resolved_path, get_source_info(resolved_path))
                if template:
                    templates.append(template)
        except Exception:
            # Ignore read failures
            pass
    
    return templates


def expand_prompt_template(text: str, templates: List[PromptTemplate]) -> str:
    """
    Expand a prompt template if it matches a template name.
    Returns the expanded content or the original text if not a template.
    
    Args:
        text: The input text (e.g., "/templateName arg1 arg2")
        templates: List of loaded prompt templates
        
    Returns:
        Expanded template content or original text
    """
    if not text.startswith("/"):
        return text
    
    # Find template name and arguments
    space_index = text.find(" ")
    if space_index == -1:
        template_name = text[1:]
        args_string = ""
    else:
        template_name = text[1:space_index]
        args_string = text[space_index + 1:]
    
    # Find the matching template
    template = next((t for t in templates if t.name == template_name), None)
    
    if template:
        args = parse_command_args(args_string)
        return substitute_args(template.content, args)
    
    return text
