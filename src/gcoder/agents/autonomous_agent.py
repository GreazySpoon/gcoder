# src/gcoder/agents/autonomous_agent.py

import os

from google.adk.models.lite_llm import LiteLlm
from google.adk.agents import LlmAgent

# Import the correct pattern builder
from gcoder.patterns.autovibe import create_autovibe_workflow

# Import tool modules and system helpers
from gcoder.tools import file_tools, execution_tools, code_tools
from gcoder.tools.thinking_tools import ALL_THINKING_TOOLS
from gcoder.system.capability_manager import CapabilityManager
from gcoder.config import config
from gcoder.system.callbacks import rich_before_tool_callback, rich_after_tool_callback

# --- Configuration ---
os.environ['OLLAMA_API_BASE'] = config.get('ollama', 'host')
AUTONOMOUS_MODEL_NAME = config.get('ollama', 'autonomous_model', fallback='qwencoder-6:latest')
MODEL_CONFIG = LiteLlm(model=f"ollama_chat/{AUTONOMOUS_MODEL_NAME}")

# --- Toolset for the Coder Agent ---
cap_manager = CapabilityManager()
CODER_TOOLS = [
    file_tools.read_file, file_tools.write_file, file_tools.edit_file,
    file_tools.find_file, file_tools.search_text,
    execution_tools.run_in_terminal, execution_tools.change_directory,
]
if cap_manager.is_lsp_supported:
    CODER_TOOLS.extend([code_tools.inspect_file, code_tools.find_definition_reference])
CODER_TOOLS.extend(ALL_THINKING_TOOLS)

def get_tool_name(tool):
    return getattr(tool, 'name', getattr(tool, '__name__', 'unknown_tool'))

CODER_TOOL_NAMES_STR = ", ".join([f"`{get_tool_name(tool)}`" for tool in CODER_TOOLS])

# --- Instructions for the Agents (Direct and Forceful) ---

PLANNER_INSTRUCTION = f"""You are the Planner, a project manager. Your job is to achieve the user's goal by delegating single, clear steps to a Coder agent.

**CONTEXT:**
- User's Goal: `{{original_task}}`
- Coder's Last Report: `{{coder_report?}}`

**YOUR TASK:**
1.  Analyze the context.
2.  Decide the single next action required.
3.  **IMMEDIATELY ACT:**
    - If the goal is not complete, you MUST use the `delegate_to_coder` tool to assign the next step.
    - If the goal is complete, you MUST respond directly to the user with a final summary.
"""

CODER_INSTRUCTION = f"""You are the Coder, an execution agent.
You MUST fully complete the single instruction you are given. This may require using multiple tools in a sequence.

**YOUR ASSIGNED TASK is in the `{{coder_instruction}}` state variable.**

**YOUR ONLY GOAL:**
1.  Understand your assigned task.
2.  Use your tools to complete it.
3.  Your final output MUST be a concise, factual report of what you did.
"""

# --- Construct the Final Root Agent using the Autovibe Pattern ---

# Create the workflow by calling the factory function from the pattern file.
root_agent = create_autovibe_workflow(
    model=MODEL_CONFIG,
    coder_tools=CODER_TOOLS,
    planner_instruction=PLANNER_INSTRUCTION,
    coder_instruction=CODER_INSTRUCTION,
    before_tool_callback=rich_before_tool_callback,
    after_tool_callback=rich_after_tool_callback
)

# Manually add the thinking tools to the Planner after creation.
# The factory only adds the delegate tool.
root_agent.tools.extend(ALL_THINKING_TOOLS)