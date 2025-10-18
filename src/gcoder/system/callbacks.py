# src/gcoder/system/callbacks.py

import json
from typing import Dict, Any, Optional

from google.adk.tools import ToolContext, BaseTool
from rich.console import Console, Group
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Prompt
from rich.syntax import Syntax
from rich.text import Text

console = Console()

SENSITIVE_TOOLS = {
    'write_file',
    'edit_file',
    'run_in_terminal',
    'start_service',
    'stop_service'
}

def _get_output_panel_title(tool_name: str) -> str:
    """Gets a user-friendly title for the output panel."""
    title_map = {
        'run_in_terminal': "💻 Terminal Output",
        'find_file': "🔎 Search Results",
        'search_text': "🔍 Search Results",
        'find_definition': "🧠 Definition Found",
        'find_references': "🔗 References Found",
        'inspect_file': "🔬 Inspection Results",
        'browser_action': "🌐 Browser State"
    }
    return title_map.get(tool_name, "✅ Output")

def _ask_for_user_approval_and_feedback(
    tool: BaseTool, args: Dict[str, Any]
) -> Optional[Dict]:
    """Prompts the user for approval for a sensitive tool and processes their feedback."""
    prompt_text = (
        "\n> Approve? [bold green](y)es-ok[/bold green], [bold red](n)o[/bold red], "
        "or [bold yellow]provide feedback[/bold yellow] to deny and correct"
    )
    user_input = Prompt.ask(prompt_text)
    cleaned_input = user_input.strip()
    
    if not cleaned_input:
        second_prompt_text = "> Press [bold green]Enter again to confirm[/bold green], or provide feedback"
        second_input = Prompt.ask(second_prompt_text)
        if not second_input.strip():
            cleaned_input = 'y'
        else:
            cleaned_input = second_input.strip()

    if cleaned_input.lower() in ['y', 'yes', 'ok']:
        console.print("[bold green]✅ Approved by user. Proceeding...[/bold green]")
        return None
    elif cleaned_input.lower() in ['n', 'no']:
        console.print("[bold red]❌ Denied by user. Stopping tool.[/bold red]")
        return {"status": "error", "message": "User explicitly denied the execution of this tool."}
    else:
        console.print("[bold yellow]📝 Feedback received. Denying and sending feedback to agent...[/bold yellow]")
        return {
            "status": "user_feedback",
            "content": f"User denied the action, providing new instructions: '{cleaned_input}'"
        }

def _create_tool_plan_panel(tool_name: str, args: Dict[str, Any]) -> Panel:
    """Creates a consistent, rich panel for any tool call."""
    
    title = f"Executing [bold]{tool_name}[/bold]"
    content = ""
    border_style = "#61C7C7" # Default cyan

    if tool_name == 'write_file':
        path = args.get('path', 'unknown file')
        content = args.get('content', '')
        title = f"💾 Writing to [bold #FF79C6]{path}[/bold #FF79C6]"
        return Panel(Markdown(f"```\n{content}\n```", style="code"), title=title, border_style="#FFB86C", title_align="left")
    
    elif tool_name == 'edit_file':
        path = args.get('path', 'unknown file')
        start = args.get('start_line', '?')
        end = args.get('end_line', '?')
        new_content = args.get('new_content', '')
        title = f"✍️ Editing [bold #FF79C6]{path}[/bold #FF79C6]"
        description = Text(f"Replacing lines {start}-{end} with:\n")
        content_group = Group(description, Markdown(f"```\n{new_content}\n```", style="code"))
        return Panel(content_group, title=title, border_style="#FFB86C", title_align="left")

    elif tool_name == 'run_in_terminal':
        command = args.get('command', '')
        title = "💻 Executing command"
        return Panel(Syntax(command, "bash", theme="dracula", background_color="default"), title=title, border_style=border_style, title_align="left")

    elif tool_name == 'browser_action':
        action = args.get('action', 'UNKNOWN').upper()
        if action == 'GOTO': content = f"Navigating to [bold #61C7C7]{args.get('url', '...')}[/]"
        elif action == 'CLICK': content = f"Clicking element [bold #FF79C6]ID {args.get('element_id', '?')}[/]"
        elif action == 'TYPE': content = f"Typing into element [bold #FF79C6]ID {args.get('element_id', '?')}[/]"
        elif action == 'SCROLL': content = f"Scrolling [bold #FFB86C]{args.get('scroll_direction', 'down')}[/]"
        else: content = f"Performing browser action: [bold #61C7C7]{action}[/]"
        title = f"🌐 Browser: {action}"

    else: # Default for all other tools
        # Create a simple list of arguments
        args_str = "\n".join([f"- {key}: {value}" for key, value in args.items()])
        title_map = {
            'read_file': "📄 Reading File", 'find_file': "🔎 Finding File",
            'search_text': "🔍 Searching Text", 'change_directory': "📁 Changing Directory",
            'start_service': "🚀 Starting Service", 'stop_service': "🛑 Stopping Service",
            'check_service_status': "📊 Checking Service Status",
        }
        title = title_map.get(tool_name, f"⚡ Tool: {tool_name}")
        content = Text(args_str)

    return Panel(content, title=f"[bold]{title}[/bold]", border_style=border_style, title_align="left")


def rich_before_tool_callback(
    tool: BaseTool, args: Dict[str, Any], tool_context: ToolContext
) -> Optional[Dict]:
    """ADK callback that displays a normalized panel for all tool calls and handles approval."""
    
    if tool.name == 'think_tool':
        console.print()
        console.print(Text.from_markup("🤔 Thinking..."))
        return None

    console.print() # Add spacing before the tool panel
    
    # Create and display the plan for EVERY tool call to be consistent
    plan_panel = _create_tool_plan_panel(tool.name, args)
    console.print(plan_panel)

    # Now, check for approval if needed
    is_hitl_enabled = tool_context.state.get('human_in_the_loop', False)
    if tool.name in SENSITIVE_TOOLS and is_hitl_enabled:
        override_response = _ask_for_user_approval_and_feedback(tool, args)
        if override_response is not None:
            return override_response
            
    return None

def rich_after_tool_callback(
    tool: BaseTool, args: Dict[str, Any], tool_response: Dict[str, Any], tool_context: ToolContext
) -> Optional[Dict]:
    """ADK callback that prints a rich status or result after a tool executes."""

    if tool.name == 'think_tool':
        return None

    is_error = isinstance(tool_response, dict) and tool_response.get("status") == "error"
    
    if is_error:
        error_message = tool_response.get("message", str(tool_response))
        console.print(Panel(error_message, title="[bold #FF5555]❌ Error[/bold #FF5555]", border_style="#FF5555", title_align="left"))
    else:
        # Simple, one-line success messages for actions that don't have visual output
        if tool.name in ['write_file', 'edit_file', 'change_directory', 'start_service', 'stop_service'] and tool_response.get("content"):
            console.print(Text(f"✅ {tool_response['content']}", style="green"))
        
        # A result panel for tools that return significant output
        elif tool.name in ['run_in_terminal', 'find_file', 'search_text', 'check_service_status', 'find_definition', 'find_references', 'inspect_file', 'browser_action', 'read_file']:
            content = tool_response.get("content") or tool_response.get("message")
            if content and str(content).strip():
                panel_title = _get_output_panel_title(tool.name)
                console.print(Panel(str(content), title=f"[bold #61C7C7]{panel_title}[/bold #61C7C7]", border_style="#BD93F9", expand=False, title_align="left"))
    
    console.print() # Add spacing after the tool result
    return None