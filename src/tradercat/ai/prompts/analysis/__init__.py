"""Analysis prompt registry."""
from typing import Dict

ANALYSIS_REGISTRY: Dict[str, str] = {
    "global_analysis": "tradercat.ai.prompts.analysis.global_analysis",
    "symbol_analysis": "tradercat.ai.prompts.analysis.symbol_analysis",
}
