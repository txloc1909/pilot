"""Read-Only Tools Example

Demonstrates using read-only tools (read, grep, find, ls) without write access.
"""

import asyncio
from pathlib import Path

from pilot import create_agent_session
from pilot.tools import read_only_tools

# Derive project root from this file's location
PROJECT_ROOT = str(Path(__file__).resolve().parent.parent.parent)


async def main() -> None:
    """Read-only tools example."""
    # Create session with read-only tools
    session = await create_agent_session(
        model="xiaomi/mimo-v2.5-pro",
        tools=read_only_tools(PROJECT_ROOT),
        in_memory=True,
        cwd=PROJECT_ROOT,
    )

    try:
        # Print available tools
        print("Available tools:")
        for tool in session.tools:
            print(f"  - {tool.name}")
        print()

        # Track last text length and tool calls
        last_text_len = [0]

        def on_event(event):
            if event.type == "tool_execution_start":
                print(f"  [Calling: {event.tool_name}]")
            elif event.type == "message_update":
                msg = event.message
                if hasattr(msg, "content") and msg.content:
                    for block in msg.content:
                        if hasattr(block, "text"):
                            current_len = len(block.text)
                            if current_len > last_text_len[0]:
                                new_text = block.text[last_text_len[0]:]
                                print(new_text, end="", flush=True)
                                last_text_len[0] = current_len

        unsubscribe = session.subscribe(on_event)

        # Send a prompt that uses read-only tools
        await session.prompt("List the first 5 files in the tests/ directory using the ls tool.")

        print(f"\n\nTotal messages: {len(session.state.messages)}")
        unsubscribe()
    finally:
        session.dispose()


if __name__ == "__main__":
    asyncio.run(main())
