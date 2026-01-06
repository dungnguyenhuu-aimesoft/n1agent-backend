from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from app.schemas.chat import ChatRequest
from app.services.dify_service import dify_stream_generator, get_api_key, dify_discuss_stream_generator
from app.core.config import DIFY_KEYS

router = APIRouter()

@router.post("/n1-talk")
async def n1_talk_endpoint(request: ChatRequest):
    """
    Khởi tạo cuộc hội thoại 1-1 với một nhân vật AI cụ thể (N1).
    Hỗ trợ đa chế độ (Response, Search, Thinking) đối với nhân vật Tech Director.

    **Logic chọn API Key:**
    - **CEO / IR**: Sử dụng Key mặc định.
    - **TECH**: Sử dụng Key dựa trên tham số `mode`.

    **Parameters:**
    - **query** (str): Câu hỏi hoặc nội dung thảo luận của người dùng.
    - **user_id** (str): ID định danh người dùng.
    - **target_persona** (str): Nhân vật muốn chat. Giá trị hợp lệ: `CEO`, `IR`, `TECH`.
    - **mode** (str, optional): Chế độ trả lời . 
        - `response`
        - `search`
        - `thinking`
    - **conversation_id** (str, optional): ID cuộc hội thoại cũ để tiếp tục chat (Memory).

    **Returns:**
    - **Stream (text/event-stream)**: Dữ liệu trả về dạng Server-Sent Events (SSE).
        - Event `message`: Chứa text câu trả lời (`data: {"text": "..."}`).
        - Event `message_end`: Chứa `conversation_id` khi kết thúc.

    **Example Body:**
    ```json
    {
      "query": "Tìm kiếm tin tức AI mới nhất",
      "user_id": "user_123",
      "target_persona": "TECH",
      "mode": "search",
      "conversation_id": ""
    }
    ```

    **Raises:**
    - **400 Bad Request**: Nếu không tìm thấy cấu hình API Key cho Persona/Mode yêu cầu.
    - **500 Internal Server Error**: Lỗi kết nối đến Dify hoặc lỗi hệ thống.
    """
    target_key = get_api_key(request.target_persona, request.mode)
    
    if not target_key:
        raise HTTPException(status_code=400, detail=f"Cấu hình lỗi cho {request.target_persona}")

    payload = {
        "inputs": request.inputs or {},
        "query": request.query,
        "response_mode": "streaming",
        "conversation_id": request.conversation_id,
        "user": request.user_id,
        "auto_generate_name": False
    }

    return StreamingResponse(dify_stream_generator(payload, target_key), media_type="text/event-stream")


@router.post("/discuss")
async def discuss_endpoint(request: ChatRequest):
    """
    Kích hoạt phiên thảo luận nhóm giữa 3 AI (CEO, Business, Tech).
    Dựa trên mô hình 'N1s Discussion Insight Model' để tự động sinh ra kịch bản tranh luận và tổng hợp Insight.

    **Cơ chế hoạt động:**
    - Backend gọi vào Dify App được cấu hình sẵn Workflow thảo luận.

    **Parameters:**
    - **query** (str): Chủ đề cần thảo luận.
    - **user_id** (str): ID định danh người dùng.
    - **conversation_id** (str, optional): ID cuộc hội thoại cũ.

    **Returns:**
    - **Document link:**: https://docs.google.com/document/d/1NCoiHu5sPlAyExVqZJTJ_riaXdTc_5b9vX7AGYSjIzQ/edit?usp=sharing

    **Example Body:**
    ```json
    {
      "query": "Làm sao để tối ưu chi phí Cloud?",
      "user_id": "user_123",
      "conversation_id": ""
    }
    ```

    **Raises:**
    - **500 Internal Server Error**: Chưa cấu hình `DIFY_KEY_DISCUSS` trong file môi trường (.env).
    """
    discuss_key = DIFY_KEYS["DISCUSS"].get("default")
    
    if not discuss_key:
        raise HTTPException(status_code=500, detail="Chưa cấu hình DIFY_KEY_DISCUSS")

    payload = {
        "inputs": request.inputs or {},
        "query": request.query,
        "response_mode": "streaming",
        "conversation_id": request.conversation_id,
        "user": request.user_id,
        "auto_generate_name": False
    }

    # return StreamingResponse(dify_stream_generator(payload, discuss_key), media_type="text/event-stream")
    return StreamingResponse(dify_discuss_stream_generator(payload, discuss_key), media_type="text/event-stream")