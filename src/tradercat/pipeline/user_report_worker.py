"""User report generation worker for pipeline (Q3) — role-based AI.

Q3 generates personalized reports per user by:
1. Loading the macro summary + portfolio summary from Q2
2. Loading the symbol execution plans for the user's watchlist from Q2
3. Using the SummarizerRole with user's preferred identity to produce a personalized briefing
"""
import asyncio
import json
from datetime import date
from typing import List, Dict, Any, Optional
from uuid import UUID

from tradercat.logger.logger import get_logger
from tradercat.config import settings
from tradercat.ai.providers.llm_interface import LLMProvider
from tradercat.ai.roles.identity import IdentityRole
from tradercat.ai.roles.summarizer import SummarizerRole

logger = get_logger(__name__)


def _json_safe(obj: Any) -> Any:
    """Round-trip through JSON so every value is JSON-serializable (date → str, etc.)."""
    return json.loads(json.dumps(obj, default=str))


def _get_llm_provider(model_id: str = None):
    """Get LLM provider from the factory."""
    from tradercat.ai.llm_provider_factory import LLMFactory
    model_id = model_id or settings.default_llm_model
    provider_key = settings.default_llm_provider
    provider, resolved_model = LLMFactory.create_provider(f"{provider_key}_{model_id}")
    return provider, resolved_model


class UserReportWorker:
    """Worker for generating personalized user reports (Q3) using role-based AI."""
    
    def __init__(self, max_retries: int | None = None, api_key: str | None = None):
        self.max_retries = max_retries if max_retries is not None else settings.pipeline_llm_max_retries
        self.api_key = api_key
    
    async def generate_user_briefing(
        self,
        user_id: UUID,
        run_date: date,
        summary_report_md: str,
        symbol_plans: Dict[str, str],
        persona: str,
        lang: str | None,
        pipeline_run_id: UUID,
        model: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Generate a personalized briefing for a user using SummarizerRole.
        
        Uses the user's preferred identity to re-summarize the global context
        + their specific watchlist symbol plans.
        """
        model = model or settings.default_llm_model
        
        # Resolve identity — strip language suffix if present
        identity_key = persona.split("-")[0] if "-" in persona else persona
        
        # Map legacy persona names to new identity keys
        identity_mapping = {
            "wyckoff": "wyckoff",
            "options_strategist": "options_strategist",
            # Legacy personas fall back to wyckoff identity + their system prompt
            "livermore": "wyckoff",
            "ptj": "options_strategist",
            "simons": "options_strategist",
            "shaw": "options_strategist",
        }
        identity_key = identity_mapping.get(identity_key, "wyckoff")
        
        for attempt in range(self.max_retries + 1):
            try:
                content = await self._call_llm_personalized(
                    run_date=run_date,
                    summary_report_md=summary_report_md,
                    symbol_plans=symbol_plans,
                    persona=persona,
                    identity_key=identity_key,
                    model=model,
                    api_key=self.api_key,
                )
                
                return {
                    "user_id": user_id,
                    "run_date": run_date,
                    "report_type": "personalized_briefing",
                    "content_md": content,
                    "model_used": model,
                    "identity_used": persona,
                    "input_context": _json_safe({
                        "symbols": list(symbol_plans.keys()),
                        "persona": persona,
                        "identity": identity_key,
                        "has_summary": bool(summary_report_md),
                    }),
                    "pipeline_run_id": pipeline_run_id,
                }
                
            except Exception as e:
                if attempt < self.max_retries:
                    logger.warning(f"Q3: Retry {attempt + 1}/{self.max_retries} for user {user_id}: {e}")
                    await asyncio.sleep(2 ** attempt)
                else:
                    logger.error(
                        f"Q3: Failed briefing for user {user_id} "
                        f"after {self.max_retries + 1} attempts: {e}"
                    )
                    return None
        
        return None
    
    async def _call_llm_personalized(
        self,
        run_date: date,
        summary_report_md: str,
        symbol_plans: Dict[str, str],
        persona: str,
        identity_key: str,
        model: str,
        api_key: str | None = None,
    ) -> str:
        """
        Call LLM with identity-based persona to generate personalized briefing.
        Uses SummarizerRole to consolidate user's watchlist reports.
        """
        try:
            provider, resolved_model = _get_llm_provider(model)
            
            identity = IdentityRole(identity_key)
            summarizer = SummarizerRole(provider, identity, resolved_model, api_key=api_key)
            
            result = await summarizer.summarize(
                run_date=run_date,
                global_report=summary_report_md,
                symbol_reports=symbol_plans,
            )
            return result.content
            
        except Exception as e:
            logger.warning(f"Q3: LLM call failed, using placeholder: {e}")
            return self._placeholder_briefing(summary_report_md, symbol_plans, persona, model)
    
    @staticmethod
    def _placeholder_briefing(
        summary_report_md: str,
        symbol_plans: Dict[str, str],
        persona: str,
        model: str,
    ) -> str:
        """Fallback placeholder when LLM is not available."""
        symbols = list(symbol_plans.keys())
        report = f"""# Your Daily Trading Briefing

**Persona**: {persona} | **Model**: {model} | **Symbols**: {len(symbols)}

---

## Market Overview

{summary_report_md[:500] if summary_report_md else '*No macro summary available*'}

---

## Your Watchlist

"""
        for symbol, plan in symbol_plans.items():
            plan_preview = "\n".join(plan.split("\n")[:10])
            report += f"### {symbol}\n\n{plan_preview}\n\n"
        
        report += f"---\n*Generated by TraderCat Pipeline Q3 (persona: {persona})*\n"
        return report


async def generate_user_reports_q3(
    user_tasks: List[Dict[str, Any]],
    max_concurrency: int = 5,
    api_key: str | None = None,
) -> List[Dict[str, Any]]:
    """
    Q3: Generate personalized reports for all users concurrently.
    """
    if not user_tasks:
        return []
    
    queue = asyncio.Queue()
    for task in user_tasks:
        await queue.put(task)
    
    async def worker():
        results = []
        w = UserReportWorker(api_key=api_key)
        while True:
            try:
                task = queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            try:
                record = await w.generate_user_briefing(**task)
                if record:
                    results.append(record)
            finally:
                queue.task_done()
        return results
    
    workers = [
        asyncio.create_task(worker())
        for _ in range(min(max_concurrency, len(user_tasks)))
    ]
    worker_results = await asyncio.gather(*workers)
    
    all_records = []
    for result_list in worker_results:
        all_records.extend(result_list)
    
    logger.info(f"Q3 complete: {len(all_records)} user reports from {len(user_tasks)} tasks")
    return all_records
