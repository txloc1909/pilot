"""Tests for model registry (minimal version)."""

import json
import tempfile
from pathlib import Path

import pytest

from pilot.auth.storage import AuthStorage
from pilot.models.registry import ModelRegistry


def test_model_registry_in_memory():
    """Test in-memory model registry."""
    auth_storage = AuthStorage.in_memory()
    registry = ModelRegistry.in_memory(auth_storage)

    # Should have no custom models initially
    all_models = registry.get_all()
    assert len(all_models) == 0

    # Find should return None for non-existent model
    model = registry.find("openai", "nonexistent-model")
    assert model is None


def test_model_registry_load_custom_models():
    """Test loading custom models from models.json."""
    with tempfile.TemporaryDirectory() as tmpdir:
        auth_storage = AuthStorage.in_memory()
        models_path = Path(tmpdir) / "models.json"

        # Write a models.json with custom models
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

        # Check custom model was loaded
        all_models = registry.get_all()
        custom_models = [m for m in all_models if m.provider == "custom"]
        assert len(custom_models) == 1
        assert custom_models[0].id == "custom/model-1"
        assert custom_models[0].name == "Custom Model 1"

        # Check API key was set as runtime override
        assert auth_storage.has_auth("custom")


def test_model_registry_find():
    """Test finding models."""
    with tempfile.TemporaryDirectory() as tmpdir:
        auth_storage = AuthStorage.in_memory()
        models_path = Path(tmpdir) / "models.json"

        custom_config = {
            "providers": {
                "custom": {
                    "baseUrl": "http://localhost:8080",
                    "models": [
                        {"id": "custom/model-1", "name": "Model 1"},
                        {"id": "custom/model-2", "name": "Model 2"},
                    ]
                }
            }
        }

        models_path.write_text(json.dumps(custom_config))
        registry = ModelRegistry.create(auth_storage, str(models_path))

        # Find existing model
        model = registry.find("custom", "custom/model-1")
        assert model is not None
        assert model.id == "custom/model-1"

        # Find non-existent model
        model = registry.find("custom", "nonexistent")
        assert model is None


def test_model_registry_auth_status():
    """Test auth status methods."""
    auth_storage = AuthStorage.in_memory()
    registry = ModelRegistry.in_memory(auth_storage)

    # Check auth status for a provider
    status = registry.get_provider_auth_status("openai")
    assert status is not None


def test_model_registry_register_provider():
    """Test dynamic provider registration."""
    auth_storage = AuthStorage.in_memory()
    registry = ModelRegistry.in_memory(auth_storage)

    # Register a new provider
    registry.register_provider(
        "test-provider",
        {"baseUrl": "http://test.com", "apiKey": "test-key"}
    )

    # Check API key was set
    assert auth_storage.has_auth("test-provider")


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


def test_model_registry_has_configured_auth():
    """Test auth check for models."""
    auth_storage = AuthStorage.in_memory()
    registry = ModelRegistry.in_memory(auth_storage)

    # Create a mock model (not from registry, just for testing)
    from pilot_provider.types import Model

    mock_model = Model(
        id="test/model",
        name="Test Model",
        api="openai-completions",
        provider="nonexistent-provider",
        base_url="",
        reasoning=False,
        input_types=["text"],
    )

    # Should return False for unknown provider
    assert not registry.has_configured_auth(mock_model)


@pytest.mark.asyncio
async def test_model_registry_get_api_key_and_headers():
    """Test getting API key and headers for a model."""
    auth_storage = AuthStorage.in_memory()
    registry = ModelRegistry.in_memory(auth_storage)

    from pilot_provider.types import Model

    mock_model = Model(
        id="test/model",
        name="Test Model",
        api="openai-completions",
        provider="openai",
        base_url="",
        reasoning=False,
        input_types=["text"],
    )

    result = await registry.get_api_key_and_headers(mock_model)

    assert "api_key" in result
    assert "headers" in result
