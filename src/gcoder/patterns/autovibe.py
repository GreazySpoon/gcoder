# src/gcoder/patterns/autovibe.py

from typing import AsyncGenerator, List, Optional, Callable
from typing_extensions import override

from google.adk.agents import LlmAgent, BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event, EventActions
from google.adk.tools import BaseTool, FunctionTool, ToolContext
from google.adk.models.base_llm import BaseLlm

# --- Tool Specific to this Pattern ---

def delegate_to_coder(tool_context: ToolContext, task_instruction: str) -> str:
    """
    Delegates a specific, single-step task to the Coder agent. Use this to assign a
    focused part of the overall plan.
    """
    tool_context.actions.transfer_to_agent = "CoderWorkflow"
    tool_context.state["coder_instruction"] = task_instruction
    return f"Task delegated to Coder: {task_instruction}"

# --- The Smart Wrapper Agent ---

class CoderWorkflow(BaseAgent):
    """
    A custom wrapper agent that guarantees control returns to the Planner.
    It runs the Coder agent, waits for it to finish, and then programmatically
    signals a transfer back to the Planner.
    """
    def __init__(self, coder_agent: LlmAgent, planner_name: str, **kwargs):
        super().__init__(name="CoderWorkflow", sub_agents=[coder_agent], **kwargs)
        self._coder_agent = coder_agent
        self._planner_name = planner_name

    @override
    async def _run_async_impl(
        self, ctx: InvocationContext
    ) -> AsyncGenerator[Event, None]:
        """
        Orchestrates the Coder -> Planner return trip.
        """
        async for event in self._coder_agent.run_async(ctx):
            yield event

        yield Event(
            author=self.name,
            actions=EventActions(transfer_to_agent=self._planner_name)
        )

# --- Pattern Assembly Function ---

def create_autovibe_workflow(
    model: BaseLlm,
    coder_tools: List[BaseTool],
    planner_instruction: str,
    coder_instruction: str,
    before_tool_callback: Optional[Callable] = None,
    after_tool_callback: Optional[Callable] = None,
) -> LlmAgent:
    """
    Assembles the complete "Planner-Coder" conversational workflow.
    """
    PLANNER_NAME = "PlannerAgent"
    
    CoderAgent = LlmAgent(
        name="CoderAgent",
        model=model,
        tools=coder_tools,
        output_key="coder_report",
        instruction=coder_instruction,
        before_tool_callback=before_tool_callback,
        after_tool_callback=after_tool_callback,
    )

    PlannerAgent = LlmAgent(
        name=PLANNER_NAME,
        model=model,
        tools=[
            FunctionTool(func=delegate_to_coder),
            # Your thinking tools will be added in the main agent file
        ],
        sub_agents=[CoderWorkflow(coder_agent=CoderAgent, planner_name=PLANNER_NAME)],
        instruction=planner_instruction,
        before_tool_callback=before_tool_callback,
        after_tool_callback=after_tool_callback,
    )
    
    return PlannerAgent