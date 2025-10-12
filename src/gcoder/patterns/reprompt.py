# src/gcoder/patterns/reprompt.py

from typing import AsyncGenerator, List, Optional, Callable
from google.adk.agents import LlmAgent, SequentialAgent, LoopAgent, BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event, EventActions
from google.adk.tools import BaseTool
from google.adk.models.base_llm import BaseLlm

# --- Custom Control Agent (code is unchanged) ---
class LoopController(BaseAgent):
    """
    A simple, non-LLM agent that programmatically controls the main execution loop.
    """
    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        plan_str = ctx.session.state.get("plan", "")
        plan_list = [line for line in plan_str.split('\n') if line.strip()]
        current_index = ctx.session.state.get("current_step_index", 0)
        feedback = ctx.session.state.get("verifier_feedback", "")

        should_escalate = False
        
        if feedback and feedback.strip().upper() == "COMPLETE":
            current_index += 1
            ctx.session.state["current_step_index"] = current_index
            if current_index < len(plan_list):
                 ctx.session.state["current_sub_instruction"] = plan_list[current_index]
            else:
                 ctx.session.state["current_sub_instruction"] = "Plan is complete."
        elif feedback:
            ctx.session.state["current_sub_instruction"] = feedback

        if current_index >= len(plan_list):
            should_escalate = True

        yield Event(author=self.name, actions=EventActions(escalate=should_escalate))

# --- Pattern Assembly Function ---

def create_reprompt_workflow(
    model: BaseLlm,
    executor_tools: List[BaseTool],
    before_tool_callback: Optional[Callable] = None,
    after_tool_callback: Optional[Callable] = None,
    max_loops: int = 15
) -> SequentialAgent:
    """
    Assembles the full "Hierarchical Loop with Verification" (re-prompt) workflow.
    """
    # --- Create a string list of tool names for the Planner's prompt ---
#    tool_names = [tool.__name__ for tool in executor_tools if hasattr(tool, '__name__')]
    tool_names = [getattr(tool, 'name', getattr(tool, '__name__', 'unknown_tool')) for tool in executor_tools]

    tool_list_str = "\n".join([f"- `{name}`" for name in tool_names])

    # --- Specialist Agent Definitions ---

    PlannerAgent = LlmAgent(
        name="PlannerAgent",
        model=model,
        instruction=f"""You are a master strategist. Your goal is to create a concrete, actionable, step-by-step plan for a worker agent to achieve the user's request.

**CRITICAL RULES:**
1.  The worker agent can ONLY use the following tools. Your plan MUST be achievable using ONLY these tools:
{tool_list_str}
2.  Your plan MUST NOT include steps that require user interaction, browsing the web, or accessing external services not listed in the tools.
3.  Break down the problem into small, verifiable steps.
4.  Think in terms of file operations (`read_file`, `write_file`, `edit_file`) and command execution (`run_in_terminal`).

**EXAMPLE:**
User Request: "create a simple flask server"
Correct Plan:
1. Use `write_file` to create a file named `server.py`.
2. The content of `server.py` should be a minimal Flask application that serves 'Hello, World!'.
3. Use `run_in_terminal` to install Flask with the command `pip install Flask`.
4. Use `read_file` to verify the content of `server.py`.

**USER REQUEST:**
The user's request is stored in the '{{original_task}}' state variable.

Output ONLY the numbered list of plan steps.
""",
        output_key="plan",
        before_tool_callback=before_tool_callback,
        after_tool_callback=after_tool_callback,
    )

    ExecutorAgent = LlmAgent(
        name="ExecutorAgent",
        model=model,
        tools=executor_tools,
        instruction="""You are an expert worker agent. Your goal is to complete a single task.
- The overall plan is: {plan}
- Your current step is number {current_step_index}.
- Your specific instruction for this attempt is: {current_sub_instruction}

Use your tools to execute this single step. Think step-by-step.
When you are finished with this single step, provide a detailed summary of what you did, the results, and whether you believe the step was successful.
Output ONLY your summary report.""",
        output_key="executor_report",
        before_tool_callback=before_tool_callback,
        after_tool_callback=after_tool_callback,
    )

    VerifierAgent = LlmAgent(
        name="VerifierAgent",
        model=model,
        instruction="""You are a verification manager. Your job is to determine if the worker agent has successfully completed its assigned step.
- The original user goal was: {original_task}
- The full plan is: {plan}
- The worker's assigned step was: {current_sub_instruction}
- The worker's report of its actions and results is: {executor_report}

Analyze the worker's report and the tools it used. If the report provides clear evidence (e.g., successful command output, correct file content) that the step is fully complete, respond with the single word "COMPLETE".
If the worker failed, got stuck, or did not finish the step, provide a new, specific, corrective instruction to help it continue or fix its mistake.
Output ONLY the word "COMPLETE" or the new corrective instruction.""",
        output_key="verifier_feedback",
        before_tool_callback=before_tool_callback,
        after_tool_callback=after_tool_callback,
    )
    
    SummarizerAgent = LlmAgent(
        name="SummarizerAgent",
        model=model,
        instruction="""You are a reporting agent. The user's original task was '{original_task}'.
The execution of the plan is now complete. Review the final state of the 'plan', 'executor_report', and 'current_step_index'.
Provide a final, comprehensive summary of the entire process to the user, explaining what was done and the final outcome.""",
        before_tool_callback=before_tool_callback,
        after_tool_callback=after_tool_callback,
    )

    # --- Workflow Orchestration ---

    MasterLoopAgent = LoopAgent(
        name="MasterExecutionLoop",
        max_iterations=max_loops,
        sub_agents=[
            ExecutorAgent,
            VerifierAgent,
            LoopController(name="LoopController")
        ]
    )

    workflow = SequentialAgent(
        name="RepromptWorkflow",
        sub_agents=[
            PlannerAgent,
            MasterLoopAgent,
            SummarizerAgent
        ]
    )
    
    return workflow