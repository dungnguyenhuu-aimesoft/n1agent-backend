from pydantic import BaseModel, Field
from typing import Optional

class ReportRequest(BaseModel):
    content: str = Field(..., description="Nội dung thảo luận hoặc dàn ý thô cần tạo slide")
    format: str = Field("presentation", description="presentation, document, social, webpage")
    numCards: Optional[str] = None 