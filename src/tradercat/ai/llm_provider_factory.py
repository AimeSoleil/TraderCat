from typing import Dict, Type, Tuple, List, Union
from tradercat.ai.providers.llm_interface import LLMProvider
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
                # Instantiate immediately upon registration (import time)
                instance = provider_cls()
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
        """Lazy load provider modules to invoke the @register decorators."""
        if not cls._providers_loaded:
            try:
                import tradercat.ai.providers.litellm_provider
            except ImportError:
                logger.warning("LiteLLM provider not available (litellm not installed)")
            try:
                import tradercat.ai.providers.copilot_provider
            except ImportError:
                logger.warning("Copilot SDK provider not available (copilot-sdk not installed)")
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
        
        headers = ["Provider", "Model ID", "CLI Command Param"]
        table_data = []

        for provider_key, instance in cls._registry.items():
            # Instance is already created, so we call method directly without cls()
            models = instance.list_supported_models()
            for model in models:
                cli_param = f"{provider_key}_{model}"
                table_data.append([provider_key, model, f"--model {cli_param}"])

        print("\n🤖 Supported AI Models Registry:")
        
        if tabulate:
            print(tabulate(table_data, headers=headers, tablefmt="grid"))
        else:
            print(f"{'Provider':<15} | {'Model ID':<30} | {'CLI Command Param'}")
            print("-" * 75)
            for row in table_data:
                print(f"{row[0]:<15} | {row[1]:<30} | {row[2]}")

        print("\n📝 Note: Set provider-specific API keys (OPENAI_API_KEY, ANTHROPIC_API_KEY, etc.) for authentication.")

