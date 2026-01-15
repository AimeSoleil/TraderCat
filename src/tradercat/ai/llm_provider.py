import os
import asyncio
from tradercat.ai.llm_interface import LLMProvider
from tradercat.logger.logger import get_logger

# Optional import for Azure AI Inference
try:
    from azure.ai.inference import ChatCompletionsClient
    from azure.ai.inference.models import SystemMessage, UserMessage
    from azure.core.credentials import AzureKeyCredential
except ImportError:
    ChatCompletionsClient = None

logger = get_logger(__name__)

class MockAIProvider(LLMProvider):
    """A dummy provider for testing without API keys."""
    def get_model_name(self) -> str:
        return "Mock-GPT-4"

    async def generate_thought(self, prompt: str, system_prompt: str = None) -> str:
        logger.info(f"Mocking AI call with prompt length: {len(prompt)}")
        return f"**MOCK ANALYSIS**: Based on the technicals provided, the stock looks bullish. (This is a mock response)."

class GitHubModelsProvider(LLMProvider):
    """
    Official implementation for GitHub Models (Azure AI Inference).
    Requires GITHUB_TOKEN environment variable.
    """
    def __init__(self, model_name: str = "gpt-4o"):
        self.model_name = model_name
        self.token = os.environ.get("GITHUB_TOKEN")
        
        if not ChatCompletionsClient:
            logger.error("❌ 'azure-ai-inference' not installed. Run: pip install azure-ai-inference")
            self.client = None
            return

        if not self.token:
            logger.error("❌ GITHUB_TOKEN not found. Required for GitHub Models.")
            self.client = None
            return

        try:
            # Official Endpoint for GitHub Marketplace Models
            self.client = ChatCompletionsClient(
                endpoint="https://models.inference.ai.azure.com",
                credential=AzureKeyCredential(self.token),
            )
        except Exception as e:
            logger.error(f"Failed to init GitHub client: {e}")
            self.client = None

    def get_model_name(self) -> str:
        return f"GitHub-Native ({self.model_name})"

    async def generate_thought(self, prompt: str, system_prompt: str = None) -> str:
        if not self.client:
            return "Error: Client not initialized. Check logs."

        messages = []
        if system_prompt:
            messages.append(SystemMessage(content=system_prompt))
        
        # In this specific SDK, pure strings might work, but UserMessage object is safer
        messages.append(UserMessage(content=prompt))

        try:
            # Note: This SDK might be synchronous by default. 
            # We run it in a thread executor to keep our TraderCat async loop searching.
            loop = asyncio.get_event_loop()
            
            def _blocking_call():
                return self.client.complete(
                    messages=messages,
                    model=self.model_name,
                    max_tokens=4096,
                    temperature=0.7
                )

            response = await loop.run_in_executor(None, _blocking_call)
            return response.choices[0].message.content

        except Exception as e:
            logger.error(f"GitHub Inference Error: {e}")
            return f"AI Error: {str(e)}"

class OpenAIProvider(LLMProvider):
    """Real implementation connecting to OpenAI."""
    def __init__(self, model_name="gpt-4o"):
        self.model_name = model_name
        self.api_key = os.environ.get("OPENAI_API_KEY")
        # from openai import AsyncOpenAI
        # self.client = AsyncOpenAI(api_key=self.api_key)

    def get_model_name(self) -> str:
        return self.model_name

    async def generate_thought(self, prompt: str, system_prompt: str = None) -> str:
        if not self.api_key:
            return "Error: OPENAI_API_KEY not found."
        
        # 实际调用逻辑 (需要安装 openai 包)
        # response = await self.client.chat.completions.create(...)
        # return response.choices[0].message.content
        return "OpenAI integration pending (install openai package to enable)."