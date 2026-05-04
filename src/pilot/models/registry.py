"""Model registry — minimal model configuration management.

Maps to pi's ``model-registry.ts`` but simplified for pilot's use case.

Provides:
1. Custom model loading from ~/.pi/agent/models.json
2. API key resolution via AuthStorage
3. Provider registration hook for extensions

Note: Built-in model definitions are in pilot_provider.
This registry focuses on runtime configuration and API key management.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from pilot.auth.storage import AuthStorage
from pilot.config import get_agent_dir
from pilot_provider.types import Model, ModelCost


class ModelRegistry:
    """Model registry for runtime model configuration and API key resolution.

    Simplified from pi's ModelRegistry to focus on:
    - Loading custom models from models.json
    - Resolving API keys via AuthStorage
    - Supporting dynamic provider registration
    """

    def __init__(self, auth_storage: AuthStorage, models_json_path: str = "") -> None:
        self._auth_storage = auth_storage
        self._models_path = Path(models_json_path or str(Path(get_agent_dir()) / "models.json"))
        self._custom_models: List[Model] = []
        self._providers: Dict[str, Dict[str, Any]] = {}
        self._load_error: Optional[str] = None
        self._refresh()

    @classmethod
    def create(cls, auth_storage: AuthStorage, models_json_path: str = "") -> ModelRegistry:
        """Create registry loading from models.json."""
        return cls(auth_storage, models_json_path)

    @classmethod
    def in_memory(cls, auth_storage: AuthStorage) -> ModelRegistry:
        """Create in-memory registry (no models.json)."""
        return cls(auth_storage, "")

    def _refresh(self) -> None:
        """Reload custom models from models.json."""
        self._custom_models = []
        self._load_error = None

        if not self._models_path.exists():
            return

        try:
            content = self._models_path.read_text()
            data = json.loads(content)

            if not isinstance(data, dict):
                return

            # Parse custom models
            self._load_custom_models(data)
            self._load_provider_configs(data)
        except Exception as e:
            self._load_error = f"Failed to load models.json: {e}"

    def _load_custom_models(self, data: Dict[str, Any]) -> None:
        """Load custom model definitions from models.json."""
        providers = data.get("providers", {})
        if not isinstance(providers, dict):
            return

        for provider_name, provider_config in providers.items():
            if not isinstance(provider_config, dict):
                continue

            # Set runtime API key if provided
            if "apiKey" in provider_config:
                self._auth_storage.set_runtime_api_key(
                    provider_name, provider_config["apiKey"]
                )

            # Load custom models from this provider
            models = provider_config.get("models", [])
            if isinstance(models, list):
                for model_def in models:
                    if isinstance(model_def, dict) and "id" in model_def:
                        model = self._build_model_from_def(provider_name, model_def)
                        if model:
                            self._custom_models.append(model)

    def _build_model_from_def(self, provider: str, model_def: Dict[str, Any]) -> Optional[Model]:
        """Build a Model from a model definition dict."""
        try:
            # Basic required fields
            model_id = model_def["id"]
            name = model_def.get("name", model_id)

            # Parse cost if provided
            cost_data = model_def.get("cost", {})
            cost = ModelCost(
                input=cost_data.get("input", 0.0),
                output=cost_data.get("output", 0.0),
                cache_read=cost_data.get("cacheRead", 0.0),
                cache_write=cost_data.get("cacheWrite", 0.0),
            )

            # Build Model (minimal fields, provider-specific fields can be added)
            return Model(
                id=model_id,
                name=name,
                api=model_def.get("api", "openai-completions"),
                provider=provider,
                base_url=model_def.get("baseUrl", ""),
                reasoning=model_def.get("reasoning", False),
                input_types=model_def.get("input", ["text"]),
                cost=cost,
                context_window=model_def.get("contextWindow", 0),
                max_tokens=model_def.get("maxTokens", 0),
            )
        except Exception:
            return None

    def _load_provider_configs(self, data: Dict[str, Any]) -> None:
        """Load provider configurations for extension registration."""
        providers = data.get("providers", {})
        if isinstance(providers, dict):
            for name, config in providers.items():
                if isinstance(config, dict):
                    self._providers[name] = config

    def refresh(self) -> None:
        """Reload models from disk."""
        self._refresh()

    def get_error(self) -> Optional[str]:
        """Get any error from loading models.json."""
        return self._load_error

    def get_all(self) -> List[Model]:
        """Get all custom models loaded from models.json."""
        return list(self._custom_models)

    def find(self, provider: str, model_id: str) -> Optional[Model]:
        """Find a custom model by provider and ID."""
        for model in self._custom_models:
            if model.provider == provider and model.id == model_id:
                return model
        return None

    def has_configured_auth(self, model: Model) -> bool:
        """Check if a model has configured authentication."""
        return self._auth_storage.has_auth(model.provider)

    async def get_api_key_and_headers(self, model: Model) -> Dict[str, Any]:
        """Get API key and headers for a model."""
        api_key = await self._auth_storage.get_api_key(model.provider)
        headers = dict(model.headers or {})
        return {"api_key": api_key, "headers": headers if headers else None}

    def get_provider_auth_status(self, provider: str) -> Any:
        """Return auth status for a provider."""
        return self._auth_storage.get_auth_status(provider)

    def get_api_key_for_provider(self, provider: str) -> Optional[str]:
        """Get API key for a provider (sync)."""
        return self._auth_storage.get_api_key(provider)

    def is_using_oauth(self, model: Model) -> bool:
        """Check if a model is using OAuth credentials."""
        cred = self._auth_storage.get(model.provider)
        return cred is not None and cred.get("type") == "oauth"

    def register_provider(self, provider_name: str, config: Dict[str, Any]) -> None:
        """Register a provider dynamically (from extensions).

        Args:
            provider_name: Name of the provider
            config: Provider configuration including baseUrl, apiKey, etc.
        """
        self._providers[provider_name] = config

        # If API key is provided, set as runtime override
        if "apiKey" in config:
            self._auth_storage.set_runtime_api_key(provider_name, config["apiKey"])

    def unregister_provider(self, provider_name: str) -> None:
        """Unregister a previously registered provider.

        Args:
            provider_name: Name of the provider to unregister
        """
        self._providers.pop(provider_name, None)
