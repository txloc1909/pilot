"""Minimal SDK Example

Uses all defaults: coding tools, in-memory session.
"""

import asyncio
from pathlib import Path

from pilot import create_agent_session

# Derive project root from this file's location
PROJECT_ROOT = str(Path(__file__).resolve().parent.parent.parent)


async def main() -> None:
    """Minimal SDK usage example."""
    # Create session with defaults
    session = await create_agent_session(
        model="xiaomi/mimo-v2.5-pro",
        in_memory=True,
        cwd=PROJECT_ROOT,
    )

    try:
        # Track last text length to only print new content
        last_text_len = [0]

        def on_event(event):
            if event.type == "message_update":
                msg = event.message
                if hasattr(msg, "content") and msg.content:
                    for block in msg.content:
                        if hasattr(block, "text"):
                            # Only print the new part (delta)
                            current_len = len(block.text)
                            if current_len > last_text_len[0]:
                                new_text = block.text[last_text_len[0]:]
                                print(new_text, end="", flush=True)
                                last_text_len[0] = current_len

        unsubscribe = session.subscribe(on_event)

        # Send a prompt
        await session.prompt("List the Python files in the src/pilot directory. Be concise.")

        # Print final messages
        print("\n\n--- Session Summary ---")
        print(f"Total messages: {len(session.state.messages)}")

        unsubscribe()
    finally:
        session.dispose()


if __name__ == "__main__":
    asyncio.run(main())
