import os
import platform
import subprocess
import shlex
import signal
from pathlib import Path
from typing import Dict, Any, List

from google.adk.tools import ToolContext
from rich.prompt import Prompt

# --- Helper Function for Service Management ---

def _get_services_dir() -> Path:
    """Gets the path to the ~/.gcoder/services directory, creating it if it doesn't exist."""
    services_dir = Path.home() / ".gcoder" / "services"
    services_dir.mkdir(parents=True, exist_ok=True)
    return services_dir

# --- New Service Management Tools ---

def start_service(tool_context: ToolContext, command: str, service_name: str) -> Dict[str, Any]:
    """
    Starts a long-running command (like a web server) as a detached background service.
    This tool is NON-BLOCKING and returns control to the agent immediately.
    The service's output (stdout and stderr) is redirected to a log file.

    Args:
        command (str): The full command to execute (e.g., "npm start", "python app.py").
        service_name (str): A unique name to identify this service (e.g., "frontend_server").
    """
    if not command or not service_name:
        return {"status": "error", "message": "Both 'command' and 'service_name' are required."}

    state = tool_context.state
    if 'running_services' not in state:
        state['running_services'] = {}
    
    if service_name in state['running_services']:
        pid = state['running_services'][service_name].get('pid')
        return {"status": "error", "message": f"Service '{service_name}' is already running with PID {pid}. You must stop it first."}

    try:
        services_dir = _get_services_dir()
        log_path = services_dir / f"{service_name}.log"
        current_cwd = state.get('cwd', os.getcwd())

        # Use shlex.split for robust command parsing, especially on Linux/macOS
        cmd_args = shlex.split(command)

        with open(log_path, 'wb') as log_file:
            process = subprocess.Popen(
                cmd_args,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                cwd=current_cwd,
                # Create a new process group to manage the process and its children
                preexec_fn=os.setsid if platform.system() != "Windows" else None
            )

        state['running_services'][service_name] = {
            "pid": process.pid,
            "command": command,
            "log_path": str(log_path)
        }
        
        return {
            "status": "success", 
            "content": f"Service '{service_name}' started in the background with PID {process.pid}. Logs are at {log_path}"
        }
    except Exception as e:
        return {"status": "error", "message": f"Failed to start service '{service_name}': {e}"}

def check_service_status(tool_context: ToolContext, service_name: str) -> Dict[str, Any]:
    """
    Checks the status of a background service started with 'start_service'.
    It reports if the service is running and provides the last few lines of its log file.

    Args:
        service_name (str): The unique name of the service to check.
    """
    state = tool_context.state
    services = state.get('running_services', {})
    
    if service_name not in services:
        return {"status": "error", "message": f"Service '{service_name}' not found. Has it been started?"}

    service_info = services[service_name]
    pid = service_info.get('pid')
    log_path = service_info.get('log_path')
    is_running = False

    try:
        # Cross-platform check to see if the process exists
        if platform.system() == "Windows":
            # On Windows, check if the PID is in the tasklist
            result = subprocess.run(['tasklist', '/FI', f'PID eq {pid}'], capture_output=True, text=True)
            if str(pid) in result.stdout:
                is_running = True
        else:
            # On Linux/macOS, os.kill(pid, 0) checks for process existence without killing it
            os.kill(pid, 0)
            is_running = True
    except (ProcessLookupError, OSError):
        is_running = False

    log_snippet = ""
    try:
        if log_path and os.path.exists(log_path):
            with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
                lines = f.readlines()
                log_snippet = "".join(lines[-20:]) # Get the last 20 lines
    except Exception as e:
        log_snippet = f"Could not read log file: {e}"

    if not is_running:
        # If the process is no longer running, clean up the state
        del state['running_services'][service_name]
        status_message = "stopped"
    else:
        status_message = "running"
        
    return {
        "status": "success",
        "service_name": service_name,
        "service_status": status_message,
        "pid": pid if is_running else None,
        "log_snippet": log_snippet.strip()
    }

def stop_service(tool_context: ToolContext, service_name: str) -> Dict[str, Any]:
    """
    Stops a background service that was started with 'start_service'.

    Args:
        service_name (str): The unique name of the service to stop.
    """
    state = tool_context.state
    services = state.get('running_services', {})

    if service_name not in services:
        return {"status": "error", "message": f"Service '{service_name}' is not currently running or being managed."}

    pid = services[service_name].get('pid')
    try:
        if platform.system() == "Windows":
            subprocess.run(['taskkill', '/F', '/T', '/PID', str(pid)], check=True)
        else:
            # Send SIGTERM to the entire process group to terminate child processes
            os.killpg(os.getpgid(pid), signal.SIGTERM)
        
        # Clean up the state after stopping
        del state['running_services'][service_name]
        return {"status": "success", "content": f"Successfully stopped service '{service_name}' (PID: {pid})."}
    except (ProcessLookupError, OSError):
        # The process was already gone, so we just clean up the state
        del state['running_services'][service_name]
        return {"status": "success", "content": f"Service '{service_name}' (PID: {pid}) was already stopped. State has been cleaned up."}
    except Exception as e:
        return {"status": "error", "message": f"Error stopping service '{service_name}' (PID: {pid}): {e}"}

# --- Existing Tools (Retained for simple, blocking commands) ---

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
    """
    Executes a non-interactive shell command, waits for it to complete, and captures its output.
    This tool is BLOCKING and should be used for quick, one-off commands (e.g., 'ls', 'git status').
    For long-running servers, use 'start_service' instead.
    """
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