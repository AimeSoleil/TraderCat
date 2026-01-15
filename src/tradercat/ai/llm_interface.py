from abc import ABC, abstractmethod

class LLMProvider(ABC):
    """
    Abstract Base Class for AI Models.
    This allows us to switch between OpenAI, Gemini, Claude, or local Ollama easily.
    """
    
    @abstractmethod
    async def generate_thought(self, prompt: str, system_prompt: str = None) -> str:
        """
        Send a prompt to the LLM and get a text response.
        """
        pass
    
    @abstractmethod
    def get_model_name(self) -> str:
        pass