import os
import asyncio
from typing import List, Dict, Tuple
from tradercat.ai.providers.llm_provider import LLMProvider
from tradercat.ai.llm_provider_factory import LLMFactory
from tradercat.logger.logger import get_logger

try:
    from copilot import CopilotClient
except ImportError:
    CopilotClient = None

logger = get_logger(__name__)

@LLMFactory.register("copilot")
class CopilotProvider(LLMProvider):
    """
    GitHub Copilot Provider.
    Uses github/copilot-sdk to communicate with the Copilot CLI via JSON-RPC.
    Requires 'copilot-sdk' installed and GitHub Copilot CLI authenticated.
    """
    def __init__(self, api_key: str = None):
        super().__init__(api_key=api_key)
        
        self._client = None
        self._client_lock = asyncio.Lock()

        # Copilot usually relies on CLI auth ('gh auth login'), 
        # so explicit token handling might not be needed here unless the SDK requires it.
        # We perform a check to see if the SDK is installed.
        if not CopilotClient:
            logger.warning("Copilot SDK not found. Please install via 'pip install copilot-sdk' (check specific package name).")

    def get_provider_name(self) -> str: return "copilot"

    def get_provider_description(self) -> str:
        return "https://github.com/github/copilot-sdk"

    def list_supported_models(self) -> List[str]:
        # Copilot CLI normally handles model selection dynamically, 
        # but we can list common ones or those requested by the user.
        default_models = [
            "gpt-4o", 
            "gpt-4o-mini"
        ]
        
        extra = os.environ.get("TRADERCAT_AI_MODELS", "")
        if extra:
            default_models.extend([m.strip() for m in extra.split(",") if m.strip()])

        seen = set()
        return [m for m in default_models if not (m in seen or seen.add(m))]

    async def _get_client(self):
        """
        Singleton-like access to the started CopilotClient.
        Starts the client (heavy process) only once.
        """
        if not CopilotClient:
            return None
            
        async with self._client_lock:
            if self._client is None:
                try:
                    self._client = CopilotClient()
                    await self._client.start()
                    logger.info("Copilot Client started successfully (Persistent).")
                except Exception as e:
                    logger.error(f"Failed to start Copilot Client: {e}")
                    self._client = None
            return self._client

    async def _run_copilot_session(self, prompt: str, model_id: str, system_prompt: str = None, prev_session_id: str | None = None) -> Tuple[str, str]:
        """
        Helper method to manage session using the persistent client.
        Creates a new session for the request (lightweight) but reuses the connection.
        """
        client = await self._get_client()
        if not client:
            return None, "Error: CopilotClient not initialized (SDK missing or start failed)."

        response_content = []
        session = None
        
        try:
            # Create/Resume a session (lightweight RPC call)
            session_config = {"model": model_id}
            
            # Add system message if provided
            if system_prompt:
                session_config["systemMessage"] = {
                    "content": system_prompt
                }

            if prev_session_id:
                session = await client.resume_session(prev_session_id)
            else:
                session = await client.create_session(session_config)

            # Event handling
            done = asyncio.Event()

            def on_event(event):
                try:
                    # Adjust event property access based on actual SDK structure
                    if hasattr(event, "type") and event.type.value == "assistant.message":
                        if hasattr(event, "data") and hasattr(event.data, "content"):
                            response_content.append(event.data.content)
                    elif hasattr(event, "type") and event.type.value == "session.idle":
                        done.set()
                except Exception as inner_e:
                    logger.error(f"Event handler error: {inner_e}")
                    done.set()

            session.on(on_event)

            # Send message
            await session.send({"prompt": prompt})

            # Wait for completion
            await done.wait()
            
        except Exception as e:
            logger.error(f"Copilot Session Error: {e}")
            return None, f"Error executing Copilot session: {str(e)}"
        finally:
            # Clean up only the session, keep the client active
            if session:
                try:
                    await session.destroy()
                except Exception as e:
                    logger.error(f"Error destroying session: {e}")

        return session.session_id, "".join(response_content)

    async def generate_thought(self, prompt: str, model_id: str, system_prompt: str = None) -> Tuple[str, str]:
        session_id, response_text = await self._run_copilot_session(prompt, model_id, system_prompt=system_prompt)
        return session_id, response_text

    async def chat(self, messages: List[Dict[str, str]], model_id: str, prev_session_id: str | None = None) -> Tuple[str, str]:
        """
        For chat, we reconstruct the conversation history into a single prompt
        since the basic SDK usage creates a fresh session/turn per call.
        """
        system_prompt = None
        prompt_lines = []
        
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            
            if role == "system":
                system_prompt = content
                continue
            
            role_cap = role.capitalize()
            prompt_lines.append(f"{role_cap}: {content}")
        
        if prev_session_id:
            # if resuming, only send user messages
            conversations = [line for line in prompt_lines if line.lower().startswith("user:")]
        else:
            conversations = "\n".join(prompt_lines)

        return await self._run_copilot_session(conversations, model_id, system_prompt, prev_session_id)