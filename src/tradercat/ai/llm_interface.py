from abc import ABC, abstractmethod
from typing import List, Dict

class LLMProvider(ABC):
    """
    Abstract Base Class for AI Models.
    Stateless regarding the specific model in use; defines the connection to the provider.
    """
    
    @abstractmethod
    def __init__(self, api_key: str = None):
        """Initialize the client connection (Auth only)."""
        pass
    
    @staticmethod
    @abstractmethod
    def get_provider_name() -> str:
        """Returns the unique ID for this provider (e.g., 'copilot')."""
        pass

    @staticmethod
    @abstractmethod
    def list_supported_models() -> List[str]:
        """Returns a list of valid model identifiers for this provider."""
        pass

    @abstractmethod
    async def generate_thought(self, prompt: str, model_id: str, system_prompt: str = None) -> str:
        """Single-shot generation."""
        pass

    @abstractmethod
    async def chat(self, messages: List[Dict[str, str]], model_id: str) -> str:
        """
        Conducts a chat conversation based on the provided message history.
        :param messages: List of dicts e.g. [{"role": "user", "content": "..."}]
        :param model_id: The specific model to use
        :return: The generated response string
        """
        pass