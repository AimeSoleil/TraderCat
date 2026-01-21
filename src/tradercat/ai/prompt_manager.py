from typing import List
from tradercat.ai.prompts import buffett, buffett_zh, livermore, livermore_zh, ptj, ptj_zh, wyckoff, wyckoff_zh

class PromptManager:
    """
    Manages AI persona templates via in-memory constants.
    """

    def __init__(self):
        self.PROMPT_REGISTRY = {        
            "wyckoff": wyckoff.PROMPT,
            "wyckoff-zh": wyckoff_zh.PROMPT,
            "livermore": livermore.PROMPT,
            "livermore-zh": livermore_zh.PROMPT,
            "buffett": buffett.PROMPT,
            "buffett-zh": buffett_zh.PROMPT,
            "ptj": ptj.PROMPT,
            "ptj-zh": ptj_zh.PROMPT,        
        }

    def list_analysts(self) -> List[str]:
        """
        Returns a sorted list of unique available analyst keys (aliases).
        """
        return sorted(list(self.PROMPT_REGISTRY.keys()))

    def get_prompt_template(self, alias: str) -> str:
        """
        Retrieves the prompt content directly from memory.
        """
        alias_lower = alias.lower()
        
        if alias_lower not in self.PROMPT_REGISTRY:
            valid_keys = ", ".join(self.list_analysts()[:5]) + "..."
            raise ValueError(f"Unknown analyst alias: '{alias}'. Available: {valid_keys}")

        # Direct memory access - extremely fast & reliable
        return self.PROMPT_REGISTRY[alias_lower]