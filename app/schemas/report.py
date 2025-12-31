from pydantic import BaseModel, Field
from typing import Optional

class ReportRequest(BaseModel):
    topic: str = Field(..., description="Chủ đề của báo cáo")
    content: str = Field(..., description="Nội dung thảo luận hoặc dàn ý thô cần tạo slide")
    format: str = Field("presentation", description="presentation, document, social, webpage")
    api_key: Optional[str] = None # Cho phép user truyền key riêng nếu muốn