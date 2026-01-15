import os
import asyncio
from typing import Dict, Type, List, Tuple
from tradercat.ai.llm_interface import LLMProvider
from tradercat.logger.logger import get_logger

# Optional: Output formatting
try:
    from tabulate import tabulate
except ImportError:
    tabulate = None

try:
    from azure.ai.inference import ChatCompletionsClient
    # [IMPORTANT] Import message types
    from azure.ai.inference.models import SystemMessage, UserMessage, AssistantMessage
    from azure.core.credentials import AzureKeyCredential
except ImportError:
    ChatCompletionsClient = None

logger = get_logger(__name__)

class LLMFactory:
    """
    Factory to register and instantiate LLM Providers dynamically.
    """
    _registry: Dict[str, Type[LLMProvider]] = {}

    @classmethod
    def register(cls, prefix: str):
        def wrapper(provider_cls):
            cls._registry[prefix] = provider_cls
            return provider_cls
        return wrapper

    @classmethod
    def create_provider(cls, model_spec: str) -> Tuple[LLMProvider, str]:
        """
        Validates model spec and returns (ProviderInstance, ModelName).
        """
        # 1. Parse string
        raw_model_name = "default"
        if "_" in model_spec:
            provider_key, raw_model_name = model_spec.split("_", 1)
        else:
            provider_key = model_spec

        if provider_key not in cls._registry:
            raise ValueError(f"Unknown AI Provider '{provider_key}'.")

        provider_cls = cls._registry[provider_key]
        
        # 2. Verify Model Support (Strict)
        supported_models = provider_cls.list_supported_models()
        if raw_model_name == "default":
            final_model = supported_models[0] if supported_models else "unknown"
            logger.info(f"Defaulting to model: {final_model}")
        else:
            if raw_model_name not in supported_models:
                valid_str = ", ".join(supported_models)
                raise ValueError(f"Model '{raw_model_name}' not supported by '{provider_key}'. Valid: {valid_str}")
            final_model = raw_model_name

        # 3. Instantiate Provider (Auth Only)
        api_key = os.environ.get("TRADERCAT_AI_TOKEN")
        instance = provider_cls(api_key=api_key)
        
        return instance, final_model

    @classmethod
    def list_all_supported_models(cls):
        """
        Introspects all registered providers to print available models using a table.
        """
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
            # Fallback if tabulate is not installed
            print(f"{'Provider':<15} | {'Model ID':<30} | {'CLI Command Param'}")
            print("-" * 75)
            for row in table_data:
                print(f"{row[0]:<15} | {row[1]:<30} | {row[2]}")

        print("\n📝 Note: Set 'TRADERCAT_AI_TOKEN' env var for authentication.")

# --- IMPLEMENTATIONS ---

@LLMFactory.register("mock")
class MockAIProvider(LLMProvider):
    def __init__(self, api_key: str = None):
        pass

    @staticmethod
    def get_provider_name() -> str: return "mock"
    
    @staticmethod
    def list_supported_models() -> List[str]:
        return ["gpt-mock", "random-forest"]

    async def generate_thought(self, prompt: str, model_id: str, system_prompt: str = None) -> str:
        return f"**MOCK ({model_id})**: Bullish."

    async def chat(self, messages: List[Dict[str, str]], model_id: str) -> str:
        last_user = messages[-1]['content']
        return f"**MOCK ({model_id})**: I see you asked '{last_user}'. Based on previous context, I still say BUY."

@LLMFactory.register("copilot")
class GitHubModelsProvider(LLMProvider):
    def __init__(self, api_key: str = None):
        self.token = api_key or os.environ.get("GITHUB_TOKEN")
        
        if not ChatCompletionsClient or not self.token:
            self.client = None
            logger.warning("GitHub/Azure Client not initialized (Missing Token or SDK).")
        else:
            try:
                self.client = ChatCompletionsClient(
                    endpoint="https://models.inference.ai.azure.com",
                    credential=AzureKeyCredential(self.token),
                )
            except Exception as e:
                logger.error(f"Client Init Error: {e}")
                self.client = None

    @staticmethod
    def get_provider_name() -> str: return "copilot"

    @staticmethod
    def list_supported_models() -> List[str]:
        return ["gpt-4o", "gpt-4o-mini", "o1", "o1-mini", "Phi-3.5-mini-instruct", "Llama-3.2-90B-Vision-Instruct"]

    async def generate_thought(self, prompt: str, model_id: str, system_prompt: str = None) -> str:
        if not self.client:
            return "Error: Client not initialized."

        messages = []
        if system_prompt:
            messages.append(SystemMessage(content=system_prompt))
        messages.append(UserMessage(content=prompt))

        try:
            loop = asyncio.get_event_loop()
            def _blocking_call():
                return self.client.complete(
                    messages=messages,
                    model=model_id,  # Passed dynamically here!
                    max_tokens=4096,
                    temperature=0.7
                )
            response = await loop.run_in_executor(None, _blocking_call)
            return response.choices[0].message.content
        except Exception as e:
            return f"AI Error: {str(e)}"

    async def chat(self, messages: List[Dict[str, str]], model_id: str) -> str:
        """
        Converts generic dict history into Azure SDK objects and calls the API.
        """
        if not self.client:
            return "Error: Client not initialized."

        sdk_messages = []
        
        # [CRITICAL] Map history to SDK specific objects
        for msg in messages:
            role = msg.get("role")
            content = msg.get("content")
            
            if role == "system":
                sdk_messages.append(SystemMessage(content=content))
            elif role == "user":
                sdk_messages.append(UserMessage(content=content))
            elif role == "assistant":
                sdk_messages.append(AssistantMessage(content=content))

        try:
            loop = asyncio.get_event_loop()
            
            def _blocking_call():
                return self.client.complete(
                    messages=sdk_messages,
                    model=model_id,
                    max_tokens=2048, # Allow reasonable length for chat
                    temperature=0.7
                )

            response = await loop.run_in_executor(None, _blocking_call)
            return response.choices[0].message.content
        except Exception as e:
            logger.error(f"Chat Error: {e}")
            return f"❌ Chat Error: {str(e)}"