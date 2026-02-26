"""Summarizer Role — Consolidates all analyses into final options portfolio report.

Takes the Global Regime Report + all Per-Symbol Options Analysis Reports and produces
a unified options portfolio plan with $2,000 capital, Greeks budget, risk management, and ROI estimation.
"""
import json
from typing import Dict, Any, Optional

from tradercat.ai.roles.base import AIRole, RoleType, RoleOutput
from tradercat.ai.roles.identity import IdentityRole
from tradercat.ai.providers.llm_interface import LLMProvider
from tradercat.ai.prompts.summary.portfolio_summary import (
    SYSTEM_PROMPT as SUMMARY_SYSTEM,
    USER_PROMPT_TEMPLATE as SUMMARY_USER,
)
from tradercat.logger.logger import get_logger

import logging
from tradercat.config import settings

# Set up logger
use_json = settings.log_format == "json"
logger = get_logger(__name__, level=getattr(logging, settings.log_level), use_json=use_json)


class SummarizerRole(AIRole):
    """
    Summarizer Role — produces the final portfolio report.
    
    Combines the Identity persona with summary instructions to consolidate
    global analysis + symbol analyses into an actionable portfolio plan.
    """
    
    def __init__(
        self,
        llm: LLMProvider,
        identity: IdentityRole,
        model_id: str = "claude-opus-4.6",
        api_key: Optional[str] = None,
    ):
        self.llm = llm
        self.identity = identity
        self.model_id = model_id
        self.api_key = api_key
    
    @property
    def role_type(self) -> RoleType:
        return RoleType.SUMMARY
    
    def _compose_system_prompt(self) -> str:
        """Compose Identity prompt + Summary instructions."""
        identity_prompt = self.identity.get_system_prompt()
        return f"""{identity_prompt}

---

{SUMMARY_SYSTEM}"""
    
    async def summarize(
        self,
        run_date: str,
        global_report: str,
        symbol_reports: Dict[str, str],
    ) -> RoleOutput:
        """
        Final Phase: Portfolio summary and execution plan.
        
        Args:
            run_date: The analysis date
            global_report: Global regime report markdown from AnalystRole
            symbol_reports: Dict mapping symbol → analysis markdown from AnalystRole
        
        Returns:
            RoleOutput containing the complete portfolio report
        """
        system_prompt = self._compose_system_prompt()
        
        # Concatenate all symbol reports
        symbol_reports_text = ""
        for symbol, report in symbol_reports.items():
            symbol_reports_text += f"\n### {symbol}\n{report}\n\n---\n"
        
        user_prompt = SUMMARY_USER.format(
            run_date=run_date,
            global_report=global_report,
            symbol_reports=symbol_reports_text,
        )
        
        logger.info(f"Summarizer: Generating portfolio summary for {run_date} "
                     f"({len(symbol_reports)} symbols, identity={self.identity.identity_key})")
        
        content = await self.llm.generate_thought(
            prompt=user_prompt,
            model_id=self.model_id,
            system_prompt=system_prompt,
            api_key=self.api_key,
        )
        
        return RoleOutput(
            role=RoleType.SUMMARY,
            identity=self.identity.identity_key,
            content=content,
            model_used=self.model_id,
            metadata={
                "run_date": run_date,
                "symbols_analyzed": list(symbol_reports.keys()),
                "has_global_context": bool(global_report),
            },
        )
    
    async def execute(self, **kwargs) -> RoleOutput:
        """Generic execute — delegates to summarize()."""
        return await self.summarize(
            run_date=kwargs["run_date"],
            global_report=kwargs["global_report"],
            symbol_reports=kwargs["symbol_reports"],
        )
