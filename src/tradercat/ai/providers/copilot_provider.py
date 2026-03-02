"""GitHub Copilot SDK provider — uses the official copilot-sdk (JSON-RPC) for LLM access.

Authentication (in priority order):
  1. Per-request ``api_key`` parameter  → used as ``github_token``
  2. ``GITHUB_TOKEN`` environment variable
  3. Logged-in GitHub CLI user (``gh auth login``)

Available models depend on your Copilot subscription.  Use ``list_models()``
at runtime to discover the actual set, or rely on the hard-coded fallback list.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import time
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from tradercat.ai.llm_provider_factory import LLMFactory
from tradercat.ai.providers.llm_interface import LLMProvider
from tradercat.ai.llm_progress_logger import llm_call_progress, StreamingAccumulator, estimate_tokens
from tradercat.logger import get_logger

if TYPE_CHECKING:
    from copilot import CopilotClient

try:
    from copilot import CopilotClient as _CopilotClient  # noqa: F811

    _copilot_available = True
except ImportError:
    _CopilotClient = None
    _copilot_available = False

logger = get_logger(__name__)

@LLMFactory.register("copilot")
class CopilotProvider(LLMProvider):
    """
    LLM provider backed by the GitHub Copilot CLI via the ``copilot-sdk``.

    The provider lazily creates **one** :class:`CopilotClient` per authentication
    token.  Each ``generate_thought`` / ``chat`` call creates an ephemeral
    session, sends the prompt, waits for the complete response, and tears the
    session down — so callers can treat it as stateless.

    Supported models (non-exhaustive — depends on subscription):
        gpt-4o, gpt-4o-mini, gpt-4, o1, o3-mini,
        claude-sonnet-4-20250514, claude-3.5-haiku, gemini-2.0-flash …
    """

    # Timeout (seconds) for a single send_and_wait call.
    # opus models processing large batches (P3a gate audit) can take 3-5 min.
    REQUEST_TIMEOUT = 600.0

    # Session cache TTL (seconds) — discard cached sessions older than this.
    SESSION_CACHE_TTL = 600.0  # 10 minutes

    # Max cached sessions to prevent unbounded growth.
    SESSION_CACHE_MAX = 10

    # Fallback catalogue when the CLI is not reachable at import time.
    KNOWN_MODELS = [
        "claude-haiku-4.5",
        "claude-opus-4.5",
        "claude-opus-4.6",
        "claude-opus-4.6-fast",
        "claude-sonnet-4",
        "claude-sonnet-4.5",
        "gemini-3-pro-preview",
        "gpt-4.1",
        "gpt-5",
        "gpt-5-mini",
        "gpt-5.1",
        "gpt-5.1-codex",
        "gpt-5.1-codex-max",
        "gpt-5.1-codex-mini",
        "gpt-5.2",
        "gpt-5.2-codex",
        "gpt-5.3-codex",
    ]

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def __init__(self) -> None:
        super().__init__()

        if not _copilot_available:
            logger.warning(
                "copilot-sdk package not installed – run:  "
                "pip install github-copilot-sdk"
            )
            self._available = False
            return

        self._available = True
        # Singleton client (created on first call in the running event-loop)
        self._client: CopilotClient | None = None
        self._client_lock: asyncio.Lock | None = None
        self._github_token: str | None = os.environ.get("GITHUB_TOKEN")

        # T3c: Session cache — keyed by (model_id, hash(system_prompt))
        # Reuses sessions within the same pipeline run to avoid per-call overhead.
        self._session_cache: Dict[str, Any] = {}  # key → (session, created_at)
        self._session_cache_lock: asyncio.Lock | None = None

        logger.info("Copilot SDK provider registered (client starts lazily)")

    # ------------------------------------------------------------------
    # Streaming helper
    # ------------------------------------------------------------------

    @staticmethod
    def _is_streaming_enabled() -> bool:
        """Check config to decide whether to use streaming mode."""
        try:
            from tradercat.config import settings
            return settings.llm_streaming_enabled
        except Exception:
            return True

    async def _send_streaming(
        self,
        session,
        prompt: str,
        accumulator: StreamingAccumulator,
    ) -> str:
        """Send a prompt and stream the response via SDK events.

        Uses ``session.on(callback)`` + ``session.send()`` + ``asyncio.Event``
        to receive incremental deltas and assemble the full content.

        Falls back to the final ``assistant.message`` event content to guarantee
        completeness even if deltas are somehow lost.
        """
        done = asyncio.Event()
        final_content: Dict[str, str] = {"message": ""}

        def on_event(event) -> None:
            etype = event.type.value if hasattr(event.type, "value") else str(event.type)

            if etype == "assistant.message_delta":
                delta = getattr(event.data, "delta_content", None) or ""
                accumulator.on_delta(delta)

            elif etype == "assistant.reasoning_delta":
                delta = getattr(event.data, "delta_content", None) or ""
                accumulator.on_reasoning_delta(delta)

            elif etype == "assistant.message":
                # Final complete content — keep as authoritative source
                final_content["message"] = getattr(event.data, "content", "") or ""

            elif etype == "assistant.reasoning":
                pass  # reasoning complete; we already streamed it

            elif etype == "session.idle":
                done.set()

        session.on(on_event)
        await session.send({"prompt": prompt})

        try:
            await asyncio.wait_for(done.wait(), timeout=self.REQUEST_TIMEOUT)
        except asyncio.TimeoutError:
            logger.error("Streaming timed out after %.0fs", self.REQUEST_TIMEOUT)
            raise

        accumulator.log_final()

        # Prefer the authoritative final message; fall back to accumulated deltas
        content = final_content["message"] or accumulator.content
        return content

    # ------------------------------------------------------------------
    # Public interface (LLMProvider ABC)
    # ------------------------------------------------------------------

    def get_provider_name(self) -> str:
        return "copilot"

    def list_supported_models(self) -> List[str]:

        return list(self.KNOWN_MODELS)

    async def generate_thought(
        self,
        prompt: str,
        model_id: str,
        system_prompt: str = None,
        temperature: float = 0.7,
        max_tokens: int = 16384,
        api_key: Optional[str] = None,
    ) -> str:
        """Single-shot generation via the Copilot SDK.

        When streaming is enabled the response is received incrementally and
        each chunk is printed to stderr / logged in real time.

        T3c: Reuses cached sessions when the same (model_id, system_prompt)
        is requested again (common in P3a/P3b batched pipeline calls).
        """
        if not self._available:
            return "Error: copilot-sdk not installed"

        use_streaming = self._is_streaming_enabled()

        async with llm_call_progress(
            role_name=self._role_name or "Copilot",
            model_id=model_id,
            system_prompt_length=len(system_prompt or ""),
            user_prompt_length=len(prompt),
            identity=self._identity,
            phase=self._phase,
            progress_interval=self._progress_interval,
            enabled=self._progress_logging_enabled,
        ) as result_dict:
            client = await self._ensure_client(api_key)

            if use_streaming:
                # ---- Streaming path (fresh session with streaming=True) ----
                session_config: Dict[str, Any] = {
                    "model": model_id,
                    "streaming": True,
                    "infinite_sessions": {"enabled": False},
                }
                if system_prompt:
                    session_config["system_message"] = {"content": system_prompt}

                session = await client.create_session(session_config)
                accumulator = StreamingAccumulator(
                    role_name=self._role_name or "Copilot",
                    model_id=model_id,
                    identity=self._identity,
                    phase=self._phase,
                    enabled=self._progress_logging_enabled,
                )
                try:
                    content = await self._send_streaming(session, prompt, accumulator)
                    result_dict["output_length"] = len(content)
                    result_dict["input_tokens"] = estimate_tokens(system_prompt or "") + estimate_tokens(prompt)
                    result_dict["output_tokens"] = estimate_tokens(content)
                    result_dict["total_tokens"] = result_dict["input_tokens"] + result_dict["output_tokens"]
                    result_dict["token_source"] = "estimated"
                    return content
                except Exception as e:
                    logger.error("Copilot SDK streaming generation error (model=%s): %s", model_id, e)
                    raise
                finally:
                    await self._destroy_session_safe(session)
            else:
                # ---- Non-streaming path (uses session cache) ----
                cache_key = self._session_cache_key(model_id, system_prompt)
                session = await self._get_or_create_session(client, cache_key, model_id, system_prompt)

                try:
                    reply = await session.send_and_wait({"prompt": prompt}, timeout=self.REQUEST_TIMEOUT)
                    content = reply.data.content if (reply and reply.data) else ""
                    result_dict["output_length"] = len(content)
                    result_dict["input_tokens"] = estimate_tokens(system_prompt or "") + estimate_tokens(prompt)
                    result_dict["output_tokens"] = estimate_tokens(content)
                    result_dict["total_tokens"] = result_dict["input_tokens"] + result_dict["output_tokens"]
                    result_dict["token_source"] = "estimated"
                    return content
                except Exception as e:
                    logger.error("Copilot SDK generation error (model=%s): %s", model_id, e)
                    await self._evict_session(cache_key)
                    raise

    async def chat(
        self,
        messages: List[Dict[str, str]],
        model_id: str,
        temperature: float = 0.7,
        max_tokens: int = 16384,
        api_key: Optional[str] = None,
    ) -> str:
        """Multi-turn chat via the Copilot SDK.

        The Copilot SDK is session-based.  To avoid N round-trips for N
        historical turns, the full message history is flattened into a single
        prompt (previous turns become context) and sent in **one** request.
        """
        if not self._available:
            return "Error: copilot-sdk not installed"

        # Calculate prompt lengths
        total_prompt_length = sum(len(str(msg.get("content", ""))) for msg in messages)
        system_prompt_length = 0
        for msg in messages:
            if msg.get("role") == "system":
                system_prompt_length = len(msg.get("content", ""))
                break

        use_streaming = self._is_streaming_enabled()

        async with llm_call_progress(
            role_name=self._role_name or "Copilot",
            model_id=model_id,
            system_prompt_length=system_prompt_length,
            user_prompt_length=total_prompt_length - system_prompt_length,
            identity=self._identity,
            phase=self._phase,
            progress_interval=self._progress_interval,
            enabled=self._progress_logging_enabled,
        ) as result_dict:
            client = await self._ensure_client(api_key)

            # Separate system message from the conversation
            system_content: Optional[str] = None
            conversation: List[Dict[str, str]] = []
            for msg in messages:
                if msg.get("role") == "system":
                    if system_content is None:
                        system_content = msg.get("content", "")
                    else:
                        system_content += "\n" + msg.get("content", "")
                else:
                    conversation.append(msg)

            flat_prompt = self._flatten_conversation(conversation)

            if use_streaming:
                # ---- Streaming path ----
                session_config: Dict[str, Any] = {
                    "model": model_id,
                    "streaming": True,
                    "infinite_sessions": {"enabled": False},
                }
                if system_content:
                    session_config["system_message"] = {"content": system_content}

                session = await client.create_session(session_config)
                accumulator = StreamingAccumulator(
                    role_name=self._role_name or "Copilot",
                    model_id=model_id,
                    identity=self._identity,
                    phase=self._phase,
                    enabled=self._progress_logging_enabled,
                )
                try:
                    content = await self._send_streaming(session, flat_prompt, accumulator)
                    result_dict["output_length"] = len(content)
                    result_dict["input_tokens"] = estimate_tokens(system_content or "") + estimate_tokens(flat_prompt)
                    result_dict["output_tokens"] = estimate_tokens(content)
                    result_dict["total_tokens"] = result_dict["input_tokens"] + result_dict["output_tokens"]
                    result_dict["token_source"] = "estimated"
                    return content
                except Exception as e:
                    logger.error("Copilot SDK streaming chat error (model=%s): %s", model_id, e)
                    raise
                finally:
                    await self._destroy_session_safe(session)
            else:
                # ---- Non-streaming path ----
                session_config: Dict = {
                    "model": model_id,
                    "infinite_sessions": {"enabled": False},
                }
                if system_content:
                    session_config["system_message"] = {"content": system_content}

                session = await client.create_session(session_config)
                try:
                    reply = await session.send_and_wait({"prompt": flat_prompt}, timeout=self.REQUEST_TIMEOUT)
                    content = reply.data.content if (reply and reply.data) else ""
                    result_dict["output_length"] = len(content)
                    result_dict["input_tokens"] = estimate_tokens(system_content or "") + estimate_tokens(flat_prompt)
                    result_dict["output_tokens"] = estimate_tokens(content)
                    result_dict["total_tokens"] = result_dict["input_tokens"] + result_dict["output_tokens"]
                    result_dict["token_source"] = "estimated"
                    return content
                except Exception as e:
                    logger.error("Copilot SDK chat error (model=%s): %s", model_id, e)
                    raise
                finally:
                    await self._destroy_session_safe(session)

    # ------------------------------------------------------------------
    # Session cache (T3c)
    # ------------------------------------------------------------------

    @staticmethod
    def _session_cache_key(model_id: str, system_prompt: str | None) -> str:
        """Build a cache key from model + hash of system prompt."""
        sp_hash = hashlib.md5((system_prompt or "").encode()).hexdigest()[:12]
        return f"{model_id}:{sp_hash}"

    async def _get_or_create_session(self, client, cache_key: str, model_id: str, system_prompt: str | None):
        """Return a cached session or create a new one."""
        if self._session_cache_lock is None:
            self._session_cache_lock = asyncio.Lock()

        async with self._session_cache_lock:
            # Check cache
            if cache_key in self._session_cache:
                session, created_at = self._session_cache[cache_key]
                if time.monotonic() - created_at < self.SESSION_CACHE_TTL:
                    logger.debug("T3c: Session cache HIT for %s", cache_key)
                    return session
                else:
                    # Expired — destroy and recreate
                    logger.debug("T3c: Session cache EXPIRED for %s", cache_key)
                    await self._destroy_session_safe(session)
                    del self._session_cache[cache_key]

            # Evict oldest if at capacity
            if len(self._session_cache) >= self.SESSION_CACHE_MAX:
                oldest_key = min(self._session_cache, key=lambda k: self._session_cache[k][1])
                old_session, _ = self._session_cache.pop(oldest_key)
                await self._destroy_session_safe(old_session)
                logger.debug("T3c: Evicted oldest session %s", oldest_key)

            # Create new session
            session_config: Dict = {
                "model": model_id,
                "infinite_sessions": {"enabled": True},
            }
            if system_prompt:
                session_config["system_message"] = {"content": system_prompt}

            session = await client.create_session(session_config)
            self._session_cache[cache_key] = (session, time.monotonic())
            logger.debug("T3c: Session cache MISS — created new session for %s", cache_key)
            return session

    async def _evict_session(self, cache_key: str) -> None:
        """Remove and destroy a session from the cache."""
        if self._session_cache_lock is None:
            return
        async with self._session_cache_lock:
            entry = self._session_cache.pop(cache_key, None)
            if entry:
                await self._destroy_session_safe(entry[0])
                logger.debug("T3c: Evicted failed session %s", cache_key)

    async def destroy_session_cache(self) -> None:
        """Tear down all cached sessions. Call at end of pipeline run."""
        if not self._session_cache:
            return
        if self._session_cache_lock is None:
            self._session_cache_lock = asyncio.Lock()
        async with self._session_cache_lock:
            for key, (session, _) in list(self._session_cache.items()):
                await self._destroy_session_safe(session)
            count = len(self._session_cache)
            self._session_cache.clear()
            logger.info("T3c: Destroyed %d cached sessions", count)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _ensure_client(self, api_key: str | None = None) -> CopilotClient:
        """Return (or create) the shared :class:`CopilotClient`."""
        # Lazily create the asyncio Lock inside the running event-loop.
        if self._client_lock is None:
            self._client_lock = asyncio.Lock()

        token = api_key or self._github_token

        async with self._client_lock:
            if self._client is not None:
                return self._client

            # Derive SDK log_level from the application-wide setting so
            # Copilot client verbosity follows the system logger.
            sdk_log_level = "warning"
            try:
                from tradercat.config import settings
                _level_map = {
                    "DEBUG": "debug",
                    "INFO": "info",
                    "WARNING": "warning",
                    "WARN": "warning",
                    "ERROR": "error",
                    "CRITICAL": "error",
                }
                sdk_log_level = _level_map.get(settings.log_level.upper(), "warning")
            except Exception:
                pass

            opts: Dict[str, Any] = {
                "log_level": sdk_log_level,
                "auto_start": True,
                "auto_restart": True,
            }
            if token:
                opts["github_token"] = token

            self._client = _CopilotClient(opts)  # type: ignore[misc]
            await self._client.start()
            logger.info("Copilot SDK client started (pid reused for future calls)")

            # Try to refresh the known models list from the live server.
            try:
                models = await self._client.list_models()
                if models:
                    # SDK may return objects with .id or plain dicts with ["id"]
                    self.KNOWN_MODELS = [
                        m.id if hasattr(m, "id") else m["id"]
                        for m in models
                        if (hasattr(m, "id") and m.id) or (isinstance(m, dict) and m.get("id"))
                    ]
                    logger.info(
                        "Copilot models refreshed from server: %s",
                        ", ".join(self.KNOWN_MODELS),
                    )
                else:
                    logger.warning("Copilot client returned empty model list")
            except Exception as exc:
                logger.debug("Could not list Copilot models: %s (using fallback list)", exc)

            return self._client

    @staticmethod
    def _flatten_conversation(conversation: List[Dict[str, str]]) -> str:
        """Collapse a multi-turn message list into a single prompt string.

        When only one user message is present we pass it through as-is so the
        LLM sees a clean, simple prompt.
        """
        if len(conversation) == 0:
            return ""
        if len(conversation) == 1:
            return conversation[0].get("content", "")

        # Multiple turns → format as labelled context + final prompt
        context_parts: List[str] = []
        for msg in conversation[:-1]:
            role = msg.get("role", "user").capitalize()
            content = msg.get("content", "")
            context_parts.append(f"[{role}]: {content}")

        last_content = conversation[-1].get("content", "")
        context_block = "\n\n".join(context_parts)
        return (
            f"Previous conversation:\n{context_block}\n\n"
            f"{last_content}"
        )

    @staticmethod
    async def _destroy_session_safe(session) -> None:
        """Destroy a session, swallowing errors."""
        try:
            await session.destroy()
        except Exception:
            pass
