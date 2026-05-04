"""Test for model registry."""

import json
import tempfile
from pathlib import Path

import pytest

from pilot.auth.storage import AuthStorage
from pilot.models.registry import ModelRegistry, _BUILT_IN_MODELS


def test_model_registry_in_memory():
    """Test in-memory model registry."""
    auth_storage = AuthStorage.in_memory()
    registry = ModelRegistry.in_memory(auth_storage)

    # Check built-in models are loaded
    all_models = registry.get_all()
    assert len(all_models) > 0

    # Check available models (models with auth)
    available = registry.get_available()
    # Should be empty since no auth is configured
    assert len(available) == 0

    # Test find - openai/gpt-4o exists in built-in models
    model = registry.find("openai", "openai/gpt-4o")
    assert model is not None  # Found in built-in models
    
    # Test find with non-existent model
    model2 = registry.find("openai", "nonexistent/model")
    assert model2 is None  # Should not find non-existent model

    # Find by provider (partial match)
    for m in all_models:
        if m.provider == "openai":
            found = registry.find("openai", m.id)
            assert found is not None
            break


def test_model_registry_load_built_in():
    """Test loading built-in models."""
    auth_storage = AuthStorage.in_memory()
    registry = ModelRegistry.create(auth_storage)

    # Should have the minimal built-in models
    models = registry.get_all()
    assert len(models) > 0

    # Check model structure
    for model in models:
        assert model.id
        assert model.name
        assert model.provider
        assert model.api


def test_model_registry_has_configured_auth():
    """Test auth check for models."""
    auth_storage = AuthStorage.in_memory()
    registry = ModelRegistry.create(auth_storage)

    # No auth configured
    model = _BUILT_IN_MODELS[0]
    assert not registry.has_configured_auth(model)


def test_model_registry_error_handling():
    """Test error handling for invalid models.json."""
    with tempfile.TemporaryDirectory() as tmpdir:
        auth_storage = AuthStorage.in_memory()
        models_path = Path(tmpdir) / "models.json"
        models_path.write_text("invalid json")

        registry = ModelRegistry.create(auth_storage, str(models_path))
        error = registry.get_error()

        # Should have an error from loading invalid JSON
        assert error is not None


def test_model_registry_with_custom_models():
    """Test loading custom models from models.json."""
    with tempfile.TemporaryDirectory() as tmpdir:
        auth_storage = AuthStorage.in_memory()
        models_path = Path(tmpdir) / "models.json"

        custom_config = {
            "providers": {
                "custom": {
                    "baseUrl": "http://localhost:8080",
                    "apiKey": "test-key",
                    "models": [
                        {
                            "id": "custom/model-1",
                            "name": "Custom Model 1",
                            "reasoning": False,
                            "input": ["text"],
                            "cost": {"input": 0.5, "output": 1.0, "cacheRead": 0, "cacheWrite": 0},
                            "contextWindow": 8192,
                            "maxTokens": 2048,
                        }
                    ]
                }
            }
        }

        models_path.write_text(json.dumps(custom_config))
        registry = ModelRegistry.create(auth_storage, str(models_path))
        registry.refresh()

        # Check custom model was loaded
        all_models = registry.get_all()
        custom_models = [m for m in all_models if m.provider == "custom"]
        assert len(custom_models) > 0

        # Check API key was set (uses runtime override)
        assert auth_storage.has_auth("custom")


@pytest.mark.asyncio
async def test_model_registry_get_api_key_and_headers():
    """Test getting API key and headers for a model."""
    auth_storage = AuthStorage.in_memory()
    registry = ModelRegistry.create(auth_storage)

    model = _BUILT_IN_MODELS[0]
    result = await registry.get_api_key_and_headers(model)

    assert "api_key" in result
    assert "headers" in result
