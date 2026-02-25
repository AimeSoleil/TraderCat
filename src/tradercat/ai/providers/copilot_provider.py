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
import os
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from tradercat.ai.llm_provider_factory import LLMFactory
from tradercat.ai.providers.llm_interface import LLMProvider
from tradercat.logger.logger import get_logger

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
    REQUEST_TIMEOUT = 300.0

    # Fallback catalogue when the CLI is not reachable at import time.
    KNOWN_MODELS = [
        "gpt-4o",
        "gpt-4o-mini",
        "gpt-4",
        "o1",
        "o3-mini",
        "claude-sonnet-4-20250514",
        "claude-3.5-haiku",
        "gemini-2.0-flash",
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

        logger.info("Copilot SDK provider registered (client starts lazily)")

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
        max_tokens: int = 8192,
        api_key: Optional[str] = None,
    ) -> str:
        """Single-shot generation via the Copilot SDK."""
        if not self._available:
            return "Error: copilot-sdk not installed"

        client = await self._ensure_client(api_key)

        session_config: Dict = {
            "model": model_id,
            "infinite_sessions": {"enabled": False},
        }
        if system_prompt:
            session_config["system_message"] = {"content": system_prompt}

        session = await client.create_session(session_config)
        try:
            reply = await session.send_and_wait({"prompt": prompt}, timeout=self.REQUEST_TIMEOUT)
            return reply.data.content if (reply and reply.data) else ""
        except Exception as e:
            logger.error("Copilot SDK generation error (model=%s): %s", model_id, e)
            raise
        finally:
            await self._destroy_session_safe(session)

    async def chat(
        self,
        messages: List[Dict[str, str]],
        model_id: str,
        temperature: float = 0.7,
        max_tokens: int = 8192,
        api_key: Optional[str] = None,
    ) -> str:
        """Multi-turn chat via the Copilot SDK.

        The Copilot SDK is session-based.  To avoid N round-trips for N
        historical turns, the full message history is flattened into a single
        prompt (previous turns become context) and sent in **one** request.
        """
        if not self._available:
            return "Error: copilot-sdk not installed"

        client = await self._ensure_client(api_key)

        # Separate system message from the conversation
        system_content: Optional[str] = None
        conversation: List[Dict[str, str]] = []
        for msg in messages:
            if msg.get("role") == "system":
                # Concatenate if several system messages exist
                if system_content is None:
                    system_content = msg.get("content", "")
                else:
                    system_content += "\n" + msg.get("content", "")
            else:
                conversation.append(msg)

        session_config: Dict = {
            "model": model_id,
            "infinite_sessions": {"enabled": False},
        }
        if system_content:
            session_config["system_message"] = {"content": system_content}

        session = await client.create_session(session_config)
        try:
            prompt = self._flatten_conversation(conversation)
            reply = await session.send_and_wait({"prompt": prompt}, timeout=self.REQUEST_TIMEOUT)
            return reply.data.content if (reply and reply.data) else ""
        except Exception as e:
            logger.error("Copilot SDK chat error (model=%s): %s", model_id, e)
            raise
        finally:
            await self._destroy_session_safe(session)

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

            opts: Dict[str, Any] = {
                "log_level": "warning",
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
                    self.KNOWN_MODELS = [m.id for m in models]
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
