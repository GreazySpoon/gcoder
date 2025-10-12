# src/gcoder/patterns/custom_llm.py

from typing import List, AsyncGenerator, Optional

from google.adk.agents import LlmAgent, SequentialAgent, BaseAgent
from google.adk.tools import FunctionTool, BaseTool
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event
from typing_extensions import override

# This is the Looper agent from your original pattern. It's a helper here.
def _create_looper(
    model: BaseAgent,
    report_tool: FunctionTool
) -> LlmAgent:
    """
    Creates a dedicated agent whose only job is to execute the report_back tool.
    It receives the report content via session state.
    """
    looper_instruction = f"""
    **YOU MUST USE THE `report_back` TOOL!**

    You are a reporting agent. Your ONLY function is to take the report provided in the `looper_report_content` state variable and send it to the coordinator using the `report_back` tool.
    """
    return LlmAgent(
        model=model,
        name="LooperAgent",
        tools=[report_tool],
        instruction=looper_instruction,
    )

class CustomLlm(LlmAgent):
    """
    A custom autonomous agent that intelligently orchestrates a team of specialists.

    This agent acts as a coordinator. When it delegates to a specialist, it
    waits for the specialist to complete its work. It then catches the specialist's
    final 'report_back' tool call, extracts the report, and uses a dedicated
    'LooperAgent' to reliably transfer control back to itself.

    This prevents the 'dropped tool call' issue seen with simple SequentialAgents.
    """
    def __init__(
        self,
        specialists: List[LlmAgent],
        model: BaseAgent,
        name: str,
        instruction: str,
        delegate_tool: FunctionTool,
        report_tool: FunctionTool,
        thinking_tools: List[BaseTool],
        **kwargs
    ):
        # The specialists are the direct sub-agents for delegation purposes
        super().__init__(
            model=model,
            name=name,
            instruction=instruction,
            tools=[delegate_tool] + thinking_tools,
            sub_agents=specialists,
            **kwargs
        )
        # Internally store the specialists and create the looper for our custom logic
        self._specialists = {agent.name: agent for agent in specialists}
        self._looper_agent = _create_looper(model=model, report_tool=report_tool)

    @override
    async def _run_async_impl(
        self, ctx: InvocationContext
    ) -> AsyncGenerator[Event, None]:
        """
        Implements the custom orchestration logic.
        """
        # --- Step 1: Run the Coordinator's own logic ---
        # This will allow the coordinator to think and call 'delegate_task'.
        coordinator_events = super()._run_async_impl(ctx)
        
        target_agent_name: Optional[str] = None
        async for event in coordinator_events:
            # Yield all normal events from the coordinator (like thought processes)
            yield event
            # Intercept the event that signals a transfer
            if event.actions and event.actions.transfer_to_agent:
                target_agent_name = event.actions.transfer_to_agent
                break # Stop processing coordinator events once delegation starts

        # If the coordinator finished its turn without delegating, we are done.
        if not target_agent_name:
            return

        # --- Step 2: Run the designated Specialist ---
        specialist = self._specialists.get(target_agent_name)
        if not specialist:
            # Yield an error event if the delegated agent doesn't exist
            yield Event(author=self.name, error_message=f"Coordinator tried to delegate to an unknown agent: {target_agent_name}")
            return

        specialist_events = specialist.run_async(ctx)
        last_specialist_event: Optional[Event] = None
        async for event in specialist_events:
            yield event
            last_specialist_event = event

        # --- Step 3: Catch the final 'report_back' tool call ---
        if not last_specialist_event:
            return # Specialist produced no events

        final_tool_calls = last_specialist_event.get_function_calls()
        if not final_tool_calls or final_tool_calls[0].name != "report_back":
            # The specialist finished without calling report_back. This is an error in its logic.
            # We can optionally force a report-back with a default message.
            report_content = "Specialist finished without an explicit report."
        else:
            # We caught it! Extract the report content.
            report_content = final_tool_calls[0].args.get("report", "No report content provided.")

        # --- Step 4: Run the Looper to reliably transfer control back ---
        # Set the report content in a specific state key for the looper to find
        ctx.session.state["looper_report_content"] = report_content
        
        looper_events = self._looper_agent.run_async(ctx)
        async for event in looper_events:
            # This will yield the 'report_back' tool call from the looper,
            # which the runner will execute, finally transferring control
            # back to this Coordinator for the next cycle.
            yield event