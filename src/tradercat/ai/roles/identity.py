"""Identity Role — Loads identity/persona prompts for system context.

The Identity role does not call the LLM itself. It provides the system prompt
(persona definition) that is combined with Analysis or Summary prompts.
"""
from typing import Dict, Optional

from tradercat.ai.roles.base import AIRole, RoleType, RoleOutput
from tradercat.logger import get_logger

logger = get_logger(__name__)

# Lazy-load identity prompts
_IDENTITY_CACHE: Dict[str, str] = {}

def _load_identity(identity_key: str) -> str:
    """Load and cache an identity prompt by key."""
    if identity_key in _IDENTITY_CACHE:
        return _IDENTITY_CACHE[identity_key]
    
    # Map identity keys to prompt modules
    identity_map = {
        "options_strategist": "tradercat.ai.prompts.identities.options_strategist",
        "summarizer": "tradercat.ai.prompts.identities.summarizer",
    }
    
    key_lower = identity_key.lower()
    if key_lower not in identity_map:
        raise ValueError(
            f"Unknown identity: '{identity_key}'. "
            f"Available: {list(identity_map.keys())}"
        )
    
    import importlib
    module = importlib.import_module(identity_map[key_lower])
    prompt = getattr(module, "IDENTITY")
    _IDENTITY_CACHE[key_lower] = prompt
    return prompt

def list_identities() -> list[str]:
    """Return all available identity keys."""
    return ["options_strategist", "summarizer"]

class IdentityRole(AIRole):
    """
    Identity Role — provides the persona system prompt.
    
    This role does not call the LLM. It loads and returns the identity prompt
    which is then composed with Analysis/Summary prompts before LLM invocation.
    """
    
    def __init__(self, identity_key: str):
        self.identity_key = identity_key.lower()
        self._prompt: Optional[str] = None
    
    @property
    def role_type(self) -> RoleType:
        return RoleType.IDENTITY
    
    def get_system_prompt(self) -> str:
        """Load and return the identity system prompt."""
        if self._prompt is None:
            self._prompt = _load_identity(self.identity_key)
        return self._prompt
    
    async def execute(self, **kwargs) -> RoleOutput:
        """
        Identity role 'execution' just loads the prompt.
        No LLM call — the prompt is returned as content for composition.
        """
        prompt = self.get_system_prompt()
        return RoleOutput(
            role=RoleType.IDENTITY,
            identity=self.identity_key,
            content=prompt,
            model_used="none",
            metadata={"identity_key": self.identity_key},
        )
