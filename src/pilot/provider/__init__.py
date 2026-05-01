"""Provider abstraction layer.

Contains the `stream` async generator that normalises different LLM provider
APIs into a common event stream. Stubs are provided for future implementation.
"""

from typing import AsyncGenerator, List, Dict, Any
from pydantic import BaseModel


class ProviderEvent(BaseModel):
    """Base class for normalized events emitted by providers."""
    type: str
    data: Dict[str, Any]


async def stream(provider: str, model: str, messages: List[Dict[str, Any]], tools: List[Dict[str, Any]]) -> AsyncGenerator[ProviderEvent, None]:
    """Yield normalized events from the selected LLM provider.

    Parameters
    ----------
    provider: str
        Name of the provider (e.g., "openai", "anthropic").
    model: str
        Model identifier.
    messages: List[Dict[str, Any]]
        Conversation history formatted for the provider.
    tools: List[Dict[str, Any]]
        Tool definitions the model can call.
    """
    # TODO: implement provider specific streaming logic.
    # Placeholder yields a single dummy text event.
    yield ProviderEvent(type="text", data={"content": "[stub response]"})
