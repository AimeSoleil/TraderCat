"""LiteLLM unified provider - supports OpenAI, Anthropic, Google Gemini, Azure, and 100+ LLMs."""
import os
import asyncio
from typing import Any, List, Dict, Optional
from tradercat.ai.providers.llm_interface import LLMProvider
from tradercat.ai.llm_provider_factory import LLMFactory
from tradercat.logger import get_logger

try:
    import litellm
    litellm.drop_params = True  # Silently drop unsupported params per-provider
except ImportError:
    litellm = None

logger = get_logger(__name__)

@LLMFactory.register("litellm")
class LiteLLMProvider(LLMProvider):
    """
    Unified LLM provider using LiteLLM.
    
    Supports all major providers through a single interface:
      - OpenAI:           model="gpt-4o", "gpt-4o-mini", "o1", etc.
      - Anthropic:        model="claude-sonnet-4-20250514", "claude-3.5-haiku", etc.
      - Google:           model="gemini/gemini-2.0-flash", "gemini/gemini-pro", etc.
      - Azure:            model="azure/<deployment_name>"
      - GitHub Models:    model="github/gpt-4o", "github/Phi-4", etc.
      - GitHub Copilot:   model="github_copilot/gpt-4", "github_copilot/claude-sonnet-4-20250514", etc.
      - And 100+ more: https://docs.litellm.ai/docs/providers
    
    API keys are read from environment variables per provider convention:
      - OPENAI_API_KEY, ANTHROPIC_API_KEY, GEMINI_API_KEY, AZURE_API_KEY
      - GITHUB_API_KEY (for GitHub Models marketplace)
      - GitHub Copilot uses OAuth device flow (auto-prompted on first use)
    """
    
    # Default models available across major providers
    KNOWN_MODELS = [
        # OpenAI
        "gpt-4o",
        "gpt-4o-mini",
        "o1",
        "o1-mini",
        # Anthropic
        "claude-sonnet-4-20250514",
        "claude-3-5-haiku-latest",
        # Google Gemini
        "gemini/gemini-2.0-flash",
        "gemini/gemini-pro",
        # GitHub Models (https://github.com/marketplace/models)
        "github/gpt-4o",
        "github/Phi-4",
        # GitHub Copilot (OAuth device flow, no key needed)
        "github_copilot/gpt-4",
        "github_copilot/claude-sonnet-4-20250514",
    ]
    
    def __init__(self):
        super().__init__()
        
        if not litellm:
            logger.warning("litellm package not installed. Run: pip install litellm")
            self._available = False
            return
        
        self._available = True
        
        # Configure litellm
        litellm.set_verbose = False
        
        # Load extra models from env
        extra = os.environ.get("TRADERCAT_LITELLM_MODELS", "")
        if extra:
            for m in extra.split(","):
                m = m.strip()
                if m and m not in self.KNOWN_MODELS:
                    self.KNOWN_MODELS.append(m)
        
        logger.info(f"LiteLLM provider initialized with {len(self.KNOWN_MODELS)} known models")
    
    def get_provider_name(self) -> str:
        return "litellm"
    
    def list_supported_models(self) -> List[str]:
        return list(self.KNOWN_MODELS)
    
    async def generate_thought(
        self,
        prompt: str,
        model_id: str,
        system_prompt: str = None,
        temperature: float = 0.7,
        max_tokens: int = 8192,
        api_key: Optional[str] = None,
    ) -> str:
        """Single-shot generation using LiteLLM's unified API."""
        if not self._available:
            return "Error: litellm not installed"
        
        messages = []
        if system_prompt:
            msg: Dict[str, Any] = {"role": "system", "content": system_prompt}
            # Anthropic prompt caching — 90% discount on cached input tokens.
            # Eligible when model is Claude and system_prompt > 1024 tokens (~4K chars).
            if self._is_anthropic_model(model_id) and len(system_prompt) > 4000:
                msg["cache_control"] = {"type": "ephemeral"}
            messages.append(msg)
        messages.append({"role": "user", "content": prompt})
        
        kwargs = dict(
            model=model_id,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        if api_key:
            kwargs["api_key"] = api_key

        try:
            response = await litellm.acompletion(**kwargs)
            content = response.choices[0].message.content
            return content or ""
        except Exception as e:
            logger.error(f"LiteLLM generation error (model={model_id}): {e}")
            raise
    
    async def chat(
        self,
        messages: List[Dict[str, str]],
        model_id: str,
        temperature: float = 0.7,
        max_tokens: int = 8192,
        api_key: Optional[str] = None,
    ) -> str:
        """Multi-turn chat using LiteLLM's unified API."""
        if not self._available:
            return "Error: litellm not installed"

        # Apply Anthropic prompt caching to system messages
        processed = []
        for msg in messages:
            if (
                msg.get("role") == "system"
                and self._is_anthropic_model(model_id)
                and len(msg.get("content", "")) > 4000
            ):
                processed.append({**msg, "cache_control": {"type": "ephemeral"}})
            else:
                processed.append(msg)

        kwargs = dict(
            model=model_id,
            messages=processed,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        if api_key:
            kwargs["api_key"] = api_key

        try:
            response = await litellm.acompletion(**kwargs)
            return response.choices[0].message.content
        except Exception as e:
            logger.error(f"LiteLLM chat error (model={model_id}): {e}")
            raise

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _is_anthropic_model(model_id: str) -> bool:
        """Check if model_id targets an Anthropic Claude model."""
        m = model_id.lower()
        return m.startswith("claude") or "anthropic" in m
