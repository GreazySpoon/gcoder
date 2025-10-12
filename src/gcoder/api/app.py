# src/gcoder/api/app.py

import os
import json
import asyncio
import uuid
from pathlib import Path
from fastapi import FastAPI, Request, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from sse_starlette.sse import EventSourceResponse
from typing import AsyncGenerator

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.events import Event
from google.genai import types

from .models import CreateSessionResponse

# --- ADK Integration Setup (In-Memory) ---
session_service = InMemorySessionService()
# Cache runners to avoid re-instantiation
active_runners: dict[str, Runner] = {}

def get_runner_for_agent(agent_module) -> Runner:
    agent_name = agent_module.root_agent.name
    if agent_name in active_runners:
        return active_runners[agent_name]
    runner = Runner(
        agent=agent_module.root_agent,
        app_name="gcoder_api",
        session_service=session_service
    )
    active_runners[agent_name] = runner
    return runner

# --- FastAPI Application ---
app = FastAPI(
    title="Gcoder API",
    description="API for interacting with the Gcoder AI assistant (In-Memory Mode).",
    version="0.1.0"
)

@app.on_event("startup")
async def startup_event():
    """Handles server startup tasks."""
    os.environ['OLLAMA_API_BASE'] = 'http://10.10.60.28:11434'
    web_dir = Path(__file__).parent.parent.parent.parent / "web"
    if web_dir.exists():
        app.mount("/static", StaticFiles(directory=web_dir), name="static")
    else:
        print(f"Warning: Web UI directory not found at '{web_dir}'.")

@app.get("/")
async def read_index():
    """Serves the main index.html file for the web UI."""
    web_dir = Path(__file__).parent.parent.parent.parent / "web"
    index_path = web_dir / 'index.html'
    if index_path.exists():
        return FileResponse(index_path)
    raise HTTPException(status_code=404, detail="Web UI not found.")

@app.post("/sessions", response_model=CreateSessionResponse)
async def create_session() -> CreateSessionResponse:
    """Creates a new in-memory session and returns its ID."""
    session_id = str(uuid.uuid4())
    await session_service.create_session(
        app_name="gcoder_api",
        user_id="api_user",
        session_id=session_id,
        state={'cwd': os.getcwd()}
    )
    return CreateSessionResponse(session_id=session_id)

async def translate_adk_event_to_json(event: Event) -> str:
    """A defensive adapter to convert ADK Events to the frontend's JSON format."""
    if not isinstance(event, Event):
        return json.dumps({"event": "error", "data": f"Invalid event type: {type(event).__name__}"})
    if event.error_message:
        return json.dumps({"event": "error", "data": f"Agent Error: {event.error_message}"})
    if event.actions and event.actions.state_delta:
        return json.dumps({"event": "ui_update", "state": event.actions.state_delta})
    if function_calls := event.get_function_calls():
        tool_data = [{"tool_name": call.name, "tool_args": call.args} for call in function_calls]
        return json.dumps({"event": "tool_call", "tools": tool_data})
    if function_responses := event.get_function_responses():
        tool_data = [{"tool_name": resp.name, "result": str(resp.response)} for resp in function_responses]
        return json.dumps({"event": "tool_response", "tools": tool_data})
    content = event.content
    if isinstance(content, types.Content) and content.parts:
        part = content.parts[0]
        if isinstance(part, types.Part) and part.text:
            is_final = event.is_final_response()
            event_type = "final_summary" if is_final else "content_chunk"
            return json.dumps({"event": event_type, "data": part.text})
    return json.dumps({"event": "system_update", "author": event.author})

@app.get("/sessions/{session_id}/dispatch")
async def dispatch_command(session_id: str, prompt: str, request: Request):
    """Main endpoint for sending a prompt to an agent and streaming back events."""
    command, *args = prompt.strip().split(maxsplit=1)
    task_description = args[0] if args else ""
    
    try:
        if command == '@task':
            from gcoder.agents import autonomous_agent as agent_module
            user_input = task_description
            if not user_input:
                raise HTTPException(status_code=400, detail="No task description for @task.")
        else:
            from gcoder.agents import basic_agent as agent_module
            user_input = prompt
        runner = get_runner_for_agent(agent_module)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to initialize agent runner: {e}")

    async def event_generator() -> AsyncGenerator[str, None]:
        try:
            if command == '@task':
                 await session_service.create_session(
                    app_name="gcoder_api", user_id="api_user", session_id=session_id,
                    state={
                        'original_task': user_input,
                        'cwd': os.getcwd()
                    },
                )
            user_message = types.Content(role='user', parts=[types.Part(text=user_input)])
            async for event in runner.run_async(user_id="api_user", session_id=session_id, new_message=user_message):
                if await request.is_disconnected():
                    break
                json_payload = await translate_adk_event_to_json(event)
                yield json_payload
        except Exception as e:
            error_payload = json.dumps({"event": "error", "data": f"Runner Error: {type(e).__name__}: {e}"})
            yield error_payload
            print(f"Error during API stream generation: {e}")

    return EventSourceResponse(event_generator())