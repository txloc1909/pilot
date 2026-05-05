"""System prompt construction and project context loading."""

import os
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, List

from .types import BuildSystemPromptOptions


def _format_skills_for_prompt(skills: List[Any]) -> str:
    """
    Format skills for inclusion in the system prompt.
    
    This is a simplified version. The full implementation would format
    skill names, descriptions, and triggers for the LLM.
    """
    if not skills:
        return ""
    
    result = "\n\n# Available Skills\n\n"
    for skill in skills:
        # Assuming skill has name and description attributes
        if hasattr(skill, "name") and hasattr(skill, "description"):
            result += f"## {skill.name}\n\n{skill.description}\n\n"
    
    return result


def _get_git_info(cwd: str) -> tuple[str | None, str | None]:
    """
    Get git branch and repo root if cwd is inside a git repo.
    
    Returns:
        Tuple of (branch_name, repo_root) or (None, None) if not in git repo
    """
    try:
        # Check if we're in a git repo
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return None, None
        
        repo_root = result.stdout.strip()
        
        # Get the current branch
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            branch = result.stdout.strip()
            return branch, repo_root
        
        return None, repo_root
    except Exception:
        return None, None


def _read_instructions_file(cwd: str) -> str | None:
    """
    Read custom instructions from .pi/instructions.md if present.
    
    Returns:
        Content of instructions.md or None if not found
    """
    instructions_path = Path(cwd) / ".pi" / "instructions.md"
    if instructions_path.exists():
        try:
            return instructions_path.read_text(encoding="utf-8")
        except Exception:
            return None
    return None


def build_system_prompt(options: BuildSystemPromptOptions) -> str:
    """
    Build the system prompt with tools, guidelines, and context.
    
    Args:
        options: Configuration options for building the prompt
        
    Returns:
        The complete system prompt string
    """
    custom_prompt = options.customPrompt
    selected_tools = options.selectedTools
    tool_snippets = options.toolSnippets
    prompt_guidelines = options.promptGuidelines
    append_system_prompt = options.appendSystemPrompt
    cwd = options.cwd
    context_files = options.contextFiles or []
    skills = options.skills or []
    
    resolved_cwd = cwd
    prompt_cwd = resolved_cwd.replace("\\", "/")
    
    now = datetime.now()
    date = now.strftime("%Y-%m-%d")
    
    # Append custom section if provided
    append_section = f"\n\n{append_system_prompt}" if append_system_prompt else ""
    
    # Read custom instructions from .pi/instructions.md
    custom_instructions = _read_instructions_file(resolved_cwd)
    
    if custom_prompt:
        prompt = custom_prompt
        if append_section:
            prompt += append_section
        
        # Append project context files
        if context_files:
            prompt += "\n\n# Project Context\n\n"
            prompt += "Project-specific instructions and guidelines:\n\n"
            for ctx_file in context_files:
                path = ctx_file.get("path", "")
                content = ctx_file.get("content", "")
                prompt += f"## {path}\n\n{content}\n\n"
        
        # Append custom instructions if present
        if custom_instructions:
            prompt += f"\n\n# Custom Instructions\n\n{custom_instructions}\n"
        
        # Append skills section (only if read tool is available)
        custom_prompt_has_read = not selected_tools or "read" in selected_tools
        if custom_prompt_has_read and skills:
            prompt += _format_skills_for_prompt(skills)
        
        # Add date and working directory last
        prompt += f"\nCurrent date: {date}"
        prompt += f"\nCurrent working directory: {prompt_cwd}"
        return prompt
    
    # Get absolute paths to documentation and examples (these would come from config)
    readme_path = "docs/README.md"
    docs_path = "docs/"
    examples_path = "examples/"
    
    # Build tools list based on selected tools
    tools = selected_tools or ["read", "bash", "edit", "write"]
    visible_tools = [name for name in tools if tool_snippets and name in tool_snippets]
    
    if visible_tools:
        tools_list = "\n".join(f"- {name}: {tool_snippets[name]}" for name in visible_tools)
    else:
        tools_list = "(none)"
    
    # Build guidelines based on which tools are actually available
    guidelines_list = []
    guidelines_set = set()
    
    def add_guideline(guideline: str):
        if guideline not in guidelines_set:
            guidelines_set.add(guideline)
            guidelines_list.append(guideline)
    
    has_bash = "bash" in tools
    has_grep = "grep" in tools
    has_find = "find" in tools
    has_ls = "ls" in tools
    has_read = "read" in tools
    
    # File exploration guidelines
    if has_bash and not has_grep and not has_find and not has_ls:
        add_guideline("Use bash for file operations like ls, rg, find")
    elif has_bash and (has_grep or has_find or has_ls):
        add_guideline("Prefer grep/find/ls tools over bash for file exploration (faster, respects .gitignore)")
    
    # Add user-provided guidelines
    if prompt_guidelines:
        for guideline in prompt_guidelines:
            normalized = guideline.strip()
            if normalized:
                add_guideline(normalized)
    
    # Always include these
    add_guideline("Be concise in your responses")
    add_guideline("Show file paths clearly when working with files")
    
    guidelines = "\n".join(f"- {g}" for g in guidelines_list)
    
    # Start building the prompt
    prompt = f"""You are an expert coding assistant operating inside pi, a coding agent harness. You help users by reading files, executing commands, editing code, and writing new files.

Available tools:
{tools_list}

In addition to the tools above, you may have access to other custom tools depending on the project.

Guidelines:
{guidelines}

Pi documentation (read only when the user asks about pi itself, its SDK, extensions, themes, skills, or TUI):
- Main documentation: {readme_path}
- Additional docs: {docs_path}
- Examples: {examples_path} (extensions, custom tools, SDK)
- When asked about: extensions (docs/extensions.md, examples/extensions/), themes (docs/themes.md), skills (docs/skills.md), prompt templates (docs/prompt-templates.md), TUI components (docs/tui.md), keybindings (docs/keybindings.md), SDK integrations (docs/sdk.md), custom providers (docs/custom-provider.md), adding models (docs/models.md), pi packages (docs/packages.md)
- When working on pi topics, read the docs and examples, and follow .md cross-references before implementing
- Always read pi .md files completely and follow links to related docs (e.g., tui.md for TUI API details)"""
    
    prompt += append_section
    
    # Append project context files
    if context_files:
        prompt += "\n\n# Project Context\n\n"
        prompt += "Project-specific instructions and guidelines:\n\n"
        for ctx_file in context_files:
            path = ctx_file.get("path", "")
            content = ctx_file.get("content", "")
            prompt += f"## {path}\n\n{content}\n\n"
    
    # Append custom instructions if present
    if custom_instructions:
        prompt += f"\n\n# Custom Instructions\n\n{custom_instructions}\n"
    
    # Append skills section (only if read tool is available)
    if has_read and skills:
        prompt += _format_skills_for_prompt(skills)
    
    # Add date and working directory last
    prompt += f"\nCurrent date: {date}"
    prompt += f"\nCurrent working directory: {prompt_cwd}"
    
    # Also add git info if available
    git_branch, git_root = _get_git_info(resolved_cwd)
    if git_branch:
        prompt += f"\nGit branch: {git_branch}"
    
    return prompt
