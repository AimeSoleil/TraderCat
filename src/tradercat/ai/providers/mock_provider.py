from typing import List, Dict, Tuple
from tradercat.ai.providers.llm_provider import LLMProvider
from tradercat.ai.llm_provider_factory import LLMFactory
from tradercat.logger.logger import get_logger

logger = get_logger(__name__)

@LLMFactory.register("mock")
class MockAIProvider(LLMProvider):

    def __init__(self, api_key: str = None):
        super().__init__(api_key=api_key)
        if api_key:
            logger.info("MockAIProvider initialized with API key (not used).")

    def get_provider_name(self) -> str: return "mock"

    def get_provider_description(self):
        return "Mock AI Provider for testing purposes."
    
    def list_supported_models(self) -> List[str]:
        return ["gpt-mock", "random-forest"]

    async def generate_thought(self, prompt: str, model_id: str, system_prompt: str = None) -> Tuple[str, str]:
        if model_id not in self.list_supported_models():
            return None, f"Error: Model '{model_id}' not supported by Azure Provider."
        return None, f"**MOCK ({model_id})**: Bullish sentiment detected based on mock data."

    async def chat(self, messages: List[Dict[str, str]], model_id: str, session_id: str | None = None) -> Tuple[str, str]:
        last_user = messages[-1]['content']
        return None, f"**MOCK ({model_id})**: I see you asked '{last_user}'. Based on previous context, I still say BUY."