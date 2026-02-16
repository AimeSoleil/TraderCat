from abc import ABC, abstractmethod
from typing import List, Dict, Optional

class LLMProvider(ABC):
    """
    Abstract Base Class for AI Models.
    Stateless regarding the specific model in use; defines the connection to the provider.
    """
    
    @abstractmethod
    def __init__(self):
        """Initialize the client connection."""
        pass
    
    @abstractmethod
    def get_provider_name(self) -> str:
        """Returns the unique ID for this provider (e.g., 'copilot')."""
        pass

    @abstractmethod
    def list_supported_models(self) -> List[str]:
        """Returns a list of valid model identifiers for this provider."""
        pass

    @abstractmethod
    async def generate_thought(
        self,
        prompt: str,
        model_id: str,
        system_prompt: str = None,
        temperature: float = 0.7,
        max_tokens: int = 8192,
        api_key: Optional[str] = None,
    ) -> str:
        """Single-shot generation.

        Args:
            api_key: Optional per-request API key. When provided it overrides
                     the environment-variable-based key for this call.
        """
        pass

    @abstractmethod
    async def chat(
        self,
        messages: List[Dict[str, str]],
        model_id: str,
        temperature: float = 0.7,
        max_tokens: int = 8192,
        api_key: Optional[str] = None,
    ) -> str:
        """
        Conducts a chat conversation based on the provided message history.

        Args:
            messages: List of dicts e.g. [{"role": "user", "content": "..."}]
            model_id: The specific model to use
            api_key: Optional per-request API key.
        """
        pass