import os
from typing import Dict, Any

from google.adk.agents import LlmAgent
from google.adk.planners import BuiltInPlanner
from google.adk.tools import FunctionTool
from google.genai import types

from gcoder.patterns.autovibe import create_autovibe_workflow
from gcoder.tools import file_tools, execution_tools, code_tools
from gcoder.tools.thinking_tools import ALL_THINKING_TOOLS
from gcoder.tools.orchestration_tools import create_delegate_task_tool, create_report_back_tool
from gcoder.system.capability_manager import CapabilityManager
from gcoder.system.callbacks import rich_before_tool_callback, rich_after_tool_callback
from gcoder.model_factory import get_model_instance
from gcoder.config import config

# --- Feature Flags ---
ENABLE_THINKING = config.getboolean('model_features', 'think')
ENABLE_VISION = config.getboolean('model_features', 'vision')

# --- Configuration ---
MODEL_CONFIG = get_model_instance('autonomous')
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
    execution_tools.run_in_terminal, execution_tools.change_directory,
]
if cap_manager.is_lsp_supported:
    CODER_TOOLS.extend([
        code_tools.inspect_file,
        code_tools.find_definition,
        code_tools.find_references
    ])
CODER_TOOLS.extend(ALL_THINKING_TOOLS)

if ENABLE_VISION:
    print("[gcoder] Vision is enabled for autonomous agent. Adding vision tools to Coder.")
    from gcoder.tools.vision_tools import ALL_VISION_TOOLS
    CODER_TOOLS.extend(ALL_VISION_TOOLS)


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
coder_agent_kwargs: Dict[str, Any] = {
    "name": "CoderAgent",
    "model": MODEL_CONFIG,
    "tools": CODER_TOOLS,
    "output_key": CODER_REPORT_KEY,
    "instruction": CODER_INSTRUCTION,
    "before_tool_callback": rich_before_tool_callback,
    "after_tool_callback": rich_after_tool_callback,
}

autovibe_kwargs: Dict[str, Any] = {
    "model": MODEL_CONFIG,
    "planner_instruction": PLANNER_INSTRUCTION,
    "delegate_tool": delegate_tool,
    "report_tool": report_tool,
    "thinking_tools": ALL_THINKING_TOOLS,
    "before_tool_callback": rich_before_tool_callback,
    "after_tool_callback": rich_after_tool_callback,
}

if ENABLE_THINKING:
    print("[gcoder] Thinking is enabled for autonomous agent.")
    planner = BuiltInPlanner(thinking_config=types.ThinkingConfig(include_thoughts=True))
    coder_agent_kwargs["planner"] = planner
    autovibe_kwargs["planner"] = planner


CoderAgent = LlmAgent(**coder_agent_kwargs)
autovibe_kwargs["coder_agent"] = CoderAgent

# --- Construct the Final Root Agent ---
root_agent = create_autovibe_workflow(**autovibe_kwargs)