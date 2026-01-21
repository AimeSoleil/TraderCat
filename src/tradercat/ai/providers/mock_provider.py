from typing import List, Dict
from tradercat.ai.providers.llm_interface import LLMProvider
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
    
    def list_supported_models(self) -> List[str]:
        return ["gpt-mock", "random-forest"]

    async def generate_thought(self, prompt: str, model_id: str, system_prompt: str = None) -> str:
        return f"**MOCK ({model_id})**: Bullish sentiment detected based on mock data."

    async def chat(self, messages: List[Dict[str, str]], model_id: str) -> str:
        last_user = messages[-1]['content']
        return f"**MOCK ({model_id})**: I see you asked '{last_user}'. Based on previous context, I still say BUY."