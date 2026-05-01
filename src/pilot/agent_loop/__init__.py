"""Agent loop core.

Provides the async generator `agent_loop` that drives the conversation, dispatches
tool calls, and yields `AgentEvent` objects. Currently a stub implementation.
"""

from typing import AsyncGenerator, List, Dict, Any
from pydantic import BaseModel


class AgentEvent(BaseModel):
    type: str
    data: Dict[str, Any]


async def agent_loop(messages: List[Dict[str, Any]], context: Dict[str, Any]) -> AsyncGenerator[AgentEvent, None]:
    """Placeholder agent loop – yields a single dummy event.
    """
    yield AgentEvent(type="info", data={"msg": "agent loop stub"})
