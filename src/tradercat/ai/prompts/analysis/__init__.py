"""Analysis prompt registry."""
from typing import Dict

ANALYSIS_REGISTRY: Dict[str, str] = {
    "macro_analysis": "tradercat.ai.prompts.analysis.macro_analysis",
    "symbol_analysis": "tradercat.ai.prompts.analysis.symbol_analysis",
}
