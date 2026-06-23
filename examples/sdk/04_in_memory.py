"""In-Memory Session Example

Demonstrates using an in-memory session with no file persistence.
"""

import asyncio
from pathlib import Path

from pilot import create_agent_session

# Derive project root from this file's location
PROJECT_ROOT = str(Path(__file__).resolve().parent.parent.parent)


async def main() -> None:
    """In-memory session example."""
    # Create in-memory session
    session = await create_agent_session(
        model="xiaomi/mimo-v2.5-pro",
        in_memory=True,
        cwd=PROJECT_ROOT,
    )

    try:
        # Verify session properties
        print(f"Session persisted: {session.session_manager.is_persisted()}")
        print(f"Session file: {session.session_manager.get_session_file()}")
        print(f"Initial messages: {len(session.state.messages)}")
        print()

        # Track last text length
        last_text_len = [0]

        def on_event(event):
            if event.type == "agent_start":
                print("[Agent Start]")
            elif event.type == "turn_end":
                print("[Turn End]")
            elif event.type == "agent_end":
                print("[Agent End]")
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

        # Send a prompt
        await session.prompt("Say hello in one sentence.")

        print(f"\n\nTotal messages: {len(session.state.messages)}")
        unsubscribe()
    finally:
        session.dispose()

    print("\nSession disposed (no files to clean up)")


if __name__ == "__main__":
    asyncio.run(main())
