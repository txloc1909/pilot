"""Model registry — manages built-in and custom models.

Maps to pi's ``model-registry.ts``.

Loads built-in models and custom models from ``~/.pi/agent/models.json``,
provides API key resolution via AuthStorage.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from pilot.auth.storage import AuthStorage
from pilot.config import get_agent_dir, get_models_path
from pilot_provider.types import Model, ModelCost


class ModelRegistry:
    """Model registry - loads and manages models, resolves API keys via AuthStorage."""

    def __init__(self, auth_storage: AuthStorage, models_json_path: str = "") -> None:
        self._auth_storage = auth_storage
        self._models_path = Path(models_json_path or get_models_path())
        self._models: List[Model] = []
        self._load_error: Optional[str] = None
        self._refresh()

    # ---- Factory constructors ----

    @classmethod
    def create(cls, auth_storage: AuthStorage, models_json_path: str = "") -> ModelRegistry:
        return cls(auth_storage, models_json_path)

    @classmethod
    def in_memory(cls, auth_storage: AuthStorage) -> ModelRegistry:
        return cls(auth_storage, "")

    # ---- Refresh ----

    def _refresh(self) -> None:
        """Reload models from disk (built-in + custom from models.json)."""
        self._models = []
        self._load_error = None

        # Load built-in models
        built_in = self._load_built_in_models()
        self._models.extend(built_in)

        # Load custom models
        try:
            custom = self._load_custom_models()
            if custom:
                # Merge: custom models override built-in ones with the same provider+id
                by_key = {}
                for m in self._models:
                    key = f"{m.provider}/{m.id}"
                    by_key[key] = m

                for m in custom:
                    key = f"{m.provider}/{m.id}"
                    by_key[key] = m  # custom wins

                self._models = list(by_key.values())
        except Exception as e:
            self._load_error = f"Failed to load custom models: {e}"

    def _load_built_in_models(self) -> List[Model]:
        """Load built-in models. For now returns a set of common models."""
        # This is a minimal set; pi ships with ~100+ models
        return _BUILT_IN_MODELS.copy()

    def _load_custom_models(self) -> Optional[List[Model]]:
        """Load custom models from models.json."""
        path = self._models_path
        if not path.exists():
            return None

        content = path.read_text()
        data = json.loads(content)

        if not isinstance(data, dict):
            return None

        models: List[Model] = []

        # Parse providers section
        providers = data.get("providers", {})
        if not isinstance(providers, dict):
            return models

        for provider_name, provider_config in providers.items():
            if not isinstance(provider_config, dict):
                continue

            base_url = provider_config.get("baseUrl")
            api_key = provider_config.get("apiKey")
            api = provider_config.get("api", "openai-completions")
            headers = provider_config.get("headers", {})

            if api_key:
                self._auth_storage.set_runtime_api_key(provider_name, api_key)

            # Parse models
            model_defs = provider_config.get("models", [])
            if isinstance(model_defs, list):
                for mdef in model_defs:
                    if not isinstance(mdef, dict) or "id" not in mdef:
                        continue

                    model_url = mdef.get("baseUrl", base_url or "")
                    model_headers = mdef.get("headers", {})

                    cost_data = mdef.get("cost", {})
                    cost = ModelCost(
                        input=cost_data.get("input", 0.0),
                        output=cost_data.get("output", 0.0),
                        cache_read=cost_data.get("cacheRead", 0.0),
                        cache_write=cost_data.get("cacheWrite", 0.0),
                    )

                    thinking_level_map = mdef.get("thinkingLevelMap")
                    input_types = mdef.get("input", ["text"])

                    model = Model(
                        id=mdef["id"],
                        name=mdef.get("name", mdef["id"]),
                        api=api,
                        provider=provider_name,
                        base_url=model_url,
                        reasoning=bool(mdef.get("reasoning", False)),
                        thinking_level_map=thinking_level_map,
                        input_types=input_types,
                        cost=cost,
                        context_window=int(mdef.get("contextWindow", 0)),
                        max_tokens=int(mdef.get("maxTokens", 0)),
                        headers=model_headers if model_headers else None,
                    )
                    models.append(model)

        # Parse modelOverrides section
        model_overrides = data.get("modelOverrides", {})
        if isinstance(model_overrides, dict):
            for model_id, overrides in model_overrides.items():
                if not isinstance(overrides, dict):
                    continue
                for m in self._models:
                    if m.id == model_id:
                        # Apply overrides
                        if "name" in overrides:
                            m.name = overrides["name"]
                        if "reasoning" in overrides:
                            m.reasoning = overrides["reasoning"]
                        if "contextWindow" in overrides:
                            m.context_window = overrides["contextWindow"]
                        if "maxTokens" in overrides:
                            m.max_tokens = overrides["maxTokens"]
                        if "cost" in overrides:
                            cost_data = overrides["cost"]
                            m.cost = ModelCost(
                                input=cost_data.get("input", m.cost.input),
                                output=cost_data.get("output", m.cost.output),
                                cache_read=cost_data.get("cacheRead", m.cost.cache_read),
                                cache_write=cost_data.get("cacheWrite", m.cost.cache_write),
                            )
                        break

        return models

    # ---- Public API ----

    def refresh(self) -> None:
        self._refresh()

    def get_error(self) -> Optional[str]:
        return self._load_error

    def get_all(self) -> List[Model]:
        """Get all models (built-in + custom)."""
        return list(self._models)

    def get_available(self) -> List[Model]:
        """Get only models that have auth configured."""
        return [m for m in self._models if self._auth_storage.has_auth(m.provider)]

    def find(self, provider: str, model_id: str) -> Optional[Model]:
        """Find a model by provider and ID."""
        for m in self._models:
            if m.provider == provider and m.id == model_id:
                return m
        return None

    def has_configured_auth(self, model: Model) -> bool:
        """Check if a model has configured authentication."""
        return self._auth_storage.has_auth(model.provider)

    async def get_api_key_and_headers(
        self, model: Model
    ) -> Dict[str, Any]:
        """Get API key and request headers for a model."""
        api_key = await self._auth_storage.get_api_key(model.provider)
        headers = dict(model.headers or {})
        return {"api_key": api_key, "headers": headers if headers else None}

    def get_provider_auth_status(self, provider: str) -> Any:
        """Return auth status for a provider."""
        return self._auth_storage.get_auth_status(provider)

    def get_api_key_for_provider(self, provider: str) -> Optional[str]:
        """Get API key for a provider (sync)."""
        # Try runtime override first
        if hasattr(self._auth_storage, "_runtime_overrides"):
            key = self._auth_storage._runtime_overrides.get(provider)
            if key:
                return key
        # Try auth.json
        cred = self._auth_storage.get(provider)
        if cred and isinstance(cred, dict) and cred.get("type") == "api_key":
            return cred["key"]
        # Try env var
        from pilot.auth.storage import _get_env_api_key
        return _get_env_api_key(provider)


# ---------------------------------------------------------------------------
# Built-in models
# ---------------------------------------------------------------------------

# Minimal built-in model list (pi ships with many more)
_BUILT_IN_MODELS: List[Model] = [
    Model(
        id="openai/gpt-4o",
        name="GPT-4o",
        api="openai-completions",
        provider="openai",
        base_url="https://api.openai.com/v1",
        reasoning=False,
        input_types=["text", "image"],
        cost=ModelCost(input=2.50, output=10.00),
        context_window=128000,
        max_tokens=16384,
    ),
    Model(
        id="openai/gpt-4o-mini",
        name="GPT-4o Mini",
        api="openai-completions",
        provider="openai",
        base_url="https://api.openai.com/v1",
        reasoning=False,
        input_types=["text", "image"],
        cost=ModelCost(input=0.15, output=0.60),
        context_window=128000,
        max_tokens=16384,
    ),
    Model(
        id="anthropic/claude-3.5-sonnet",
        name="Claude 3.5 Sonnet",
        api="anthropic-messages",
        provider="anthropic",
        base_url="https://api.anthropic.com/v1",
        reasoning=False,
        input_types=["text", "image"],
        cost=ModelCost(input=3.00, output=15.00),
        context_window=200000,
        max_tokens=8192,
    ),
    Model(
        id="google/gemini-2.0-flash-001",
        name="Gemini 2.0 Flash",
        api="google-gemini",
        provider="google",
        base_url="",
        reasoning=False,
        input_types=["text", "image"],
        cost=ModelCost(input=0.10, output=0.40),
        context_window=1048576,
        max_tokens=8192,
    ),
    Model(
        id="openai/o3-mini",
        name="o3 Mini",
        api="openai-completions",
        provider="openai",
        base_url="https://api.openai.com/v1",
        reasoning=True,
        input_types=["text"],
        cost=ModelCost(input=1.10, output=4.40),
        context_window=200000,
        max_tokens=100000,
    ),
]