import asyncio
from typing import List, Dict
from tradercat.ai.providers.llm_interface import LLMProvider
from tradercat.ai.llm_provider_factory_ import LLMFactory
from tradercat.logger.logger import get_logger

# Optional dependency
try:
    from copilot import CopilotClient
except ImportError:
    CopilotClient = None

logger = get_logger(__name__)

@LLMFactory.register("copilot-sdk")
class CopilotSDKProvider(LLMProvider):
    """
    Integration for the programmatic Copilot Client SDK.
    Wraps the async event-driven architecture into TraderCat's request/response model.
    """
    def __init__(self, api_key: str = None):
        super().__init__(api_key=api_key)
        
        if not CopilotClient:
            logger.warning("Optional dependency 'copilot' SDK not found. Install via pip if needed.")
            self.client_ready = False
        else:
            self.client_ready = True

    def get_provider_name(self) -> str: return "copilot-sdk"

    @staticmethod
    def list_supported_models() -> List[str]:
        # Copilot SDK usually defaults to latest models available to the authenticated session
        return ["gpt-5", "gpt-4o", "default"]

    async def _run_session(self, prompt: str, model_id: str, history: List[Dict] = None) -> str:
        """
        Internal helper to manage the full session lifecycle for a single request.
        """
        if not self.client_ready:
            return "Error: 'copilot' python package not installed."

        client = CopilotClient()
        response_content = []
        
        try:
            # 1. Start Client
            await client.start()

            # 2. Create Session
            target_model = "gpt-4o" if model_id == "default" else model_id
            session = await client.create_session({"model": target_model})

            # 3. Setup Logic
            done = asyncio.Event()
            
            def on_event(event):
                # Robustly check event type
                event_type = getattr(event.type, "value", str(event.type))
                
                if event_type == "assistant.message":
                    if hasattr(event.data, "content") and event.data.content:
                        response_content.append(event.data.content)
                elif event_type == "session.idle":
                    done.set()
                elif event_type == "error":
                    logger.error(f"Copilot SDK Error: {event.data}")
                    response_content.append(f"[Error: {event.data}]")
                    done.set()

            session.on(on_event)

            # 4. Construct Payload
            if history:
                full_context = "\n".join([f"{m['role']}: {m['content']}" for m in history])
                full_context += f"\nuser: {prompt}"
                payload = {"prompt": full_context}
            else:
                payload = {"prompt": prompt}

            # 5. Send and Wait
            await session.send(payload)
            
            # Wait with a timeout
            try:
                await asyncio.wait_for(done.wait(), timeout=120)
            except asyncio.TimeoutError:
                logger.error("Copilot session timed out.")
                return "Error: Timeout waiting for Copilot response."

            # 6. Cleanup
            await session.destroy()
        
        except Exception as e:
            logger.error(f"Copilot SDK Execution Error: {e}")
            return f"Error: {str(e)}"
        
        finally:
            await client.stop()

        return "".join(response_content).strip()

    async def generate_thought(self, prompt: str, model_id: str, system_prompt: str = None) -> str:
        final_prompt = f"System: {system_prompt}\nUser: {prompt}" if system_prompt else prompt
        return await self._run_session(final_prompt, model_id)

    async def chat(self, messages: List[Dict[str, str]], model_id: str) -> str:
        last_msg = messages[-1]['content']
        history_context = messages[:-1]
        return await self._run_session(last_msg, model_id, history=history_context)