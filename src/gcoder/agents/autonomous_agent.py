# src/gcoder/agents/autonomous_agent.py

import os

from google.adk.models.lite_llm import LiteLlm
from google.adk.agents import LlmAgent
from google.adk.tools import FunctionTool

# Import the correct pattern builder
from gcoder.patterns.autovibe import create_autovibe_workflow

# Import tool modules and system helpers
from gcoder.tools import file_tools, execution_tools, code_tools
from gcoder.tools.thinking_tools import ALL_THINKING_TOOLS
from gcoder.tools.orchestration_tools import create_delegate_task_tool, create_report_back_tool
from gcoder.system.capability_manager import CapabilityManager
from gcoder.config import config
from gcoder.system.callbacks import rich_before_tool_callback, rich_after_tool_callback

# --- Configuration ---
os.environ['OLLAMA_API_BASE'] = config.get('ollama', 'host')
AUTONOMOUS_MODEL_NAME = config.get('ollama', 'autonomous_model', fallback='qwencoder-6:latest')
MODEL_CONFIG = LiteLlm(model=f"ollama_chat/{AUTONOMOUS_MODEL_NAME}")
NAMESPACE = "gcoder_task"
CODER_REPORT_KEY = f"{NAMESPACE}:coder_report"

# --- Tool Factories Instantiation ---
PLANNER_NAME = "PlannerAgent"
delegate_tool = create_delegate_task_tool(namespace=NAMESPACE)
report_tool = create_report_back_tool(coordinator_name=PLANNER_NAME, namespace=NAMESPACE)

# --- Toolset for the Coder Agent ---
cap_manager = CapabilityManager()
CODER_TOOLS = [
    file_tools.read_file, file_tools.write_file, file_tools.edit_file,
   # file_tools.find_file, file_tools.search_text,
    execution_tools.run_in_terminal, execution_tools.change_directory,
]
if cap_manager.is_lsp_supported:
    CODER_TOOLS.extend([
        code_tools.inspect_file,
        code_tools.find_definition,
        #code_tools.get_definition_code,
        code_tools.find_references
    ])
CODER_TOOLS.extend(ALL_THINKING_TOOLS)

def get_tool_name(tool):
    return getattr(tool, 'name', getattr(tool, '__name__', 'unknown_tool'))

CODER_TOOL_NAMES_STR = ", ".join([f"`{get_tool_name(tool)}`" for tool in CODER_TOOLS])

# --- Agent Instructions ---

PLANNER_INSTRUCTION = f"""You are the Planner, a project manager. Your job is to achieve the user's goal by delegating single, clear steps to a Coder agent.

**CONTEXT:**
- User's Goal: `{{original_task}}`
- Coder's Last Report: `{{{NAMESPACE}:last_report?}}`

**YOUR WORKFLOW:**
1.  Analyze the context. Decide the single next action.
2.  **IMMEDIATELY ACT:**
    - If the goal is not complete, you MUST use the `delegate_task` tool to assign the next step to the `CoderAgentWorkflow`.
    - If the goal is complete, you MUST respond directly to the user with a final summary.
"""

CODER_INSTRUCTION = f"""You are the Coder, an execution agent.
You MUST fully complete the single instruction you are given. This may require using multiple tools in a sequence.

**YOUR ASSIGNED TASK is in the `{{{NAMESPACE}:current_task}}` state variable.**

**YOUR ONLY GOAL:**
1.  Understand your assigned task.
2.  Use your tools to complete it.
3.  Your final output MUST be a concise, factual report of what you did. This is your only output.
"""

# --- Agent Definitions ---

CoderAgent = LlmAgent(
    name="CoderAgent",
    model=MODEL_CONFIG,
    tools=CODER_TOOLS,
    output_key=CODER_REPORT_KEY, # This is where the Coder's report is saved
    instruction=CODER_INSTRUCTION,
    before_tool_callback=rich_before_tool_callback,
    after_tool_callback=rich_after_tool_callback,
)

# --- Construct the Final Root Agent ---
root_agent = create_autovibe_workflow(
    model=MODEL_CONFIG,
    planner_instruction=PLANNER_INSTRUCTION,
    coder_agent=CoderAgent, # Pass the fully configured Coder agent
    delegate_tool=delegate_tool,
    report_tool=report_tool,
    thinking_tools=ALL_THINKING_TOOLS,
    before_tool_callback=rich_before_tool_callback,
    after_tool_callback=rich_after_tool_callback,
)