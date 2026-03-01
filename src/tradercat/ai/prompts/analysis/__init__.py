"""Analysis prompt registry."""
from typing import Dict

ANALYSIS_REGISTRY: Dict[str, str] = {
    "macro_analysis": "tradercat.ai.prompts.analysis.macro_analysis",
    "gate_audit": "tradercat.ai.prompts.analysis.gate_audit",
    "execution_plan": "tradercat.ai.prompts.analysis.execution_plan_prompt",
}
