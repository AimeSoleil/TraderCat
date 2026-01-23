import os
import asyncio
import traceback
from typing import List, Dict, Tuple
from tradercat.ai.providers.llm_provider import LLMProvider
from tradercat.ai.llm_provider_factory import LLMFactory
from tradercat.logger.logger import get_logger

try:
    from azure.ai.inference import ChatCompletionsClient
    from azure.ai.inference.models import SystemMessage, UserMessage, AssistantMessage
    from azure.core.credentials import AzureKeyCredential
except ImportError:
    ChatCompletionsClient = None

logger = get_logger(__name__)

@LLMFactory.register("azure")
class AzureProvider(LLMProvider):
    """
    Azure AI Models Provider.
    Uses Azure AI Inference SDK to connect to Azure-hosted models.
    """
    def __init__(self, api_key: str = None):
        super().__init__(api_key=api_key)

        self.token = api_key or os.environ.get("GITHUB_TOKEN")
        if not self.token:
            logger.warning("GitHub/Azure Token not found in TRADERCAT_AI_TOKEN or GITHUB_TOKEN.")
        
        if not ChatCompletionsClient or not self.token:
            self.client = None
            logger.warning("GitHub/Azure Client not initialized (Missing Token or azure-ai-inference SDK).")
        else:
            try:
                self.client = ChatCompletionsClient(
                    endpoint="https://models.inference.ai.azure.com",
                    credential=AzureKeyCredential(self.token),
                )
            except Exception as e:
                logger.error(f"Client Init Error: {e}")
                self.client = None

    def get_provider_name(self) -> str: return "azure"

    def get_provider_description(self) -> str:
        return "https://pypi.org/project/azure-ai-inference/"

    def list_supported_models(self) -> List[str]:
        default_models = [
            "gpt-4o", 
            "gpt-4o-mini"
        ]
    
        extra = os.environ.get("TRADERCAT_AI_MODELS", "")
        if extra:
            default_models.extend([m.strip() for m in extra.split(",") if m.strip()])

        seen = set()
        return [m for m in default_models if not (m in seen or seen.add(m))]

    async def generate_thought(self, prompt: str, model_id: str, system_prompt: str = None) -> Tuple[str, str]:
        if not self.client:
            return None, "Error: Client not initialized."

        if model_id not in self.list_supported_models():
            return None, f"Error: Model '{model_id}' not supported by {self.get_provider_name()} Provider."

        messages = []
        if system_prompt:
            messages.append(SystemMessage(content=system_prompt))
        messages.append(UserMessage(content=prompt))

        try:
            loop = asyncio.get_event_loop()
            def _blocking_call():
                return self.client.complete(
                    messages=messages,
                    model=model_id,
                    max_tokens=4096,
                    temperature=0.7
                )
            response = await loop.run_in_executor(None, _blocking_call)
            return None, response.choices[0].message.content
        except Exception as e:
            return None, f"AI Error: {traceback.format_exc()}"

    async def chat(self, messages: List[Dict[str, str]], model_id: str, session_id: str | None = None) -> Tuple[str, str]:
        if not self.client:
            return None, "Error: Client not initialized."

        sdk_messages = []
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
                    max_tokens=2048,
                    temperature=0.7
                )
            response = await loop.run_in_executor(None, _blocking_call)
            return None, response.choices[0].message.content
        except Exception as e:
            logger.error(f"Chat Error: {e}")
            return None, f"❌ Chat Error: {str(e)}"