# thinking_tools.py (Corrected Version)

import logging
from textwrap import dedent
from typing import Any, Dict, List
from typing_extensions import override
from google.adk.tools.tool_context import ToolContext
    # InvocationContext is needed for app_name, user_id, session_id when calling service directly
from google.adk.agents.invocation_context import InvocationContext
from google.adk.tools import BaseTool
from google.genai import types



logger = logging.getLogger(__name__)

class ThinkTool(BaseTool):
    """
    A tool that acts as a private scratchpad for the AI. It allows the AI to record
    its reasoning, plans, and observations without showing them directly to the user.
    Thoughts are persisted throughout the current session.
    """
    def __init__(self):
        super().__init__(
            name='think_tool',
            description=(
                "Use this tool as a private scratchpad to reason about the user's request, "
                "plan steps, check rules, and reflect on tool outputs. It helps you "
                "organize your thoughts before responding. It does not take actions or "
                "show the output to the user."
            )
        )

    def _get_declaration(self) -> types.FunctionDeclaration | None:
        """Defines the tool's interface for the LLM."""
        return types.FunctionDeclaration(
            name=self.name,
            description=self.description,
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    'thought': types.Schema(
                        type=types.Type.STRING,
                        description="The thought, reflection, or step-by-step reasoning to record."
                    )
                },
                required=['thought']
            )
        )

    @override
    async def run_async(self, *, args: dict[str, Any], tool_context: ToolContext) -> Dict[str, Any]:
        """
        Executes the think tool logic. It records the thought in the session state
        and returns a structured dictionary containing the recorded thought and a
        list of all previous thoughts.
        """
        thought = args.get('thought')
        if not isinstance(thought, str) or not thought.strip():
            return {'status': 'error', 'message': 'Invalid or empty "thought" provided.'}

        try:
            inv_ctx: "InvocationContext" = tool_context._invocation_context  # type: ignore
            if not hasattr(inv_ctx.session, 'state'):
                inv_ctx.session.state = {}

            thoughts_list: List[str] = inv_ctx.session.state.setdefault('thoughts', [])
            thoughts_list.append(thought)
            logger.info(f"AI recorded a thought: {thought}")

            # --- KEY CHANGE ---
            # Return a simple, structured dictionary. The model is much more
            # likely to handle this correctly than a complex, multi-line string.
            # The model will see this structured output and understand its own
            # thought process from the list.
            return {
                'status': 'success',
                'thought_recorded': thought,
                #'all_current_thoughts': thoughts_list
            }

        except Exception as e:
            logger.error(f"Error in think_tool: {e}", exc_info=True)
            return {'status': 'error', 'message': f"An unexpected error occurred while recording the thought: {str(e)}"}


# --- Instantiate and Export Tools ---

think_tool = ThinkTool()

ALL_THINKING_TOOLS = [
    think_tool,
]