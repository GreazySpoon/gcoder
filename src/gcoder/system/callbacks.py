# src/gcoder/system/callbacks.py
from typing import Dict, Any, Optional

from google.adk.tools import ToolContext, BaseTool
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

console = Console()

def rich_before_tool_callback(
    tool: BaseTool, args: Dict[str, Any], tool_context: ToolContext
) -> Optional[Dict]:
    """ADK callback that prints a start message before a tool executes."""
    
    # Create a Rich Text object for fancy formatting
    text = Text.from_markup(f"[#F9E2AF]⚡ [/][#00A7A7]Executing tool [/][bold #FF79C6]{tool.name}[/bold #FF79C6]...")
    
    console.print(text)
    return None

def rich_after_tool_callback(
    tool: BaseTool, args: Dict[str, Any], tool_response: Dict[str, Any], tool_context: ToolContext
) -> Optional[Dict]:
    """ADK callback that prints a status message and result after a tool executes."""
    is_error = isinstance(tool_response, dict) and tool_response.get("status") == "error"
    
    if is_error:
        error_message = tool_response.get("message", str(tool_response))
        console.print(Panel(error_message, title=f"[bold #FF5555]❌ Error in {tool.name}[/bold #FF5555]", border_style="#FF5555"))
    else:
        if isinstance(tool_response, dict) and "content" in tool_response:
             result_content = tool_response["content"]
             if tool.name not in ['change_directory']:
                 # Panel with a pastel purple border and cyan title
                 console.print(Panel(result_content, title=f"[bold #61C7C7]Output from {tool.name}[/bold #61C7C7]", border_style="#BD93F9", expand=False))
            
    return None