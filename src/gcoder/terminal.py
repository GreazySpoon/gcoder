# src/gcoder/terminal.py
import os
import random
import subprocess
from pathlib import Path
import asyncio
import uuid
from typing import Dict, Any, List, Tuple, Optional

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.events import Event
from google.genai.types import Content, Part
from rich.console import Console
from rich.panel import Panel
from rich.text import Text
from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.styles import Style
from prompt_toolkit.formatted_text import FormattedText

from gcoder.agents import basic_agent, autonomous_agent
from gcoder.system.callbacks import console as rich_console
from gcoder.ui.task_ui import TaskDashboard
from gcoder.system.capability_manager import CapabilityManager

# --- UI & Styling ---

VAPORWAVE_GRADIENTS: List[Tuple[str, str]] = [
    ("#FF79C6", "#61C7C7"),  # Hot Pink to Cool Cyan
    ("#BD93F9", "#50FA7B"),  # Lavender to Lime Green
    ("#FFB86C", "#FF5555"),  # Orange to Red
    ("#8BE9FD", "#FF79C6"),  # Light Cyan to Hot Pink
]

def hex_to_rgb(h: str) -> Tuple[int, int, int]:
    h = h.lstrip('#')
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))

def apply_random_gradient(ascii_art: str) -> Text:
    """Applies a random vaporwave gradient to a multiline ASCII art string."""
    start_hex, end_hex = random.choice(VAPORWAVE_GRADIENTS)
    start_rgb = hex_to_rgb(start_hex)
    end_rgb = hex_to_rgb(end_hex)
    
    text = Text()
    total_chars = len(ascii_art)
    current_char = 0

    for char in ascii_art:
        if char == '\n':
            text.append(char)
            continue
        
        ratio = current_char / max(1, total_chars - 1)
        r = int(start_rgb[0] * (1 - ratio) + end_rgb[0] * ratio)
        g = int(start_rgb[1] * (1 - ratio) + end_rgb[1] * ratio)
        b = int(start_rgb[2] * (1 - ratio) + end_rgb[2] * ratio)
        
        style = f"rgb({r},{g},{b})"
        text.append(char, style=style)
        current_char += 1
        
    return text

def get_git_info() -> Optional[str]:
    """Gets the current git branch and repo name if available."""
    try:
        # Check if we are in a git repository
        toplevel_proc = subprocess.run(['git', 'rev-parse', '--show-toplevel'], capture_output=True, text=True, check=True)
        repo_path = Path(toplevel_proc.stdout.strip())
        repo_name = repo_path.name

        # Get current branch name
        branch_proc = subprocess.run(['git', 'branch', '--show-current'], capture_output=True, text=True, check=True)
        branch_name = branch_proc.stdout.strip()
        
        return f"[ Git: {branch_name} @ {repo_name}]"
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None

# --- ADK Integration ---
session_service = InMemorySessionService()

async def handle_basic_agent_run(runner: Runner, session_id: str, prompt: str):
    """Handles a run for the basic, conversational agent."""
    user_message = Content(role='user', parts=[Part(text=prompt)])
    final_response_started = False

    async for event in runner.run_async(user_id="cli_user", session_id=session_id, new_message=user_message):
        if not isinstance(event, Event): continue
        if event.error_message:
            rich_console.print(f"[bold #FF5555]Agent Error: {event.error_message}[/bold #FF5555]")
            continue
        if event.is_final_response():
            content = event.content
            if isinstance(content, Content) and content.parts:
                part = content.parts[0]
                if isinstance(part, Part) and part.text:
                    if not final_response_started:
                        rich_console.print("---")
                        final_response_started = True
                    rich_console.print(part.text, end="", style="#8BE9FD") # Light cyan for agent response
    rich_console.print()

async def handle_autonomous_task_run(prompt: str, approval: bool):
    """Handles a run for the autonomous task agent, with UI dashboard."""
    task_description = " ".join(prompt.split(' ')[1:])
    if not task_description:
        rich_console.print("[bold #FF5555]Error: No task description provided for @task.[/bold #FF5555]")
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

    rich_console.print(f"[bold #FF79C6]🚀 Starting autonomous task:[/bold #FF79C6] {task_description}")
    
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
    rich_console.print(Panel(final_report, title="[bold #50FA7B]✅ Final Summary[/bold #50FA7B]", border_style="#50FA7B"))
    rich_console.print("[bold #FF79C6]🏁 Autonomous task finished.[/bold #FF79C6]")


def get_prompt_message(cwd: str) -> FormattedText:
    """Builds the prompt with vaporwave styling."""
    home_dir = str(Path.home())
    display_cwd = "~" + cwd[len(home_dir):] if cwd.startswith(home_dir) else cwd
    
    return FormattedText([
        ('class:brand', '>'),
        ('class:space', ' '),
        ('class:path', display_cwd),
        ('class:space', ' '),
        ('class:cursor', '❯'),
        ('class:space', ' '),
    ])

async def start_interactive_session(args):
    """Main interactive loop that dispatches to the correct agent."""
    # --- Startup Sequence ---
    banners_dir = Path(__file__).parent / "banners"
    if banners_dir.is_dir():
        banner_files = list(banners_dir.glob("*.txt"))
        if banner_files:
            chosen_banner_path = random.choice(banner_files)
            with open(chosen_banner_path, 'r', encoding='utf-8') as f:
                banner_art = f.read()
                rich_console.print(apply_random_gradient(banner_art), justify="center")

    rich_console.print(Text("> G-CODER", style="bold #FF79C6", justify="center"))
    
    cap_manager = CapabilityManager()
    context_parts = []
    if cap_manager.is_lsp_supported:
        lsp_langs = ", ".join(sorted(list(cap_manager.supported_lsp_languages)))
        context_parts.append(f"[λ LSP: {lsp_langs}]")
    git_info = get_git_info()
    if git_info:
        context_parts.append(git_info)
    
    if context_parts:
        rich_console.print(Text(" ".join(context_parts), style="#BD93F9", justify="center"))

    rich_console.print(Text("Type '@task <description>' for autonomous mode or 'exit' to quit.", style="italic #61C7C7", justify="center"))
    rich_console.print()

    # --- ADK & Prompt Toolkit Setup ---
    basic_runner = Runner(
        agent=basic_agent.root_agent,
        app_name="gcoder_cli",
        session_service=session_service
    )
    
    session_id = str(uuid.uuid4())
    await session_service.create_session(
        app_name="gcoder_cli", user_id="cli_user", session_id=session_id,
        state={'cwd': os.getcwd(), 'human_in_the_loop': args.approval}
    )

    history_file = Path(os.path.expanduser("~/.gcoder/.session_history"))
    prompt_style = Style.from_dict({
        'brand': 'bold #FF79C6',      # Magenta for >
        'path': '#BD93F9',            # Lavender for path
        'cursor': 'bold #61C7C7',     # Cyan for ❯
        'space': '',
    })
    pt_session = PromptSession(history=FileHistory(str(history_file)), style=prompt_style)
    
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
            rich_console.print(f"\n[bold #FF5555]An unexpected error occurred: {e}[/bold #FF5555]")
            import traceback
            traceback.print_exc()

    rich_console.print("\n[bold #FFB86C]Exiting session.[/bold #FFB86C]")