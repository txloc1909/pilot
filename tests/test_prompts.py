"""Tests for prompt templates and system prompt building."""

import tempfile
from pathlib import Path

import pytest

from pilot.prompts import (
    BuildSystemPromptOptions,
    LoadPromptTemplatesOptions,
    PromptTemplate,
    SourceInfo,
    build_system_prompt,
    expand_prompt_template,
    load_prompt_templates,
    parse_command_args,
    substitute_args,
)


class TestParseCommandArgs:
    """Tests for parse_command_args function."""

    def test_parse_simple_args(self):
        """Test parsing simple space-separated arguments."""
        args = parse_command_args("foo bar baz")
        assert args == ["foo", "bar", "baz"]

    def test_parse_quoted_args(self):
        """Test parsing arguments with double quotes."""
        args = parse_command_args('foo "bar baz" qux')
        assert args == ["foo", "bar baz", "qux"]

    def test_parse_single_quoted_args(self):
        """Test parsing arguments with single quotes."""
        args = parse_command_args("foo 'bar baz' qux")
        assert args == ["foo", "bar baz", "qux"]

    def test_parse_mixed_quotes(self):
        """Test parsing arguments with mixed quotes."""
        args = parse_command_args('foo "bar \'baz\' qux" test')
        assert args == ["foo", "bar 'baz' qux", "test"]

    def test_parse_empty_string(self):
        """Test parsing empty string."""
        args = parse_command_args("")
        assert args == []

    def test_parse_whitespace_only(self):
        """Test parsing whitespace-only string."""
        args = parse_command_args("   ")
        assert args == []

    def test_parse_tabs(self):
        """Test parsing with tabs."""
        args = parse_command_args("foo\tbar\tbaz")
        assert args == ["foo", "bar", "baz"]


class TestSubstituteArgs:
    """Tests for substitute_args function."""

    def test_positional_args(self):
        """Test substitution of positional arguments ($1, $2, etc.)."""
        content = "Hello $1, your name is $2"
        result = substitute_args(content, ["Alice", "Bob"])
        assert result == "Hello Alice, your name is Bob"

    def test_all_args_dollar_sign(self):
        """Test substitution of $@ (all args)."""
        content = "Arguments: $@"
        result = substitute_args(content, ["foo", "bar", "baz"])
        assert result == "Arguments: foo bar baz"

    def test_all_args_keyword(self):
        """Test substitution of $ARGUMENTS."""
        content = "Arguments: $ARGUMENTS"
        result = substitute_args(content, ["foo", "bar", "baz"])
        assert result == "Arguments: foo bar baz"

    def test_sliced_args(self):
        """Test substitution of ${@:N} (slice from Nth)."""
        content = "From second: ${@:2}"
        result = substitute_args(content, ["first", "second", "third"])
        assert result == "From second: second third"

    def test_sliced_args_with_length(self):
        """Test substitution of ${@:N:L} (L args starting from Nth)."""
        content = "Two from second: ${@:2:2}"
        result = substitute_args(content, ["first", "second", "third", "fourth"])
        assert result == "Two from second: second third"

    def test_missing_positional_arg(self):
        """Test substitution with missing positional argument."""
        content = "Hello $1, your name is $3"
        result = substitute_args(content, ["Alice"])
        assert result == "Hello Alice, your name is "

    def test_no_recursion(self):
        """Test that argument values containing $ patterns are not re-substituted."""
        content = "Value: $1"
        result = substitute_args(content, ["$2 test"])
        assert result == "Value: $2 test"


class TestLoadPromptTemplates:
    """Tests for load_prompt_templates function."""

    def test_load_from_directory(self):
        """Test loading templates from a directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a template file
            template_path = Path(tmpdir) / "test-template.md"
            template_path.write_text("""---
description: A test template
argument-hint: <name>
---

Hello $1! This is a test template.
""")
            
            options = LoadPromptTemplatesOptions(
                cwd=tmpdir,
                agentDir=None,
                promptPaths=[tmpdir],
                includeDefaults=False,
            )
            
            templates = load_prompt_templates(options)
            
            assert len(templates) == 1
            assert templates[0].name == "test-template"
            assert templates[0].description == "A test template"
            assert templates[0].argumentHint == "<name>"
            assert "Hello $1" in templates[0].content

    def test_load_with_description_from_body(self):
        """Test loading template where description comes from first line."""
        with tempfile.TemporaryDirectory() as tmpdir:
            template_path = Path(tmpdir) / "no-frontmatter.md"
            template_path.write_text("This is the description line\n\nMore content here...")
            
            options = LoadPromptTemplatesOptions(
                cwd=tmpdir,
                agentDir=None,
                promptPaths=[tmpdir],
                includeDefaults=False,
            )
            
            templates = load_prompt_templates(options)
            
            assert len(templates) == 1
            assert templates[0].description == "This is the description line"

    def test_load_nonexistent_directory(self):
        """Test loading from non-existent directory returns empty list."""
        options = LoadPromptTemplatesOptions(
            cwd="/nonexistent",
            agentDir=None,
            promptPaths=["/nonexistent"],
            includeDefaults=False,
        )
        
        templates = load_prompt_templates(options)
        assert templates == []

    def test_load_specific_file(self):
        """Test loading a specific file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            template_path = Path(tmpdir) / "specific.md"
            template_path.write_text("---\ndescription: Specific template\n---\nContent here")
            
            options = LoadPromptTemplatesOptions(
                cwd=tmpdir,
                agentDir=None,
                promptPaths=[str(template_path)],
                includeDefaults=False,
            )
            
            templates = load_prompt_templates(options)
            
            assert len(templates) == 1
            assert templates[0].name == "specific"


class TestExpandPromptTemplate:
    """Tests for expand_prompt_template function."""

    def test_expand_template_with_args(self):
        """Test expanding a template with arguments."""
        template = PromptTemplate(
            name="hello",
            description="Greet someone",
            content="Hello $1, welcome to $2!",
            sourceInfo=SourceInfo(source="local", filePath="/test/hello.md"),
            filePath="/test/hello.md",
        )
        
        result = expand_prompt_template("/hello Alice Wonderland", [template])
        assert result == "Hello Alice, welcome to Wonderland!"

    def test_expand_template_no_args(self):
        """Test expanding a template without arguments."""
        template = PromptTemplate(
            name="greeting",
            description="Simple greeting",
            content="Hello, world!",
            sourceInfo=SourceInfo(source="local", filePath="/test/greeting.md"),
            filePath="/test/greeting.md",
        )
        
        result = expand_prompt_template("/greeting", [template])
        assert result == "Hello, world!"

    def test_non_template_text(self):
        """Test that non-template text is returned unchanged."""
        result = expand_prompt_template("This is not a template", [])
        assert result == "This is not a template"

    def test_template_not_found(self):
        """Test that unmatched template name is returned unchanged."""
        result = expand_prompt_template("/nonexistent arg", [])
        assert result == "/nonexistent arg"

    def test_expand_with_quoted_args(self):
        """Test expanding template with quoted arguments."""
        template = PromptTemplate(
            name="echo",
            description="Echo arguments",
            content="You said: $@",
            sourceInfo=SourceInfo(source="local", filePath="/test/echo.md"),
            filePath="/test/echo.md",
        )
        
        result = expand_prompt_template('/echo "hello world" test', [template])
        assert result == "You said: hello world test"


class TestBuildSystemPrompt:
    """Tests for build_system_prompt function."""

    def test_basic_prompt(self):
        """Test building a basic system prompt."""
        options = BuildSystemPromptOptions(
            cwd="/test/project",
        )
        
        prompt = build_system_prompt(options)
        
        assert "You are an expert coding assistant" in prompt
        assert "Available tools:" in prompt
        assert "Guidelines:" in prompt
        assert "Current date:" in prompt
        assert "Current working directory: /test/project" in prompt

    def test_custom_prompt(self):
        """Test building with custom prompt."""
        options = BuildSystemPromptOptions(
            customPrompt="You are a specialized assistant.",
            cwd="/test/project",
        )
        
        prompt = build_system_prompt(options)
        
        assert "You are a specialized assistant" in prompt

    def test_with_selected_tools(self):
        """Test building prompt with specific tools."""
        options = BuildSystemPromptOptions(
            selectedTools=["read", "bash"],
            toolSnippets={
                "read": "Read file contents",
                "bash": "Execute shell commands",
            },
            cwd="/test/project",
        )
        
        prompt = build_system_prompt(options)
        
        assert "read:" in prompt
        assert "bash:" in prompt

    def test_with_prompt_guidelines(self):
        """Test building prompt with additional guidelines."""
        options = BuildSystemPromptOptions(
            promptGuidelines=["Always test your code", "Document your changes"],
            cwd="/test/project",
        )
        
        prompt = build_system_prompt(options)
        
        assert "Always test your code" in prompt
        assert "Document your changes" in prompt

    def test_with_append_system_prompt(self):
        """Test building prompt with appended content."""
        options = BuildSystemPromptOptions(
            appendSystemPrompt="Additional instructions go here.",
            cwd="/test/project",
        )
        
        prompt = build_system_prompt(options)
        
        assert "Additional instructions go here." in prompt

    def test_with_context_files(self):
        """Test building prompt with context files."""
        options = BuildSystemPromptOptions(
            cwd="/test/project",
            contextFiles=[
                {"path": "README.md", "content": "Project readme content"},
            ],
        )
        
        prompt = build_system_prompt(options)
        
        assert "# Project Context" in prompt
        assert "README.md" in prompt
        assert "Project readme content" in prompt

    def test_tool_guideline_logic(self):
        """Test that tool guidelines are generated correctly."""
        # With only bash, should suggest using bash for file operations
        options = BuildSystemPromptOptions(
            selectedTools=["bash"],
            cwd="/test/project",
        )
        prompt = build_system_prompt(options)
        assert "Use bash for file operations" in prompt
        
        # With grep, should suggest preferring grep over bash
        options = BuildSystemPromptOptions(
            selectedTools=["bash", "grep"],
            cwd="/test/project",
        )
        prompt = build_system_prompt(options)
        assert "Prefer grep/find/ls tools over bash" in prompt


class TestIntegration:
    """Integration tests combining multiple functions."""

    def test_full_template_workflow(self):
        """Test the full workflow: load templates, expand, build prompt."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a template
            template_path = Path(tmpdir) / "greet.md"
            template_path.write_text("""---
description: Greet a user
argument-hint: <name>
---

Hello $1! Welcome to the project.
""")
            
            # Load templates
            options = LoadPromptTemplatesOptions(
                cwd=tmpdir,
                agentDir=None,
                promptPaths=[tmpdir],
                includeDefaults=False,
            )
            templates = load_prompt_templates(options)
            
            # Expand template
            expanded = expand_prompt_template("/greet Alice", templates)
            assert "Hello Alice!" in expanded
            
            # Build system prompt
            prompt_options = BuildSystemPromptOptions(
                cwd=tmpdir,
                customPrompt="Custom prompt",
            )
            system_prompt = build_system_prompt(prompt_options)
            assert "Custom prompt" in system_prompt
