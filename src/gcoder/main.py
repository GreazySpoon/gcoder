# src/gcoder/main.py

import sys
import argparse
import asyncio
import os
import uvicorn
from rich.console import Console

from gcoder.terminal import start_interactive_session

console = Console()

def setup_parser():
    """Sets up the argparse parser for the CLI."""
    parser = argparse.ArgumentParser(description="Gcoder: An AI agent for code and system tasks.")
    parser.add_argument('prompt', nargs='?', help="The prompt to run in single-shot mode (experimental).")
    parser.add_argument('-i', '--interactive', action='store_true', help="Start an interactive session (default action).")
    parser.add_argument('-a', '--approval', action='store_true', help="Require human approval for sensitive commands in the CLI.")
    
    api_group = parser.add_argument_group('API Server')
    api_group.add_argument('--api', nargs='?', const=8844, type=int, metavar='PORT', help="Start the FastAPI server on a given port (default: 8844).")
    
    return parser

def main():
    """Synchronous entry point that orchestrates the async main logic."""
    parser = setup_parser()
    args = parser.parse_args()

    os.environ['OLLAMA_API_BASE'] = 'http://10.10.60.28:11434'

    try:
        if args.api is not None:
            console.print(f"[bold green]🚀 Starting Gcoder API server on http://127.0.0.1:{args.api}[/bold green]")
            console.print("[dim]Press Ctrl+C to shut down.[/dim]")
            uvicorn.run("gcoder.api.app:app", host="127.0.0.1", port=args.api, log_level="info")
        
        # Default to interactive session if --api is not specified
        else:
            asyncio.run(start_interactive_session(args))

    except KeyboardInterrupt:
        console.print("\n[bold yellow]Exiting.[/bold yellow]")

if __name__ == "__main__":
    main()