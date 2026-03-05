from abc import ABC, abstractmethod
from typing import List, Dict, Optional, Any


class LLMProvider(ABC):
    """
    Abstract Base Class for AI Models.
    Stateless regarding the specific model in use; defines the connection to the provider.
    """
    
    # Class-level configuration for progress logging
    _progress_logging_enabled: bool = False
    _progress_interval: float = 10.0
    _role_name: Optional[str] = None
    _identity: Optional[str] = None
    _phase: Optional[str] = None
    
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
    
    @classmethod
    def enable_progress_logging(
        cls,
        enabled: bool = True,
        progress_interval: float = 30.0,
        role_name: Optional[str] = None,
        identity: Optional[str] = None,
        phase: Optional[str] = None,
    ) -> None:
        """
        Enable or disable real-time progress logging for LLM calls.
        
        Args:
            enabled: Whether to enable progress logging
            progress_interval: Seconds between progress updates
            role_name: Name of the role making the call (e.g., "MacroAnalyst")
            identity: Identity key (e.g., "macro_analyst")
            phase: Pipeline phase (e.g., "P2", "P3a")
        """
        cls._progress_logging_enabled = enabled
        cls._progress_interval = progress_interval
        cls._role_name = role_name
        cls._identity = identity
        cls._phase = phase

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