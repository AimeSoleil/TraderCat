import os
from typing import Dict, Type, Tuple, List, Union
from tradercat.ai.providers.llm_provider import LLMProvider
from tradercat.logger.logger import get_logger

# Optional: Output formatting
try:
    from tabulate import tabulate
except ImportError:
    tabulate = None

logger = get_logger(__name__)

class LLMFactory:
    """
    Factory to register and hold LLM Provider Singleton Instances.
    """
    # Registry now holds Instances, not Classes
    _registry: Dict[str, LLMProvider] = {}
    _providers_loaded = False

    @classmethod
    def register(cls, prefix: str):
        def wrapper(provider_cls):
            try:
                # Instantiate immediately upon registration (Import Time)
                # Pass the global AI token if available
                token = os.environ.get("TRADERCAT_AI_TOKEN")
                
                # Initialize the provider with the token
                instance = provider_cls(api_key=token)
                
                cls._registry[prefix] = instance
            except Exception as e:
                logger.error(f"Failed to auto-init provider '{prefix}': {e}")
            return provider_cls
        return wrapper

    @classmethod
    def fit_provider_model(cls, model_spec: str) -> Tuple[str, str]:
        """
        Parses "provider_model" string.
        """
        raw_model_name = "default"
        if "_" in model_spec:
            provider_key, raw_model_name = model_spec.split("_", 1)
        else:
            provider_key = model_spec
        return provider_key, raw_model_name

    @classmethod
    def _ensure_providers_loaded(cls):
        """Lazy load provider modules to invoke the @register decorators"""
        if not cls._providers_loaded:
            # Import modules here to trigger @register decorators
            import tradercat.ai.providers.mock_provider
            import tradercat.ai.providers.azure_provider
            import tradercat.ai.providers.copilot_provider
            cls._providers_loaded = True

    @classmethod
    def create_provider(cls, model_spec: str) -> Tuple[LLMProvider, str]:
        """
        Retrieves the pre-initialized Provider instance and validates the model.
        """
        cls._ensure_providers_loaded()

        provider_key, raw_model_name = cls.fit_provider_model(model_spec)

        if provider_key not in cls._registry:
            raise ValueError(f"Unknown AI Provider '{provider_key}'. Available: {list(cls._registry.keys())}")

        # Retrieve the existing singleton instance
        instance = cls._registry[provider_key]
        
        # Validate Model
        supported_models = instance.list_supported_models()
        if raw_model_name == "default":
            final_model = supported_models[0] if supported_models else "unknown"
            logger.info(f"Defaulting to model: {final_model}")
        else:
            if raw_model_name not in supported_models:
                valid_str = ", ".join(supported_models)
                # Ensure strict checking or soft warning depending on provider nature
                if "default" not in supported_models: 
                    logger.warning(f"Model '{raw_model_name}' might not be supported by {provider_key}. Valid: {valid_str}")
            final_model = raw_model_name
        
        return instance, final_model

    @classmethod
    def list_all_supported_models(cls):
        """
        Introspects all registered provider instances to print available models.
        """
        cls._ensure_providers_loaded()
        
        headers = ["Provider", "Description", "Model Id", "Usage Example"]
        table_data = []

        for provider_key, instance in cls._registry.items():
            description = instance.get_provider_description()
            models = instance.list_supported_models()
            models_str = ", ".join(models)
            usage_example = f"--model <provider_key>_<model_id>, e.g. --model {provider_key}_{models[0] if models else 'default'}"

            table_data.append([provider_key, description, models_str, usage_example])

        print("\n🤖 Supported AI Models Registry:")
        print("- Model Id may vary by provider. Ensure correct usage.")
        print("- TRADERCAT_AI_MODELS env var can append additional models.")
        
        if tabulate:
            print(tabulate(table_data, headers=headers, tablefmt="github"))
        else:
            print(f"{'Provider':<15} | {'Description':<30} | {'Model Id':<20} | {'Usage Example':<20}")
            print("-" * 75)
            for row in table_data:
                print(f"{row[0]:<15} | {row[1]:<30} | {row[2]:<20} | {row[3]:<20}")

        print("\n📝 Note: Set 'TRADERCAT_AI_TOKEN' env var for authentication.")

