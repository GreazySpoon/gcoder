# src/gcoder/patterns/autonomous.py

from typing import List

from google.adk.agents import LlmAgent, SequentialAgent, BaseAgent
from google.adk.tools import FunctionTool, BaseTool

def _create_looper(
    model: BaseAgent,
    output_key: str,
    report_tool: FunctionTool
) -> LlmAgent:
    """
    Creates a dedicated agent whose only job is to report back the
    results from a specialist agent.
    """
    looper_instruction = f"""
    **YOU MUST USE THE `report_back` TOOL!**

    You are a reporting agent. Your ONLY function is to take the output from the previous agent and report it back to your coordinator.
    The report you must send is stored in the '{{{output_key}}}' state variable.

    You DO NOT have tools to write code, execute commands, or do anything other than reporting.
    Use the `report_back` tool to send the complete, unmodified report content.
    """
    return LlmAgent(
        model=model,
        name="LooperAgent",
        tools=[report_tool],
        instruction=looper_instruction,
    )

class AutonomousLlm(LlmAgent):
    """

    An autonomous agent pattern that dynamically orchestrates a team of specialists.
    It wraps each specialist in a sequential workflow that guarantees its final
    output is reported back to this main coordinator agent.
    """
    def __init__(
        self,
        specialists: List[LlmAgent],
        model: BaseAgent,
        name: str,
        instruction: str,
        output_key: str,
        delegate_tool: FunctionTool,
        report_tool: FunctionTool,
        thinking_tools: List[BaseTool],
        **kwargs
    ):
        """
        Initializes the AutonomousLlm coordinator agent.
        """
        if not specialists:
            raise ValueError("The 'specialists' list cannot be empty.")

        workflows = []
        for specialist in specialists:
            if not isinstance(specialist, LlmAgent):
                raise TypeError(f"Specialist must be an instance of LlmAgent, but got {type(specialist).__name__}")

            looper_agent = _create_looper(
                model=model,
                output_key=output_key,
                report_tool=report_tool
            )

            workflow = SequentialAgent(
                name=f"{specialist.name}Workflow",
                sub_agents=[specialist, looper_agent]
            )
            workflows.append(workflow)

        coordinator_tools = [delegate_tool] + thinking_tools

        super().__init__(
            model=model,
            name=name,
            instruction=instruction,
            tools=coordinator_tools,
            sub_agents=workflows,
            **kwargs
        )