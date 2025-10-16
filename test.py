# simple_test.py (Corrected)

import asyncio
import os
from typing import Optional

# --- ADK Imports ---
from google.adk.agents import LlmAgent
from google.adk.models.lite_llm import LiteLlm
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.events import Event
from google.genai import types

# --- Imports for the Callback ---
from google.adk.agents.callback_context import CallbackContext
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
# --- Configuration ---
os.environ['OLLAMA_API_BASE'] = 'http://10.10.60.28:11434'

# --- The Corrected Callback Logic ---

def simple_context_callback(
    callback_context: CallbackContext, llm_request: LlmRequest
) -> Optional[LlmResponse]:
    """
    A robust callback that injects context by prepending a system message
    to the conversation history, which is compatible with LiteLLM.
    """
    print("--- Running simple_context_callback ---")
    
    dynamic_context_str = f"Current Time: {asyncio.get_event_loop().time()}"
    base_instruction = "You are a helpful assistant." # The original instruction
    
    full_instruction = f"{base_instruction}\n\n--- System Context ---\n{dynamic_context_str}"

    # THE CORE FIX: Modify the message history (llm_request.contents)
    # instead of the configuration (llm_request.config.system_instruction).
    
    # Check if the first message is already our system prompt to avoid adding it repeatedly.
    if llm_request.contents and llm_request.contents[0].role == "system":
        # It already exists, so we can update it.
        print("Updating existing system message in history.")
        llm_request.contents[0].parts = [types.Part(text=full_instruction)]
    else:
        # It doesn't exist, so we insert it at the beginning.
        print("Prepending new system message to history.")
        system_message = types.Content(role="system", parts=[types.Part(text=full_instruction)])
        llm_request.contents.insert(0, system_message)
        
    return None # Return None to allow the LLM call to proceed normally

# --- Dummy Tool ---
def get_weather(city: Optional[str] = None) -> str:
    """A dummy tool to ensure tool schemas are processed correctly."""
    if city:
        return f"Weather in {city} is sunny."
    return "Please specify a city."

# --- Agent Definition with the Corrected Callback ---
test_agent = LlmAgent(
    name="TestAgentWithCallback",
    model=LiteLlm(model="ollama_chat/qwen3-30-8:latest"),
    tools=[get_weather],
    # The instruction is now passed here, and the callback will enhance it.
    instruction="You are a helpful assistant.",
    # We attach the robust callback.
    before_model_callback=simple_context_callback
)

# --- Runner and Session Setup ---
session_service = InMemorySessionService()
runner = Runner(
    agent=test_agent,
    app_name="test_app",
    session_service=session_service
)

# --- Main Execution Logic ---
async def main():
    session_id = "test_session_123"
    await session_service.create_session(
        app_name="test_app", 
        user_id="test_user", 
        session_id=session_id
    )
    
    prompt = "hi"
    print(f"--- Sending prompt: '{prompt}' ---")

    user_message = types.Content(role='user', parts=[types.Part(text=prompt)])

    try:
        async for event in runner.run_async(
            user_id="test_user", session_id=session_id, new_message=user_message
        ):
            print("\n--- Received Event ---")
            if not isinstance(event, Event):
                print(f"ERROR: Received a non-Event object of type {type(event)}")
                continue

            print(f"Author: {event.author}")
            print(f"Is Final: {event.is_final_response()}")
            
            content = event.content
            if isinstance(content, types.Content) and content.parts:
                part = content.parts[0]
                if isinstance(part, types.Part):
                    if part.text:
                        print(f"  Content (Text): {part.text}")
                    if part.function_call:
                        print(f"  Content (FunctionCall): {part.function_call.name}({part.function_call.args})")
            
            if event.error_message:
                print(f"  Error Message: {event.error_message}")
            
            print("----------------------")

    except Exception as e:
        print("\n--- A CRITICAL ERROR OCCURRED ---")
        print(f"Exception Type: {type(e).__name__}")
        print(f"Exception Details: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())