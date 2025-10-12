# src/gcoder/terminal.py

import os
from pathlib import Path
import asyncio
import uuid

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.events import Event
from google.genai.types import Content, Part
from rich.console import Console
from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.styles import Style
from prompt_toolkit.formatted_text import FormattedText

from gcoder.agents import basic_agent
from gcoder.system.callbacks import console as rich_console

# --- ADK Integration for Terminal (In-Memory) ---

session_service = InMemorySessionService()

async def handle_agent_run(runner: Runner, session_id: str, prompt: str):
    user_message = Content(role='user', parts=[Part(text=prompt)])
    final_response_started = False

    async for event in runner.run_async(
        user_id="cli_user", session_id=session_id, new_message=user_message
    ):
        # THE CORE FIX: Paranoid, defensive checks to prevent crashes
        if not isinstance(event, Event):
            rich_console.print(f"[bold red]System Warning: Received non-Event object: {type(event).__name__}[/bold red]")
            continue

        # Handle explicit errors from the framework
        if event.error_message:
            rich_console.print(f"[bold red]Agent Error: {event.error_message}[/bold red]")
            continue
        
        # Safely handle and print text content
        if event.is_final_response():
            content = event.content
            if isinstance(content, Content) and content.parts:
                part = content.parts[0]
                if isinstance(part, Part) and part.text:
                    if not final_response_started:
                        rich_console.print("---")
                        final_response_started = True
                    rich_console.print(part.text, end="", style="green")

    rich_console.print()

def get_prompt_message(cwd: str) -> FormattedText:
    home_dir = str(Path.home())
    display_cwd = "~" + cwd[len(home_dir):] if cwd.startswith(home_dir) else cwd
    return FormattedText([
        ('class:agent', '(gcoder)'), ('class:seperator', ' - '),
        ('class:cwd', display_cwd), ('class:prompt', ' > ')
    ])

async def start_interactive_session(args):
    runner = Runner(
        agent=basic_agent.root_agent,
        app_name="gcoder_cli",
        session_service=session_service
    )
    
    session_id = str(uuid.uuid4())
    rich_console.print(f"[bold green]Starting new in-memory session:[/] {session_id}")
    await session_service.create_session(
        app_name="gcoder_cli",
        user_id="cli_user",
        session_id=session_id,
        state={'cwd': os.getcwd(), 'human_in_the_loop': args.approval}
    )

    history_file = Path(os.path.expanduser("~/.gcoder/.session_history"))
    prompt_style = Style.from_dict({'agent': 'bold cyan', 'cwd': 'bold green', 'seperator': 'white', 'prompt': 'white'})
    pt_session = PromptSession(history=FileHistory(str(history_file)), style=prompt_style)
    
    rich_console.print("[bold yellow]Welcome to Gcoder. Type 'exit' to quit.[/bold yellow]")
    
    while True:
        try:
            current_cwd = os.getcwd()
            prompt_message = get_prompt_message(current_cwd)
            prompt = await pt_session.prompt_async(prompt_message, auto_suggest=AutoSuggestFromHistory())

            if prompt.lower() in ['exit', 'quit']:
                break
            if not prompt.strip():
                continue
            
            await handle_agent_run(runner, session_id, prompt)
            
        except (EOFError, KeyboardInterrupt):
            break
        except Exception as e:
            rich_console.print(f"\n[bold red]An unexpected error occurred in the main loop: {e}[/bold red]")
            import traceback
            traceback.print_exc()

    rich_console.print("\n[bold yellow]Exiting session.[/bold yellow]")