import os
import platform
import subprocess
from pathlib import Path
from typing import Optional, Dict, Any
import platform

from google.adk.agents import LlmAgent
from google.adk.planners import BuiltInPlanner
from google.adk.agents.callback_context import CallbackContext
from google.adk.models import LlmRequest, LlmResponse
from google.genai import types
from pydantic import BaseModel, Field

from gcoder.tools import file_tools, execution_tools
try:
    from gcoder.tools import code_tools
    _code_tools_available = True
except ImportError:
    _code_tools_available = False

from gcoder.system.callbacks import rich_before_tool_callback, rich_after_tool_callback
from gcoder.system.capability_manager import CapabilityManager
from gcoder.model_factory import get_model_instance
from gcoder.config import config


class FinalAnswer(BaseModel):
    final_answer: str = Field(description="The final Answer of the user query/Question")


def _get_dir_listing(path: str) -> str:
    """Helper to get a directory listing."""
    try:
        if platform.system() != "Windows":
            result = subprocess.run(['ls', '-F', path], capture_output=True, text=True, timeout=2)
            return result.stdout.strip()
        else:
            return "\n".join(os.listdir(path))
    except Exception:
        return "Could not list directory contents."

def gather_full_context(cwd: str) -> str:
    """Gathers environmental context and formats it as a string for the prompt."""
    context_parts = [
        f"Operating System: {platform.system()}",
        f"Current Directory: {cwd}",
        "--- Directory Listing ---",
        _get_dir_listing(cwd)
    ]
    return "\n".join(context_parts)


def add_dynamic_context_callback(
    callback_context: CallbackContext, llm_request: LlmRequest
) -> Optional[LlmResponse]:
    """
    This callback runs before each model call to inject fresh environmental context.
    """
    base_instruction = ""
    instruction_obj = llm_request.config.system_instruction
    if isinstance(instruction_obj, types.Content) and instruction_obj.parts:
        base_instruction = instruction_obj.parts[0].text or ""
    elif isinstance(instruction_obj, str):
        base_instruction = instruction_obj

    cwd = callback_context.state.get('cwd', os.getcwd())
    dynamic_context_str = gather_full_context(cwd)
    
    context_header = "\n\n--- Current System Context ---\n"
    full_instruction = base_instruction + context_header + dynamic_context_str
    
    llm_request.config.system_instruction = types.Content(
        parts=[types.Part(text=full_instruction)]
    )
    return None

# --- Feature Flags ---
ENABLE_THINKING = config.getboolean('model_features', 'think')
ENABLE_VISION = config.getboolean('model_features', 'vision')

# --- Dynamic Tool List Construction ---
cap_manager = CapabilityManager()
ALL_TOOLS = [
    file_tools.read_file,
    file_tools.write_file,
    file_tools.edit_file,
    file_tools.find_file,
    file_tools.search_text,
    execution_tools.run_in_terminal,
    execution_tools.change_directory,
    execution_tools.stop_service,
    execution_tools.check_service_status,
    execution_tools.start_service,
]

if _code_tools_available and cap_manager.is_lsp_supported:
    print("[gcoder] LSP support detected. Enabling code intelligence tools.")
    ALL_TOOLS.extend([
        code_tools.inspect_file,
        code_tools.find_definition,
        code_tools.get_definition_code,
        code_tools.find_references
    ])
else:
    print("[gcoder] LSP support not detected. Code intelligence tools are disabled.")

if ENABLE_VISION:
    print("[gcoder] Vision is enabled. Adding vision tools.")
    from gcoder.tools.vision_tools import ALL_VISION_TOOLS
    from gcoder.tools.browser_tools import ALL_BROWSER_TOOLS
    ALL_TOOLS.extend(ALL_VISION_TOOLS)
    ALL_TOOLS.extend(ALL_BROWSER_TOOLS)

# --- Dynamic Instruction Loading ---
def load_instruction() -> str:
    """Loads instruction prompts from text files."""
    instruction_parts = []
    prompts_dir = Path(__file__).parent.parent / "prompts"
    
    # Always load the base instruction
    try:
        with open(prompts_dir / "basic_agent_instruction.txt", 'r', encoding='utf-8') as f:
            instruction_parts.append(f.read())
    except FileNotFoundError:
        print("Warning: prompts/basic_agent_instruction.txt not found. Using a default instruction.")
        return "You are a helpful AI assistant."

    # Append vision instructions if enabled
    if ENABLE_VISION:
        try:
            with open(prompts_dir / "vision_instructions.txt", 'r', encoding='utf-8') as f:
                instruction_parts.append(f.read())
        except FileNotFoundError:
            print("Warning: prompts/vision_instructions.txt not found, but vision is enabled.")

    base_instruction = "\n\n".join(instruction_parts)
    
    # Add the crucial context for the AI
    os_context = f"\n--- System Information ---\nOperating System: {platform.system()}. When using shell, You MUST use commands compatible with this OS."
    
    return base_instruction + os_context


# --- Agent Definition ---
agent_kwargs: Dict[str, Any] = {
    "name": "GcoderBasicAgent",
    "model": get_model_instance('basic'),
    "description": "An expert AI coding assistant that can read/write files and execute commands.",
    "instruction": load_instruction(),
    "tools": ALL_TOOLS,
    "before_model_callback": add_dynamic_context_callback,
    "before_tool_callback": rich_before_tool_callback,
    "after_tool_callback": rich_after_tool_callback,
}

if ENABLE_THINKING:
    print("[gcoder] Thinking is enabled.")
    agent_kwargs["planner"] = BuiltInPlanner(
        thinking_config=types.ThinkingConfig(include_thoughts=True)
    )

root_agent = LlmAgent(**agent_kwargs)