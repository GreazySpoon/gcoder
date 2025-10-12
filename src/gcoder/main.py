# src/gcoder/main.py

import sys
import argparse
import asyncio
import os
import uvicorn
from rich.console import Console

from gcoder.terminal import start_interactive_session
from gcoder.config import config

console = Console()

def setup_parser():
    """Sets up the argparse parser for the CLI."""
    parser = argparse.ArgumentParser(description="Gcoder: An AI agent for code and system tasks.")
    parser.add_argument('prompt', nargs='?', help="The prompt to run.")
    parser.add_argument('-i', '--interactive', action='store_true', help="Start an interactive session (default action).")
    parser.add_argument('-a', '--approval', action='store_true', help="Require human approval for sensitive commands.")
    parser.add_argument('--task', action='store_true', help="Run the given prompt in autonomous task mode and exit.")
    
    api_group = parser.add_argument_group('API Server')
    api_group.add_argument('--api', nargs='?', const=8844, type=int, metavar='PORT', help="Start the FastAPI server.")
    
    return parser

async def run_single_autonomous_task(prompt: str, approval: bool):
    """Initializes and runs a single autonomous task from the CLI and exits."""
    # This imports the handle_autonomous_task_run function from terminal.py
    # We are reusing the same logic for both interactive and single-shot task runs.
    from gcoder.terminal import handle_autonomous_task_run
    await handle_autonomous_task_run(f"@task {prompt}", approval)

def main():
    """Synchronous entry point for the Gcoder CLI."""
    parser = setup_parser()
    args = parser.parse_args()

    os.environ['OLLAMA_API_BASE'] = config.get('ollama', 'host')

    try:
        if args.api is not None:
            # This logic remains the same
            uvicorn.run("gcoder.api.app:app", host="127.0.0.1", port=args.api, log_level="info")
        
        elif args.task:
            if not args.prompt:
                console.print("[bold red]Error: A prompt is required for --task mode.[/bold red]")
                sys.exit(1)
            # THE CORE FIX: Call the dedicated function for single-shot autonomous tasks
            asyncio.run(run_single_autonomous_task(args.prompt, args.approval))

        else: # Default to interactive mode
            asyncio.run(start_interactive_session(args))

    except KeyboardInterrupt:
        console.print("\n[bold yellow]Exiting.[/bold yellow]")

if __name__ == "__main__":
    main()