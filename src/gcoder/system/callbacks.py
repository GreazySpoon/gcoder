# src/gcoder/system/callbacks.py

from typing import Dict, Any, Optional

from google.adk.tools import ToolContext, BaseTool
from rich.console import Console
from rich.panel import Panel

console = Console()

def _get_start_message(tool_name: str, args: Dict[str, Any]) -> str:
    """Generates a human-readable message for a tool call."""
    path = args.get('path', '') or args.get('file_path', '')
    command = args.get('command', '')
    symbol = args.get('symbol', '')

    message_map = {
        'read_file': f"📄 Reading file [bold cyan]{path}[/bold cyan]",
        'write_file': f"💾 Writing to file [bold cyan]{path}[/bold cyan]",
        # ... (add other messages as needed)
    }
    return message_map.get(tool_name, f"Executing tool [bold]{tool_name}[/bold]")

def rich_before_tool_callback(
    tool: BaseTool, args: Dict[str, Any], tool_context: ToolContext
) -> Optional[Dict]:
    """ADK callback that prints a start message before a tool executes."""
    start_message = _get_start_message(tool.name, args)
    console.print(f"{start_message}...")
    return None

def rich_after_tool_callback(
    tool: BaseTool, args: Dict[str, Any], tool_response: Dict[str, Any], tool_context: ToolContext
) -> Optional[Dict]:
    """ADK callback that prints a status message and result after a tool executes."""
    start_message = _get_start_message(tool.name, args)
    
    # THE CORE FIX: Check the structured status field.
    is_error = isinstance(tool_response, dict) and tool_response.get("status") == "error"
    
    if is_error:
        console.print(f"❌ {start_message} [bold red]Failed.[/bold red]")
        error_message = tool_response.get("message", str(tool_response))
        console.print(Panel(error_message, title="[bold red]Tool Execution Error[/bold red]", border_style="red"))
    else:
        console.print(f"✅ {start_message} [bold green]Succeeded.[/bold green]")
        # Extract the content to display
        if isinstance(tool_response, dict) and "content" in tool_response:
             result_content = tool_response["content"]
             if tool.name not in ['change_directory']:
                 console.print(Panel(result_content, title=f"Output from [bold]{tool.name}[/bold]", border_style="dim blue", expand=False))
            
    return None