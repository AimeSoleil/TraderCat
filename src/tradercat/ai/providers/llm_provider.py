from abc import ABC, abstractmethod
from typing import List, Dict, Tuple

class LLMProvider(ABC):
    """
    Abstract Base Class for AI Models.
    Stateless regarding the specific model in use; defines the connection to the provider.
    """
    
    @abstractmethod
    def __init__(self, api_key: str = None):
        """Initialize the client connection (Auth only)."""
        pass
    
    @abstractmethod
    def get_provider_name(self) -> str:
        """Returns the unique ID for this provider (e.g., 'copilot')."""
        pass

    @abstractmethod
    def get_provider_description(self) -> str:
        """Returns a human-readable description of the provider."""
        pass

    @abstractmethod
    def list_supported_models(self) -> List[str]:
        """Returns a list of valid model identifiers for this provider."""
        pass

    @abstractmethod
    async def generate_thought(self, prompt: str, model_id: str, system_prompt: str = None) -> Tuple[str, str]:
        """Single-shot generation.
        :param prompt: The user prompt string
        :param model_id: The specific model to use
        :param system_prompt: Optional system prompt to guide the model
        :return: Tuple of session id and the generated response string
        """
        pass

    @abstractmethod
    async def chat(self, messages: List[Dict[str, str]], model_id: str, session_id: str | None = None) -> Tuple[str, str]:
        """
        Conducts a chat conversation based on the provided message history.
        :param messages: List of dicts e.g. [{"role": "user", "content": "..."}]
        :param model_id: The specific model to use
        :param session_id: Optional session ID to maintain context in case the provider supports resuming from it
        :return: Tuple of chat session id and the generated response string
        """
        pass