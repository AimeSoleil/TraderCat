import asyncio
from typing import List, Dict, Callable, Optional, AsyncGenerator
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
    REQ: 'pip install github-copilot-sdk' AND local authenticated GitHub CLI extension.
    """
    def __init__(self, api_key: str = None):
        super().__init__(api_key=api_key)
        
        self.client_ready = False
        
        if not CopilotClient:
            logger.warning("❌ 'copilot' SDK not found. Install via: pip install github-copilot-sdk")
            return

        try:
            self.client_ready = True 
        except Exception as e:
            logger.warning(f"❌ Failed to initialize Copilot Client: {e}")
            self.client_ready = False

    def get_provider_name(self) -> str: return "copilot-sdk"

    @staticmethod
    def list_supported_models() -> List[str]:
        return ["gpt-5", "gpt-4o", "default"]

    async def _run_session(
        self, 
        prompt: str, 
        model_id: str, 
        history: List[Dict] = None, 
        stream_callback: Optional[Callable[[str], None]] = None
    ) -> str:
        """
        Internal helper to manage the full session lifecycle for a single request.
        Outputs data to stream_callback if provided.
        """
        if not self.client_ready:
            return "Error: Copilot SDK not installed or configured correctly."

        client = CopilotClient()
        response_content = []
        
        try:
            # 1. Start Client
            await client.start()

            # 2. Create Session
            target_model = "gpt-4o" if model_id == "default" else model_id
            session = await client.create_session({
                "model": target_model,
            })

            # 3. Setup Events
            done = asyncio.Event()
            
            def on_event(event):
                event_type = getattr(event.type, "value", str(event.type))
                
                # Helper to handle content chunk
                def process_chunk(chunk):
                    if chunk:
                        response_content.append(chunk)
                        if stream_callback:
                            stream_callback(chunk)

                if event_type == "assistant.message_delta":
                    if hasattr(event.data, "content"):
                        process_chunk(event.data.content)
                elif event_type == "assistant.reasoning_delta":
                    if hasattr(event.data, "content"):
                        process_chunk(event.data.content) # treating reasoning as content for now
                elif event_type == "session.idle":
                    done.set()
                elif event_type == "error":
                    logger.error(f"Copilot SDK Error: {event.data}")
                    err_msg = f"[Error: {event.data}]"
                    response_content.append(err_msg)
                    if stream_callback: stream_callback(err_msg)
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
            
            try:
                await asyncio.wait_for(done.wait(), timeout=300)
            except asyncio.TimeoutError:
                logger.error("Copilot session timed out.")
                return "Error: Timeout waiting for Copilot response."

            # 6. Cleanup
            await session.destroy()
        
        except Exception as e:
            logger.error(f"Copilot SDK Execution Error: {e}")
            return f"Error: {str(e)}"
        
        finally:
            if self.client_ready:
                await client.stop()

        return "".join(response_content).strip()

    async def generate_thought(self, prompt: str, model_id: str, system_prompt: str = None) -> str:
        final_prompt = f"System: {system_prompt}\nUser: {prompt}" if system_prompt else prompt
        return await self._run_session(final_prompt, model_id)

    async def chat(self, messages: List[Dict[str, str]], model_id: str) -> str:
        last_msg = messages[-1]['content']
        history_context = messages[:-1]
        return await self._run_session(last_msg, model_id, history=history_context)

    async def chat_stream(self, messages: List[Dict[str, str]], model_id: str) -> AsyncGenerator[str, None]:
        """
        Async Generator for real-time streaming to UI.
        """
        last_msg = messages[-1]['content']
        history_context = messages[:-1]
        
        # Bridge callback-based SDK to async generator via Queue
        queue = asyncio.Queue()
        
        def push_to_queue(chunk):
            queue.put_nowait(chunk)

        # Run session in background task
        task = asyncio.create_task(
            self._run_session(last_msg, model_id, history=history_context, stream_callback=push_to_queue)
        )

        while True:
            # Wait for either new data or task completion
            get_chunk = asyncio.create_task(queue.get())
            done, _ = await asyncio.wait(
                [get_chunk, task], 
                return_when=asyncio.FIRST_COMPLETED
            )

            if get_chunk in done:
                yield get_chunk