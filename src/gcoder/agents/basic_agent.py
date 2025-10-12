# src/gcoder/agents/basic_agent.py

import os
import platform
import subprocess
from pathlib import Path
from typing import Optional, Dict, Any

from google.adk.agents import LlmAgent
from google.adk.models.lite_llm import LiteLlm
from google.adk.agents.callback_context import CallbackContext
from google.adk.models import LlmRequest, LlmResponse
from google.genai import types
from pydantic import BaseModel, Field



# Import tool modules
from gcoder.tools import file_tools, execution_tools
# Conditionally import code_tools
try:
    from gcoder.tools import code_tools
    _code_tools_available = True
except ImportError:
    _code_tools_available = False

# Import system helpers
from gcoder.system.callbacks import rich_before_tool_callback, rich_after_tool_callback
from gcoder.system.capability_manager import CapabilityManager
# Import the new config manager
from gcoder.config import config

# --- Dynamic Context Gathering Logic ---


class FinalAnswer(BaseModel):
    final_answer: str = Field(description="The final Answer of the user query/Question")


def _get_dir_listing(path: str) -> str:
    """Helper to get a directory listing."""
    try:
        if platform.system() != "Windows":
            # Use a more informative listing command on Unix-like systems
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
    # In a full implementation, you would also add git info here if desired
    return "\n".join(context_parts)

# --- ADK Callback for Dynamic Context Injection ---

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

# --- Dynamic Tool List Construction ---
cap_manager = CapabilityManager()

# Start with the base set of tools that are always available
ALL_TOOLS = [
    file_tools.read_file,
    file_tools.write_file,
    file_tools.edit_file,
    file_tools.find_file,
    file_tools.search_text,
    execution_tools.run_in_terminal,
    execution_tools.change_directory,
]

# Conditionally add the advanced code tools if LSP support is detected
if _code_tools_available and cap_manager.is_lsp_supported:
    print("[gcoder] LSP support detected. Enabling code intelligence tools.")
    ALL_TOOLS.extend([
        code_tools.inspect_file,
        code_tools.find_definition_reference
    ])
else:
    print("[gcoder] LSP support not detected. Code intelligence tools are disabled.")

# --- Load Instruction from File ---
def load_instruction() -> str:
    """Loads the main instruction prompt from the text file."""
    try:
        # Correctly resolve the path relative to this file's location
        prompt_path = Path(__file__).parent.parent / "prompts" / "basic_agent_instruction.txt"
        with open(prompt_path, 'r', encoding='utf-8') as f:
            return f.read()
    except FileNotFoundError:
        print("Warning: prompts/basic_agent_instruction.txt not found. Using a default instruction.")
        return "You are a helpful AI assistant."

# --- Agent Definition ---

# Get model configuration from the config file
ollama_host = config.get('ollama', 'host', fallback='http://localhost:11434')
model_name = config.get('ollama', 'model', fallback='qwen3-30-8:latest')

# Set the Ollama host as an environment variable for LiteLLM to pick up
os.environ['OLLAMA_API_BASE'] = ollama_host

root_agent = LlmAgent(
    name="GcoderBasicAgent",
    model=LiteLlm(model=f"ollama_chat/{model_name}"),
    description="An expert AI coding assistant that can read/write files and execute commands.",
    instruction=load_instruction(), # Load from file
    tools=ALL_TOOLS, # Use the dynamically constructed list
    before_model_callback=add_dynamic_context_callback,
    before_tool_callback=rich_before_tool_callback,
    after_tool_callback=rich_after_tool_callback,
#   output_schema=FinalAnswer, 
#   output_key="final_answer"
)