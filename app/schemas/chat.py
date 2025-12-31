from pydantic import BaseModel
from typing import Optional, Dict

class ChatRequest(BaseModel):
    query: str
    user_id: str
    conversation_id: str = ""
    inputs: Dict = {}
    # target_persona: str  # "TECH", "IR", "DISCUSS"
    target_persona: Optional[str] = None
    mode: str = "response" # "response", "search", "thinking"

class ReportRequest(BaseModel):
    topic: str
    content: str