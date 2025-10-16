from __future__ import annotations

import os
import mimetypes
import logging
from typing import Any, TYPE_CHECKING, Dict, Optional

from google.genai import types
from typing_extensions import override

from google.adk.tools import BaseTool

if TYPE_CHECKING:
    from google.adk.models.llm_request import LlmRequest
    from google.adk.tools.tool_context import ToolContext

logger = logging.getLogger(__name__)

class LoadImageFromPathTool(BaseTool):
    """
    Loads an image from a local file path. The image content will be made
    available to the LLM in the subsequent turn's context for analysis.
    """
    def __init__(self):
        super().__init__(
            name='load_image_from_path',
            description="Loads an image from a local file path. The image content will be made available to you in the next turn.",
        )

    def _get_declaration(self) -> types.FunctionDeclaration | None:
        return types.FunctionDeclaration(
            name=self.name,
            description=self.description,
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    'image_path': types.Schema(
                        type=types.Type.STRING,
                        description="The local file path to the image to load."
                    ),
                },
                required=['image_path']
            ),
        )

    @override
    async def run_async(
        self, *, args: dict[str, Any], tool_context: ToolContext
    ) -> Dict[str, Any]:
        image_path = args.get('image_path')
        if not (isinstance(image_path, str) and image_path.strip()):
            return {'status': 'error', 'message': 'Invalid or missing "image_path" parameter.'}

        # Acknowledge the request. The actual file loading happens in process_llm_request.
        return {
            "status": "success",
            "message": f"Request to load image '{image_path}' acknowledged. Content will be prepared for your next context.",
            "requested_image_path": image_path
        }

    @override
    async def process_llm_request(
        self, *, tool_context: ToolContext, llm_request: LlmRequest
    ) -> None:
        await super().process_llm_request(
            tool_context=tool_context,
            llm_request=llm_request,
        )

        if not llm_request.contents or not llm_request.contents[-1].parts:
            return

        last_part = llm_request.contents[-1].parts[0]
        if not (last_part.function_response and last_part.function_response.name == self.name):
            return

        response_data = last_part.function_response.response
        requested_image_path: Optional[str] = None
        if isinstance(response_data, dict):
            path = response_data.get("requested_image_path")
            if isinstance(path, str):
                requested_image_path = path

        if not requested_image_path:
            return

        try:
            cwd = tool_context.state.get('cwd', os.getcwd())
            full_path = os.path.join(cwd, requested_image_path)

            if not os.path.isfile(full_path):
                raise FileNotFoundError(f"Image file not found at '{full_path}'")

            with open(full_path, 'rb') as f:
                image_bytes = f.read()

            mime_type = mimetypes.guess_type(full_path)[0] or "application/octet-stream"
            image_part = types.Part(inline_data=types.Blob(mime_type=mime_type, data=image_bytes))

            llm_request.contents.append(
                types.Content(
                    role='user',
                    parts=[
                        types.Part.from_text(text=f'Content of image "{requested_image_path}":'),
                        image_part,
                    ],
                )
            )
        except Exception as e:
            logger.error(f"{self.name}: Error loading image '{requested_image_path}': {e}", exc_info=True)
            llm_request.contents.append(
                types.Content(
                    role='user',
                    parts=[
                        types.Part.from_text(text=f'Note: Error loading image "{requested_image_path}": {str(e)}'),
                    ]
                )
            )

# --- Instantiate and Export Tools ---
load_image_from_path = LoadImageFromPathTool()

ALL_VISION_TOOLS = [
    load_image_from_path,
]

if not mimetypes.inited:
    mimetypes.init()