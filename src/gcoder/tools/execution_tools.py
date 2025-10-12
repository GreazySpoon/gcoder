# src/gcoder/tools/execution_tools.py

import os
import platform
import subprocess
from typing import Dict, Any
from google.adk.tools import ToolContext
from rich.prompt import Prompt

def change_directory(tool_context: ToolContext, path: str) -> Dict[str, Any]:
    """Changes the agent's current working directory to a new path."""
    try:
        target_path = os.path.expanduser(path)
        os.chdir(target_path)
        new_cwd = os.getcwd()
        tool_context.state['cwd'] = new_cwd
        return {"status": "success", "content": f"Successfully changed directory to: {new_cwd}"}
    except FileNotFoundError:
        return {"status": "error", "message": f"The directory '{path}' does not exist."}
    except NotADirectoryError:
        return {"status": "error", "message": f"The path '{path}' is not a directory."}
    except Exception as e:
        return {"status": "error", "message": f"An unexpected error occurred: {e}"}

def run_in_terminal(tool_context: ToolContext, command: str) -> Dict[str, Any]:
    """Executes a non-interactive shell command and captures its output."""
    current_cwd = tool_context.state.get('cwd', os.getcwd())
    
    if 'sudo' in command and tool_context.state.get('human_in_the_loop', False):
         if Prompt.ask(f"Approve command: [yellow]`{command}`[/yellow] ? [y/n]", default="n").lower() != "y":
             return {"status": "error", "message": "User denied execution of sudo command."}

    try:
        result = subprocess.run(
            command, shell=True, capture_output=True, text=True, timeout=120,
            encoding='utf-8', errors='ignore', cwd=current_cwd
        )
        output = f"Exit Code: {result.returncode}\n"
        if result.stdout:
            output += f"--- STDOUT ---\n{result.stdout.strip()}\n"
        if result.stderr:
            output += f"--- STDERR ---\n{result.stderr.strip()}\n"
        
        content = output if output.strip() else f"Exit Code: {result.returncode}\n--- STDOUT ---\n(No output)"
        return {"status": "success", "content": content}
    except subprocess.TimeoutExpired:
        return {"status": "error", "message": "Command timed out after 120 seconds."}
    except Exception as e:
        return {"status": "error", "message": f"Error executing command: {e}"}