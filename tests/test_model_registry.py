"""Tests for model registry with class-based grouping and fixtures."""

import json
from pathlib import Path

import pytest

from pilot.auth.storage import AuthStorage
from pilot.models.registry import ModelRegistry


class TestModelRegistryCreation:
    """Tests for creating model registry instances."""

    def test_in_memory_creation(self, auth_storage):
        """Test creating an in-memory model registry."""
        registry = ModelRegistry.in_memory(auth_storage)

        # Should have no custom models initially
        all_models = registry.get_all()
        assert len(all_models) == 0

        # Should have no error
        assert registry.get_error() is None

    def test_create_with_models_json(self, temp_dir, auth_storage):
        """Test creating registry with a models.json file."""
        models_path = temp_dir / "models.json"
        models_path.write_text(json.dumps({
            "providers": {
                "test": {
                    "baseUrl": "http://test.com",
                    "apiKey": "test-key",
                    "models": [{"id": "test/model-1", "name": "Test Model 1"}]
                }
            }
        }))

        registry = ModelRegistry.create(auth_storage, str(models_path))
        assert len(registry.get_all()) == 1


class TestModelRegistryCustomModels:
    """Tests for custom model loading from models.json."""

    def test_load_custom_models(self, temp_dir, auth_storage):
        """Test loading custom models from models.json."""
        models_path = temp_dir / "models.json"

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
                            "cost": {"input": 0.5, "output": 1.0},
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

    def test_find_model(self, temp_dir, auth_storage):
        """Test finding models by provider and ID."""
        models_path = temp_dir / "models.json"

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


class TestModelRegistryAuth:
    """Tests for auth-related model registry methods."""

    def test_has_configured_auth(self, model_registry):
        """Test auth check for models."""
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
        assert not model_registry.has_configured_auth(mock_model)

    def test_get_provider_auth_status(self, model_registry):
        """Test getting provider auth status."""
        status = model_registry.get_provider_auth_status("openai")
        assert status is not None


class TestModelRegistryProviderRegistration:
    """Tests for dynamic provider registration."""

    def test_register_provider(self, auth_storage):
        """Test registering a new provider."""
        registry = ModelRegistry.in_memory(auth_storage)

        # Register a new provider
        registry.register_provider(
            "test-provider",
            {"baseUrl": "http://test.com", "apiKey": "test-key"}
        )

        # Check API key was set
        assert auth_storage.has_auth("test-provider")

    def test_unregister_provider(self, auth_storage):
        """Test unregistering a provider."""
        registry = ModelRegistry.in_memory(auth_storage)

        # Register then unregister
        registry.register_provider("temp-provider", {"apiKey": "key"})
        assert "temp-provider" in auth_storage._runtime_overrides

        registry.unregister_provider("temp-provider")
        # Provider config should be removed (though runtime override remains)


class TestModelRegistryErrorHandling:
    """Tests for error handling."""

    def test_invalid_models_json(self, temp_dir, auth_storage):
        """Test error handling for invalid models.json."""
        models_path = temp_dir / "models.json"
        models_path.write_text("invalid json")

        registry = ModelRegistry.create(auth_storage, str(models_path))
        error = registry.get_error()

        assert error is not None
        assert "Failed to load" in error

    def test_missing_models_json(self, temp_dir, auth_storage):
        """Test registry creation with missing models.json."""
        models_path = temp_dir / "models.json"

        registry = ModelRegistry.create(auth_storage, str(models_path))
        assert registry.get_error() is None
        assert len(registry.get_all()) == 0


class TestModelRegistryApiKeyResolution:
    """Tests for API key resolution."""

    @pytest.mark.asyncio
    async def test_get_api_key_and_headers(self, auth_storage):
        """Test getting API key and headers for a model."""
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

    @pytest.mark.asyncio
    async def test_get_api_key_for_provider(self, auth_storage):
        """Test getting API key for a provider."""
        registry = ModelRegistry.in_memory(auth_storage)

        # No key configured
        key = await registry.get_api_key_for_provider("openai")
        assert key is None

    def test_is_using_oauth(self, auth_storage):
        """Test checking if model uses OAuth."""
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

        # Should return False (no OAuth configured)
        assert not registry.is_using_oauth(mock_model)
