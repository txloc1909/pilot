"""Custom Model Example

Demonstrates using a specific model with custom thinking level.
"""

import asyncio
from pathlib import Path

from pilot import AgentSessionConfig, create_agent_session

# Derive project root from this file's location
PROJECT_ROOT = str(Path(__file__).resolve().parent.parent.parent)


async def main() -> None:
    """Custom model example."""
    # Create session with specific model and thinking level
    config = AgentSessionConfig(
        model="xiaomi/mimo-v2.5-pro",
        thinking_level="off",
        in_memory=True,
        cwd=PROJECT_ROOT,
        system_prompt="You are a helpful coding assistant. Be concise.",
    )

    session = await create_agent_session(config=config)

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

        # Print model info
        print(f"Model: {session.model.id if session.model else 'default'}")
        print(f"Thinking level: {session.state.thinking_level}")
        print()

        # Send a prompt
        await session.prompt("What is a Python decorator? Answer in 2 sentences.")

        print(f"\n\n--- Stats ---")
        print(f"Total messages: {len(session.state.messages)}")

        unsubscribe()
    finally:
        session.dispose()


if __name__ == "__main__":
    asyncio.run(main())
