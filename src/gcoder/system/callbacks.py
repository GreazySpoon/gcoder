# src/gcoder/system/callbacks.py
from typing import Dict, Any, Optional, Tuple

from google.adk.tools import ToolContext, BaseTool
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

console = Console()

def _get_tool_display_info(tool_name: str, args: Dict[str, Any]) -> Tuple[str, bool]:
    """
    Generates a user-friendly message for a tool call and determines if its output should be shown.

    Returns:
        A tuple containing (display_message, should_show_output_panel).
    """
    # Default behavior for any tool not explicitly handled
    display_message = f"Executing tool [bold]{tool_name}[/bold]"
    show_output = True

    # --- Tool-Specific Customizations ---

    # -- File Tools --
    if tool_name == 'read_file':
        path = args.get('path', 'unknown file')
        start = args.get('start_line')
        end = args.get('end_line')
        if start and end:
            display_message = f"📄 Reading file [bold #FF79C6]{path}[/bold #FF79C6] from line {start} to {end}"
        else:
            display_message = f"📄 Reading file [bold #FF79C6]{path}[/bold #FF79C6]"
        show_output = False
    
    elif tool_name == 'write_file':
        path = args.get('path', 'unknown file')
        display_message = f"💾 Writing to file [bold #FF79C6]{path}[/bold #FF79C6]"

    elif tool_name == 'edit_file':
        path = args.get('path', 'unknown file')
        display_message = f"✍️ Editing file [bold #FF79C6]{path}[/bold #FF79C6]"

    elif tool_name == 'find_file':
        filename = args.get('filename', '...')
        display_message = f"🔎 Finding file [bold #61C7C7]`{filename}`[/bold #61C7C7]"

    elif tool_name == 'search_text':
        term = args.get('search_term', '...')
        display_message = f"🔍 Searching for text [bold #61C7C7]'{term}'[/bold #61C7C7]"

    # -- Execution Tools --
    elif tool_name == 'run_in_terminal':
        command = args.get('command', '')
        display_message = f"Executing command: [bold #61C7C7]`{command}`[/bold #61C7C7]"

    elif tool_name == 'change_directory':
        path = args.get('path', '...')
        display_message = f" cd Changing directory to [bold #FF79C6]{path}[/bold #FF79C6]"
        show_output = False # The prompt will update, no need for a panel

    # -- Code (LSP) Tools --
    elif tool_name == 'find_definition':
        symbol = args.get('symbol', '...')
        display_message = f"🧠 Finding definition for [bold #61C7C7]`{symbol}`[/bold #61C7C7]"
    
    elif tool_name == 'get_definition_code':
        path = args.get('file_path', '...')
        display_message = f"📄 Getting code from [bold #FF79C6]{path}[/bold #FF79C6]"

    elif tool_name == 'find_references':
        path = args.get('file_path', '...')
        display_message = f"🔗 Finding references in [bold #FF79C6]{path}[/bold #FF79C6]"

    elif tool_name == 'inspect_file':
        path = args.get('file_path', '...')
        display_message = f"🔬 Inspecting file [bold #FF79C6]{path}[/bold #FF79C6]"

    # -- Vision Tools --
    elif tool_name == 'load_image_from_path':
        path = args.get('image_path', 'unknown media')
        display_message = f"🖼️ Reading Media [bold #FF79C6]{path}[/bold #FF79C6]"
        show_output = False

    # -- Thinking Tools --
    elif tool_name == 'think_tool':
        display_message = "🤔 Thinking"
        show_output = False

    return display_message, show_output

def rich_before_tool_callback(
    tool: BaseTool, args: Dict[str, Any], tool_context: ToolContext
) -> Optional[Dict]:
    """ADK callback that prints a customized start message before a tool executes."""
    
    if tool.name == 'think_tool':
        console.print(Text.from_markup("🤔 Thinking..."))
        return None

    display_message, _ = _get_tool_display_info(tool.name, args)
    
    text = Text.from_markup(f"[#F9E2AF]⚡ [/][#00A7A7]{display_message}[/][#00A7A7]...[/]")
    console.print(text)
    
    return None

def rich_after_tool_callback(
    tool: BaseTool, args: Dict[str, Any], tool_response: Dict[str, Any], tool_context: ToolContext
) -> Optional[Dict]:
    """ADK callback that prints a status message and conditionally shows results."""

    if tool.name == 'think_tool':
        return None

    _, should_show_output = _get_tool_display_info(tool.name, args)
    is_error = isinstance(tool_response, dict) and tool_response.get("status") == "error"
    
    if is_error:
        error_message = tool_response.get("message", str(tool_response))
        console.print(Panel(error_message, title=f"[bold #FF5555]❌ Error in {tool.name}[/bold #FF5555]", border_style="#FF5555"))
    else:
        if should_show_output and isinstance(tool_response, dict) and "content" in tool_response:
             result_content = tool_response.get("content")
             if result_content and str(result_content).strip():
                 console.print(Panel(result_content, title=f"[bold #61C7C7]Output from {tool.name}[/bold #61C7C7]", border_style="#BD93F9", expand=False))
            
    return None