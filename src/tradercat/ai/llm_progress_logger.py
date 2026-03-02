"""Real-time LLM call progress logging and monitoring."""
import asyncio
import sys
import time
from contextlib import asynccontextmanager
from typing import Optional, Dict, Any
from dataclasses import dataclass, field
from datetime import datetime

from tradercat.logger import get_logger

logger = get_logger(__name__)
llm_logger = get_logger("tradercat.ai.llm_calls")


def estimate_tokens(text: str) -> int:
    """Estimate token count from text length.

    Uses the widely accepted ~4 characters per token heuristic.
    This is a rough approximation; actual counts depend on the
    tokenizer / model.  Good enough for logging & cost tracking
    when the provider does not return real usage stats.
    """
    if not text:
        return 0
    return max(1, len(text) // 4)


@dataclass
class LLMCallContext:
    """Context information for an LLM call."""
    role_name: str
    model_id: str
    system_prompt_length: int
    user_prompt_length: int
    start_time: float
    identity: Optional[str] = None
    phase: Optional[str] = None
    extra_metadata: Optional[Dict[str, Any]] = None


@dataclass
class StreamingAccumulator:
    """Accumulates streaming chunks and logs them in real time.

    Usage inside a provider::

        acc = StreamingAccumulator(role_name="MacroAnalyst", model_id="claude-opus-4.6")
        # called from SDK event callback
        acc.on_delta(delta_text)
        ...
        final_content = acc.content  # full assembled text
    """
    role_name: str = ""
    model_id: str = ""
    identity: Optional[str] = None
    phase: Optional[str] = None
    enabled: bool = True
    # internal
    _chunks: list = field(default_factory=list)
    _char_count: int = 0
    _chunk_count: int = 0
    _start_time: float = field(default_factory=time.time)
    _last_log_time: float = 0.0
    _log_interval: float = 2.0  # log a progress line every N seconds

    # ---- public API ------------------------------------------------

    def on_delta(self, delta: str) -> None:
        """Called for each streaming chunk (message_delta / reasoning_delta)."""
        if not delta:
            return
        self._chunks.append(delta)
        self._char_count += len(delta)
        self._chunk_count += 1

        if not self.enabled:
            return

        # Always print the chunk to stderr for real-time visibility
        sys.stderr.write(delta)
        sys.stderr.flush()

        # Periodic structured log line (avoid flooding)
        now = time.time()
        if now - self._last_log_time >= self._log_interval:
            elapsed = now - self._start_time
            llm_logger.info(
                "[LLM-STREAM] %s ← %s | %d chunks, %d chars so far (%.1fs)",
                self.role_name, self.model_id, self._chunk_count, self._char_count, elapsed,
            )
            self._last_log_time = now

    def on_reasoning_delta(self, delta: str) -> None:
        """Called for reasoning/chain-of-thought chunks."""
        if not delta:
            return
        if not self.enabled:
            return
        # Print reasoning to stderr with a prefix distinction
        sys.stderr.write(delta)
        sys.stderr.flush()

    @property
    def content(self) -> str:
        """Return the full accumulated content."""
        return "".join(self._chunks)

    @property
    def char_count(self) -> int:
        return self._char_count

    @property
    def chunk_count(self) -> int:
        return self._chunk_count

    def log_final(self) -> None:
        """Log a summary line when streaming is complete."""
        if not self.enabled:
            return
        elapsed = time.time() - self._start_time
        # Print a newline after the streamed content
        sys.stderr.write("\n")
        sys.stderr.flush()
        llm_logger.info(
            "[LLM-STREAM-DONE] %s ← %s | %d chunks, %d chars total in %.2fs",
            self.role_name, self.model_id, self._chunk_count, self._char_count, elapsed,
        )


@asynccontextmanager
async def llm_call_progress(
    role_name: str,
    model_id: str,
    system_prompt_length: int,
    user_prompt_length: int,
    identity: Optional[str] = None,
    phase: Optional[str] = None,
    extra_metadata: Optional[Dict[str, Any]] = None,
    progress_interval: float = 1.0,
    enabled: bool = True,
):
    """
    Async context manager for tracking real-time LLM call progress.
    
    Logs start event, periodic progress updates, and completion with timing/metadata.
    
    Args:
        role_name: Name of the role making the call (e.g., "MacroAnalyst")
        model_id: Model identifier (e.g., "claude-opus-4.6")
        system_prompt_length: Length of system prompt in characters
        user_prompt_length: Length of user prompt in characters
        identity: Optional identity key (e.g., "macro_analyst")
        phase: Optional pipeline phase (e.g., "P2", "P3a", "P3b", "P4")
        extra_metadata: Optional dict with additional context
        progress_interval: Seconds between progress update logs
        enabled: Whether to enable progress logging (can be disabled globally)
    
    Yields:
        Dict containing context that can be updated with output_length on completion
    """
    if not enabled:
        # If disabled, yield a dummy dict and skip all logging
        try:
            yield {"output_length": 0, "input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "token_source": "none"}
        except Exception:
            raise
        return
    
    start_time = time.time()
    context = LLMCallContext(
        role_name=role_name,
        model_id=model_id,
        system_prompt_length=system_prompt_length,
        user_prompt_length=user_prompt_length,
        start_time=start_time,
        identity=identity,
        phase=phase,
        extra_metadata=extra_metadata or {},
    )
    
    # Log start event
    log_data = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "event": "llm_call_start",
        "role": context.role_name,
        "model": context.model_id,
        "system_prompt_length": context.system_prompt_length,
        "user_prompt_length": context.user_prompt_length,
        "identity": context.identity,
        "phase": context.phase,
        **context.extra_metadata,
    }
    
    llm_logger.info(f"[LLM-START] {context.role_name} → {context.model_id} (identity={context.identity}, phase={context.phase})")
    llm_logger.debug(f"LLM call details: {log_data}")
    
    # Progress task to log updates every interval
    progress_task = None
    result_dict: Dict[str, Any] = {
        "output_length": 0,
        "status": "running",
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "token_source": "none",  # "api" = provider-reported, "estimated" = heuristic
    }
    
    async def log_progress():
        """Background task to log progress updates."""
        try:
            while result_dict["status"] == "running":
                await asyncio.sleep(progress_interval)
                elapsed = time.time() - start_time
                llm_logger.debug(
                    f"[LLM-PROGRESS] {context.role_name} still processing... "
                    f"(elapsed: {elapsed:.1f}s, model: {context.model_id})"
                )
        except asyncio.CancelledError:
            pass
    
    try:
        # Start progress task
        progress_task = asyncio.create_task(log_progress())
        
        # Yield the result dict to be populated by caller
        yield result_dict
        
        # Mark as complete and cancel progress task
        result_dict["status"] = "completed"
        if progress_task:
            progress_task.cancel()
            try:
                await progress_task
            except asyncio.CancelledError:
                pass
        
        # Log completion
        elapsed = time.time() - start_time
        output_length = result_dict.get("output_length", 0)
        input_tokens = result_dict.get("input_tokens", 0)
        output_tokens = result_dict.get("output_tokens", 0)
        total_tokens = result_dict.get("total_tokens", 0)
        token_source = result_dict.get("token_source", "none")
        
        completion_log = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "event": "llm_call_complete",
            "role": context.role_name,
            "model": context.model_id,
            "elapsed_seconds": elapsed,
            "system_prompt_length": context.system_prompt_length,
            "user_prompt_length": context.user_prompt_length,
            "output_length": output_length,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": total_tokens,
            "token_source": token_source,
            "identity": context.identity,
            "phase": context.phase,
            "status": "success",
            **context.extra_metadata,
        }
        
        llm_logger.info(
            f"[LLM-COMPLETE] {context.role_name} finished in {elapsed:.2f}s "
            f"(output: {output_length} chars, model: {context.model_id}, "
            f"tokens: {input_tokens}→{output_tokens} [{token_source}])"
        )
        llm_logger.debug(f"LLM completion details: {completion_log}")
        
    except Exception as e:
        # Log error
        result_dict["status"] = "failed"
        if progress_task:
            progress_task.cancel()
            try:
                await progress_task
            except asyncio.CancelledError:
                pass
        
        elapsed = time.time() - start_time
        error_log = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "event": "llm_call_error",
            "role": context.role_name,
            "model": context.model_id,
            "elapsed_seconds": elapsed,
            "error_type": type(e).__name__,
            "error_message": str(e),
            "identity": context.identity,
            "phase": context.phase,
            "status": "failed",
            **context.extra_metadata,
        }
        
        llm_logger.error(
            f"[LLM-ERROR] {context.role_name} failed after {elapsed:.2f}s: {str(e)}"
        )
        llm_logger.debug(f"LLM error details: {error_log}")
        
        # Re-raise the exception
        raise
