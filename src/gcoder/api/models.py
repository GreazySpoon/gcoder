# src/gcoder/api/models.py

from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any, Union

class SessionInfo(BaseModel):
    id: str
    last_updated_at: Union[str, int, float, None]
    last_cwd: str

class CreateSessionResponse(BaseModel):
    session_id: str

class MessageRequest(BaseModel):
    prompt: str

class ToolExecution(BaseModel):
    tool_name: str
    tool_args: Dict[str, Any]
    result: Optional[str] = None

class SyncMessageResponse(BaseModel):
    session_id: str
    content: Optional[str] = None
    tools: List[ToolExecution] = Field(default_factory=list)
    error: Optional[str] = None