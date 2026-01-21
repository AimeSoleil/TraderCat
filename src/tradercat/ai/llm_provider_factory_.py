import os
from typing import Dict, Type, Tuple, List
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
    Factory to register and instantiate LLM Providers dynamically.
    """
    _registry: Dict[str, Type[LLMProvider]] = {}
    _providers_loaded = False

    @classmethod
    def register(cls, prefix: str):
        def wrapper(provider_cls):
            cls._registry[prefix] = provider_cls
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
        """Lazy load providers to avoid circular import issues at toplevel"""
        if not cls._providers_loaded:
            # Import modules here to trigger @register decorators
            import tradercat.ai.providers.mock_provider
            import tradercat.ai.providers.github_models
            import tradercat.ai.providers.copilot_sdk
            cls._providers_loaded = True

    @classmethod
    def create_provider(cls, model_spec: str) -> Tuple[LLMProvider, str]:
        """
        Validates model spec and returns (ProviderInstance, ModelName).
        """
        cls._ensure_providers_loaded()

        provider_key, raw_model_name = cls.fit_provider_model(model_spec)

        if provider_key not in cls._registry:
            raise ValueError(f"Unknown AI Provider '{provider_key}'. Available: {list(cls._registry.keys())}")

        provider_cls = cls._registry[provider_key]
        
        # Verify Model Support (Strict)
        supported_models = provider_cls().list_supported_models()
        if raw_model_name == "default":
            final_model = supported_models[0] if supported_models else "unknown"
            logger.info(f"Defaulting to model: {final_model}")
        else:
            if raw_model_name not in supported_models:
                valid_str = ", ".join(supported_models)
                # Soft warning instead of crash? No, strict is better for now.
                # Just logger warning might be safer if user appends custom models.
                if "default" not in supported_models: # If provider uses strict lists
                    logger.warning(f"Model '{raw_model_name}' might not be supported. Valid: {valid_str}")
            final_model = raw_model_name

        # Instantiate Provider (Auth Only)
        api_key = os.environ.get("TRADERCAT_AI_TOKEN")
        instance = provider_cls(api_key=api_key)
        
        return instance, final_model

    @classmethod
    def list_all_supported_models(cls):
        """
        Introspects all registered providers to print available models using a table.
        """
        cls._ensure_providers_loaded()
        
        headers = ["Provider", "Model ID", "CLI Command Param"]
        table_data = []

        for provider_key, cls_ref in cls._registry.items():
            models = cls_ref.list_supported_models()
            for model in models:
                # Format: provider_modelName
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

        print("\n📝 Note: Set 'TRADERCAT_AI_TOKEN' env var for authentication.")

