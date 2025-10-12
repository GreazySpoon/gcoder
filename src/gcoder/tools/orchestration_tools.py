# src/gcoder/tools/orchestration_tools.py

from google.adk.tools import ToolContext, FunctionTool
from typing import Dict, Any

def create_delegate_task_tool(namespace: str) -> FunctionTool:
    """Factory that creates a configured 'delegate_task' tool."""
    def delegate_task(
        agent_name: str,
        task_instruction: str,
        tool_context: ToolContext
    ) -> Dict[str, Any]:
      """
      Assigns a specific task to a specialist agent and transfers control.
      """
      task_key = f"{namespace}:current_task"
      report_key = f"{namespace}:last_report"

      tool_context.state[task_key] = task_instruction
      tool_context.state[report_key] = None # Clear previous report

      tool_context.actions.transfer_to_agent = agent_name
      
      # THE CORE FIX: Return a confirmation dictionary
      return {
          "status": "success",
          "message": f"Control transferred to {agent_name} with the task: '{task_instruction[:50]}...'"
      }

    return FunctionTool(func=delegate_task)

def create_report_back_tool(coordinator_name: str, namespace: str) -> FunctionTool:
    """Factory that creates a configured 'report_back' tool."""
    def report_back(
        report: str,
        tool_context: ToolContext
    ) -> Dict[str, Any]:
      """
      Reports the outcome of a task back to the coordinator.
      """
      report_key = f"{namespace}:last_report"
      task_key = f"{namespace}:current_task"

      tool_context.state[report_key] = report
      tool_context.state[task_key] = None # Clear the task instruction

      tool_context.actions.transfer_to_agent = coordinator_name
      
      # THE CORE FIX: Return a confirmation dictionary
      return {
          "status": "success",
          "message": "Report submitted and control transferred back to coordinator."
      }

    return FunctionTool(func=report_back)

def delegate_to_coder(tool_context: ToolContext, task_instruction: str) -> str:
    """
    Delegates a specific, single-step task to the Coder agent for execution.
    Use this to assign a focused part of the overall plan.
    """
    # Set the instruction for the Coder in the session state
    tool_context.state["coder_instruction"] = task_instruction
    # Signal the ADK Runner to transfer control to the CoderAgent
    tool_context.actions.transfer_to_agent = "CoderAgent"
    return f"Task delegated to Coder: {task_instruction}"

def exit_loop(tool_context: ToolContext) -> str:
    """
    Call this tool ONLY when the user's overall task is fully complete.
    This action will terminate the autonomous workflow and present the final summary.
    """
    # This signal tells the parent LoopAgent to stop iterating.
    tool_context.actions.escalate = True
    return "Workflow termination signal sent."