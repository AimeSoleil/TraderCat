"""User briefing worker for pipeline P4 — SummarizerRole.

P4 generates personalized portfolio briefings per user by:
1. Loading compressed regime context from P2 (regime label + score + filters)
2. Loading structured P3 trade cards for the user's watchlist
3. Using SummarizerRole with a FIXED summarizer identity

Token optimization:
  - Regime context is compressed (label + score + Section 4 filters only)
  - Per-symbol plans are pre-formatted as ultra-compact trade cards (~200-300 chars)
    from structured P3 JSON via format_p4_card() in options_strategist
"""
import asyncio
import json
import re
from datetime import date
from typing import List, Dict, Any, Optional
from uuid import UUID

from tradercat.logger import get_logger
from tradercat.config import settings
from tradercat.ai.providers.llm_interface import LLMProvider
from tradercat.ai.roles.identity import IdentityRole
from tradercat.ai.roles.summarizer import SummarizerRole

logger = get_logger(__name__)

# Fixed identity for P4 — always "summarizer"
_P4_IDENTITY = "summarizer"


def _json_safe(obj: Any) -> Any:
    return json.loads(json.dumps(obj, default=str))


def _get_llm_provider(model_id: str = None):
    from tradercat.ai.llm_provider_factory import LLMFactory
    model_id = model_id or settings.default_llm_model
    provider_key = settings.default_llm_provider
    provider, resolved_model = LLMFactory.create_provider(f"{provider_key}_{model_id}")
    return provider, resolved_model


def compress_regime_for_briefing(regime_md: str, regime_label: str | None = None, regime_score: float | None = None) -> str:
    """
    Compress P2 regime markdown for P4 input.
    Returns a short summary: regime label + score + downstream filters.
    """
    parts = []

    if regime_label:
        parts.append(f"**Regime**: {regime_label}")
    if regime_score is not None:
        parts.append(f"**Regime Score**: {regime_score}")

    # Extract Section 4 from markdown
    m = re.search(
        r"(##\s*4\.?\s*Downstream Filters.*?)(?=\n##\s|\Z)",
        regime_md,
        re.DOTALL | re.IGNORECASE,
    )
    if m:
        parts.append(m.group(1).strip())
    elif not parts:
        # Fallback: first 800 chars
        parts.append(regime_md[:800])

    return "\n".join(parts)


class UserBriefingWorker:
    """Worker for generating personalized user briefings (P4)."""

    def __init__(self, max_retries: int | None = None, api_key: str | None = None):
        self.max_retries = max_retries if max_retries is not None else settings.pipeline_llm_max_retries
        self.api_key = api_key

    async def generate(
        self,
        user_id: UUID,
        run_date: date,
        regime_summary: str,
        symbol_plans: Dict[str, str],
        pipeline_run_id: UUID,
        model: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Generate a personalized briefing for a user using SummarizerRole
        with the fixed summarizer identity.
        """
        model = model or settings.default_llm_model

        logger.info(
            f"P4: Generating briefing for user {user_id} "
            f"({len(symbol_plans)} symbols, identity={_P4_IDENTITY}, model={model})"
        )

        for attempt in range(self.max_retries + 1):
            try:
                content = await self._call_llm(
                    run_date=run_date,
                    regime_summary=regime_summary,
                    symbol_plans=symbol_plans,
                    model=model,
                    api_key=self.api_key,
                )

                return {
                    "user_id": user_id,
                    "run_date": run_date,
                    "content_md": content,
                    "model_used": model,
                    "identity_used": _P4_IDENTITY,
                    "input_context": _json_safe({
                        "symbols": list(symbol_plans.keys()),
                        "identity": _P4_IDENTITY,
                        "has_regime": bool(regime_summary),
                    }),
                    "pipeline_run_id": pipeline_run_id,
                }

            except Exception as e:
                if attempt < self.max_retries:
                    logger.warning(f"P4: Retry {attempt + 1}/{self.max_retries} for user {user_id}: {e}")
                    await asyncio.sleep(2 ** attempt)
                else:
                    logger.error(f"P4: Failed for user {user_id} after {self.max_retries + 1} attempts: {e}")
                    return None

        return None

    async def _call_llm(
        self,
        run_date: date,
        regime_summary: str,
        symbol_plans: Dict[str, str],
        model: str,
        api_key: str | None = None,
    ) -> str:
        """Call LLM with fixed summarizer identity."""
        try:
            provider, resolved_model = _get_llm_provider(model)
            identity = IdentityRole(_P4_IDENTITY)
            summarizer = SummarizerRole(provider, identity, resolved_model, api_key=api_key)

            result = await summarizer.summarize(
                run_date=str(run_date),
                global_report=regime_summary,
                symbol_reports=symbol_plans,
            )
            return result.content

        except Exception as e:
            logger.warning(f"P4: LLM call failed, using placeholder: {e}")
            return self._placeholder(regime_summary, symbol_plans)

    @staticmethod
    def _placeholder(regime_summary: str, symbol_plans: Dict[str, str]) -> str:
        symbols = list(symbol_plans.keys())
        report = f"# Your Daily Trading Briefing\n\n"
        report += f"**Symbols**: {len(symbols)} | **Identity**: {_P4_IDENTITY}\n\n---\n\n"
        report += "## Market Overview\n\n"
        report += (regime_summary[:500] if regime_summary else "*No regime context available*")
        report += "\n\n---\n\n## Your Watchlist\n\n"
        for symbol, plan in symbol_plans.items():
            preview = "\n".join(plan.split("\n")[:10])
            report += f"### {symbol}\n\n{preview}\n\n"
        report += f"---\n*Placeholder — LLM not available*\n"
        return report


async def generate_user_briefings_p4(
    user_tasks: List[Dict[str, Any]],
    max_concurrency: int = 5,
    api_key: str | None = None,
) -> List[Dict[str, Any]]:
    """
    P4 entry point: generate personalized briefings for all users concurrently.

    Each task dict should contain:
        user_id, run_date, regime_summary, symbol_plans, pipeline_run_id
    """
    if not user_tasks:
        return []

    queue: asyncio.Queue = asyncio.Queue()
    for task in user_tasks:
        await queue.put(task)

    async def worker():
        results = []
        w = UserBriefingWorker(api_key=api_key)
        while True:
            try:
                task = queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            try:
                record = await w.generate(**task)
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

    logger.info(f"P4 complete: {len(all_records)} user briefings from {len(user_tasks)} tasks")
    return all_records
