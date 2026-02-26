"""Analyst Role — Executes global and per-symbol analysis via LLM.

Combines Identity system prompt + Analysis instructions, then calls LLM
with market data to produce structured analysis reports.
"""
import json
from typing import List, Dict, Any, Optional

from tradercat.ai.roles.base import AIRole, RoleType, RoleOutput
from tradercat.ai.roles.identity import IdentityRole
from tradercat.ai.providers.llm_interface import LLMProvider
from tradercat.ai.prompts.analysis.macro_analysis import (
    SYSTEM_PROMPT as MACRO_ANALYSIS_SYSTEM,
    USER_PROMPT_TEMPLATE as MACRO_ANALYSIS_USER,
)
from tradercat.ai.prompts.analysis.symbol_analysis import (
    SYSTEM_PROMPT as SYMBOL_ANALYSIS_SYSTEM,
    USER_PROMPT_TEMPLATE as SYMBOL_ANALYSIS_USER,
)
from tradercat.logger.logger import get_logger

import logging
from tradercat.config import settings

# Set up logger
use_json = settings.log_format == "json"
logger = get_logger(__name__, level=getattr(logging, settings.log_level), use_json=use_json)


class AnalystRole(AIRole):
    """
    Analyst Role — performs global macro analysis and per-symbol analysis.
    
    Uses the Identity role's system prompt combined with analysis-specific
    instructions to produce structured analysis reports.
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
        return RoleType.ANALYSIS
    
    def _compose_system_prompt(self, analysis_instructions: str) -> str:
        """Compose Identity prompt + Analysis instructions into a single system prompt."""
        identity_prompt = self.identity.get_system_prompt()
        return f"""{identity_prompt}

---

{analysis_instructions}"""
    
    async def analyze_global(
        self,
        run_date: str,
        signals_data: List[Dict[str, Any]],
    ) -> RoleOutput:
        """
        Phase 0: Global macro regime analysis.
        
        Args:
            run_date: The analysis date string
            signals_data: List of ETF/index signal dicts with technical data
        
        Returns:
            RoleOutput containing the global regime report markdown
        """
        system_prompt = self._compose_system_prompt(MACRO_ANALYSIS_SYSTEM)
        
        # Format signals for the prompt
        signals_json = json.dumps(signals_data, indent=2, default=str)
        user_prompt = MACRO_ANALYSIS_USER.format(
            run_date=run_date,
            signals_json=signals_json,
        )
        
        logger.info(f"Analyst: Starting global analysis for {run_date} "
                     f"({len(signals_data)} signals, identity={self.identity.identity_key}, model={self.model_id}, provider={self.llm.get_provider_name()})")
        logger.debug(f"System_prompt: {system_prompt}")
        logger.debug(f"User_prompt: {user_prompt}")
        
        content = await self.llm.generate_thought(
            prompt=user_prompt,
            model_id=self.model_id,
            system_prompt=system_prompt,
            api_key=self.api_key,
        )   
        
        return RoleOutput(
            role=RoleType.ANALYSIS,
            identity=self.identity.identity_key,
            content=content,
            model_used=self.model_id,
            metadata={
                "analysis_type": "global",
                "run_date": run_date,
                "signal_count": len(signals_data),
            },
        )
    
    async def analyze_symbol(
        self,
        symbol_data_json: str,
        global_context: str,
    ) -> RoleOutput:
        """
        Phase 1: Per-symbol technical analysis.
        
        Args:
            symbol_data_json: JSON string of technical indicator data for the symbol(s)
            global_context: The global regime report from Phase 0
        
        Returns:
            RoleOutput containing the symbol analysis report markdown
        """
        system_prompt = self._compose_system_prompt(SYMBOL_ANALYSIS_SYSTEM)
        
        user_prompt = SYMBOL_ANALYSIS_USER.format(
            global_context=global_context,
            symbol_data_json=symbol_data_json,
        )
        
        logger.info(f"Analyst: Starting symbol analysis "
                     f"(identity={self.identity.identity_key}, model={self.model_id}, provider={self.llm.get_provider_name()})")
        logger.debug(f"System_prompt: {system_prompt}")
        logger.debug(f"User_prompt: {user_prompt}")
        
        content = await self.llm.generate_thought(
            prompt=user_prompt,
            model_id=self.model_id,
            system_prompt=system_prompt,
            api_key=self.api_key,
        )
        
        return RoleOutput(
            role=RoleType.ANALYSIS,
            identity=self.identity.identity_key,
            content=content,
            model_used=self.model_id,
            metadata={
                "analysis_type": "symbol",
            },
        )
    
    async def analyze_symbols_batch(
        self,
        symbols_data: Dict[str, str],
        global_context: str,
    ) -> Dict[str, RoleOutput]:
        """
        Analyze multiple symbols. Each symbol gets its own LLM call
        with the global context for proper filtering.
        
        Args:
            symbols_data: Dict mapping symbol → JSON technical data string
            global_context: The global regime report markdown
        
        Returns:
            Dict mapping symbol → RoleOutput
        """
        results: Dict[str, RoleOutput] = {}
        
        for symbol, data_json in symbols_data.items():
            try:
                result = await self.analyze_symbol(
                    symbol_data_json=data_json,
                    global_context=global_context,
                )
                result.metadata["symbol"] = symbol
                results[symbol] = result
                logger.info(f"Analyst: Completed analysis for {symbol}")
            except Exception as e:
                logger.error(f"Analyst: Failed to analyze {symbol}: {e}")
                results[symbol] = RoleOutput(
                    role=RoleType.ANALYSIS,
                    identity=self.identity.identity_key,
                    content=f"Analysis failed for {symbol}: {str(e)}",
                    model_used=self.model_id,
                    metadata={"symbol": symbol, "error": str(e)},
                )
        
        return results
    
    async def execute(self, **kwargs) -> RoleOutput:
        """Generic execute — dispatch to appropriate analysis method."""
        analysis_type = kwargs.get("analysis_type", "symbol")
        
        if analysis_type == "global":
            return await self.analyze_global(
                run_date=kwargs["run_date"],
                signals_data=kwargs["signals_data"],
            )
        elif analysis_type == "symbol":
            return await self.analyze_symbol(
                symbol_data_json=kwargs["symbol_data_json"],
                global_context=kwargs.get("global_context", ""),
            )
        else:
            raise ValueError(f"Unknown analysis_type: {analysis_type}")
