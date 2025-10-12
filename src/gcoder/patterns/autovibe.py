# src/gcoder/patterns/autovibe.py

from typing import List, Callable, Optional
from google.adk.agents import LlmAgent, SequentialAgent, BaseAgent
from google.adk.tools import FunctionTool, BaseTool

def _create_looper(
    model: BaseAgent,
    output_key: str,
    report_tool: FunctionTool
) -> LlmAgent:
    """
    Creates a dedicated agent whose only job is to take a report from the state
    and send it back to the coordinator using the 'report_back' tool.
    """
    looper_instruction = f"""
    **CRITICAL:** Your ONLY job is to use the `report_back` tool.
    The report you must send is stored in the `{{{output_key}}}` state variable.
    Use the `report_back` tool to send the complete, unmodified content of that report.
    Do not add any text or explanation. Just call the tool.
    """

    # The looper has no need for complex callbacks as it's a simple, single-purpose agent.
    return LlmAgent(
        model=model,
        name="LooperAgent",
        tools=[report_tool],
        instruction=looper_instruction,
    )

def create_autovibe_workflow(
    model: BaseAgent,
    planner_instruction: str,
    coder_agent: LlmAgent, # Takes the fully-formed Coder agent
    delegate_tool: FunctionTool,
    report_tool: FunctionTool,
    thinking_tools: List[BaseTool],
    before_tool_callback: Optional[Callable] = None,
    after_tool_callback: Optional[Callable] = None,
) -> LlmAgent:
    """
    Assembles the complete autonomous workflow using the [Specialist -> Looper] pattern.
    """
    PLANNER_NAME = "PlannerAgent"
    
    # --- Create the Workflow Wrapper for the Coder ---
    # This is the core of the pattern.
    looper = _create_looper(
        model=model,
        output_key=coder_agent.output_key, # Use the output_key defined on the Coder
        report_tool=report_tool
    )

    coder_workflow = SequentialAgent(
        name=f"{coder_agent.name}Workflow",
        sub_agents=[coder_agent, looper]
    )

    # --- Define the Planner Agent (The Root Agent) ---
    PlannerAgent = LlmAgent(
        name=PLANNER_NAME,
        model=model,
        tools=[delegate_tool] + thinking_tools,
        # The Planner's sub-agent is the entire sequential workflow
        sub_agents=[coder_workflow],
        instruction=planner_instruction,
        before_tool_callback=before_tool_callback,
        after_tool_callback=after_tool_callback,
    )
    
    return PlannerAgent