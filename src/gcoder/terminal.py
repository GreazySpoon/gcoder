# src/gcoder/terminal.py

import os
from pathlib import Path
import asyncio
import uuid
from typing import Dict, Any

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.events import Event
from google.genai.types import Content, Part
from rich.console import Console
from rich.panel import Panel
from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.styles import Style
from prompt_toolkit.formatted_text import FormattedText

# Import both agent modules
from gcoder.agents import basic_agent
from gcoder.agents import autonomous_agent
# Import UI and system helpers
from gcoder.system.callbacks import console as rich_console
from gcoder.ui.task_ui import TaskDashboard

# --- ADK Integration for Terminal (In-Memory) ---
session_service = InMemorySessionService()

async def handle_basic_agent_run(runner: Runner, session_id: str, prompt: str):
    """Handles a run for the basic, conversational agent."""
    user_message = Content(role='user', parts=[Part(text=prompt)])
    final_response_started = False

    async for event in runner.run_async(user_id="cli_user", session_id=session_id, new_message=user_message):
        if not isinstance(event, Event): continue
        if event.error_message:
            rich_console.print(f"[bold red]Agent Error: {event.error_message}[/bold red]")
            continue
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

async def handle_autonomous_task_run(prompt: str, approval: bool):
    """Handles a run for the autonomous task agent, with UI dashboard."""
    task_description = " ".join(prompt.split(' ')[1:])
    if not task_description:
        rich_console.print("[bold red]Error: No task description provided for @task.[/bold red]")
        return

    dashboard = TaskDashboard(task_description)
    runner = Runner(
        agent=autonomous_agent.root_agent,
        app_name="gcoder_task_cli",
        session_service=session_service
    )
    session_id = f"task_session_{uuid.uuid4()}"
    
    await session_service.create_session(
        app_name="gcoder_task_cli", user_id="cli_user", session_id=session_id,
        state={
            'original_task': task_description,
            'human_in_the_loop': approval,
            'cwd': os.getcwd()
        }
    )
    user_message = Content(role='user', parts=[Part(text=task_description)])

    rich_console.print(f"[bold magenta]🚀 Starting autonomous task:[/bold magenta] {task_description}")
    
    final_summary_text = ""
    with dashboard.live:
        async for event in runner.run_async(user_id="cli_user", session_id=session_id, new_message=user_message):
            if event.actions and event.actions.state_delta:
                dashboard.update(event.actions.state_delta)
            
            if event.is_final_response() and isinstance(event.content, Content) and event.content.parts:
                part = event.content.parts[0]
                if isinstance(part, Part) and part.text:
                    final_summary_text = part.text

    final_report = final_summary_text or "Task finished without a final summary."
    rich_console.print(Panel(final_report, title="[bold green]✅ Final Summary[/bold green]", border_style="green"))
    rich_console.print("[bold magenta]🏁 Autonomous task finished.[/bold magenta]")


def get_prompt_message(cwd: str) -> FormattedText:
    home_dir = str(Path.home())
    display_cwd = "~" + cwd[len(home_dir):] if cwd.startswith(home_dir) else cwd
    return FormattedText([('class:agent', '(gcoder)'), ('class:seperator', ' - '), ('class:cwd', display_cwd), ('class:prompt', ' > ')])

async def start_interactive_session(args):
    """Main interactive loop that dispatches to the correct agent."""
    basic_runner = Runner(
        agent=basic_agent.root_agent,
        app_name="gcoder_cli",
        session_service=session_service
    )
    
    session_id = str(uuid.uuid4())
    rich_console.print(f"[bold green]Starting new in-memory session:[/] {session_id}")
    await session_service.create_session(
        app_name="gcoder_cli", user_id="cli_user", session_id=session_id,
        state={'cwd': os.getcwd(), 'human_in_the_loop': args.approval}
    )

    history_file = Path(os.path.expanduser("~/.gcoder/.session_history"))
    prompt_style = Style.from_dict({'agent': 'bold cyan', 'cwd': 'bold green', 'seperator': 'white', 'prompt': 'white'})
    pt_session = PromptSession(history=FileHistory(str(history_file)), style=prompt_style)
    
    rich_console.print("[bold yellow]Welcome to Gcoder. Type '@task [description]' for autonomous mode or 'exit' to quit.[/bold yellow]")
    
    while True:
        try:
            current_cwd = os.getcwd()
            prompt_message = get_prompt_message(current_cwd)
            prompt = await pt_session.prompt_async(prompt_message, auto_suggest=AutoSuggestFromHistory())

            if prompt.lower() in ['exit', 'quit']:
                break
            if not prompt.strip():
                continue
            
            if prompt.strip().startswith('@task'):
                await handle_autonomous_task_run(prompt, args.approval)
            else:
                await handle_basic_agent_run(basic_runner, session_id, prompt)
            
        except (EOFError, KeyboardInterrupt):
            break
        except Exception as e:
            rich_console.print(f"\n[bold red]An unexpected error occurred: {e}[/bold red]")
            import traceback
            traceback.print_exc()

    rich_console.print("\n[bold yellow]Exiting session.[/bold yellow]")