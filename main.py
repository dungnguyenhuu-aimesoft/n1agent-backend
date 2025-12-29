import os
import json
import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()
app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DIFY_API_URL = os.getenv("DIFY_API_URL", "https://api.dify.ai/v1")
GAMMA_API_KEY = os.getenv("GAMMA_API_KEY", "")



# TECH có 3 chế độ, các con khác chỉ có 1 key mặc định (default)
DIFY_KEYS = {
    "TECH": {
        "response": os.getenv("DIFY_KEY_TECH_RESPONSE"),
        "search": os.getenv("DIFY_KEY_TECH_SEARCH"),
        "thinking": os.getenv("DIFY_KEY_TECH_THINKING")
    },
    "IR": {
        "default": os.getenv("DIFY_KEY_IR")
    },
    "DISCUSS": {
        "default": os.getenv("DIFY_KEY_DISCUSS")
    }
}

# --- DATA MODEL ---
class ChatRequest(BaseModel):
    query: str
    user_id: str
    conversation_id: str = ""
    inputs: dict = {}
    target_persona: str  # "TECH", "IR", "DISCUSS"
    mode: str = "response" # "response", "search", "thinking" (Chỉ có tác dụng với TECH)

class ReportRequest(BaseModel):
    topic: str
    content: str 

# --- HELPER FUNCTION ---
async def dify_stream_generator(payload, api_key):
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    async with httpx.AsyncClient(timeout=120.0) as client:
        try:
            async with client.stream("POST", f"{DIFY_API_URL}/chat-messages", headers=headers, json=payload) as response:
                if response.status_code != 200:
                    error_text = await response.aread()
                    yield f"data: {json.dumps({'error': error_text.decode()})}\n\n"
                    return
                async for line in response.aiter_lines():
                    if line.startswith("data:"):
                        data_str = line[5:].strip()
                        if not data_str: continue 
                        try:
                            data_json = json.loads(data_str)
                            event = data_json.get("event")
                            if event == "message" or event == "agent_message":
                                yield f"data: {json.dumps({'text': data_json.get('answer', '')})}\n\n"
                            elif event == "message_end":
                                yield f"data: {json.dumps({'conversation_id': data_json.get('conversation_id'), 'is_finished': True})}\n\n"
                                yield "data: [DONE]\n\n"
                        except: continue
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

# --- LOGIC CHỌN KEY ---
def get_api_key(persona: str, mode: str):
    """
    Hàm chọn API Key dựa trên Persona và Mode.
    - Nếu là TECH: Chọn key theo mode (response/search/thinking).
    - Nếu là IR/CEO: Luôn lấy key 'default' bất kể mode là gì.
    """
    persona_config = DIFY_KEYS.get(persona)
    
    if not persona_config:
        return None

    # Nếu persona này có chia nhiều mode (Như TECH)
    if mode in persona_config:
        return persona_config[mode]
    
    # Nếu không tìm thấy mode, hoặc persona chỉ có 1 mode -> lấy default (hoặc fallback về response)
    return persona_config.get("default") or persona_config.get("response")

# --- API ENDPOINT ---
# --- API 1: N1s Talk ---
@app.post("/api/n1-talk")
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
    # Lấy API Key chuẩn
    # request.mode có thể là "search", "thinking" nếu frontend gửi lên
    target_key = get_api_key(request.target_persona, request.mode)
    
    if not target_key:
        raise HTTPException(status_code=400, detail=f"Không tìm thấy cấu hình cho {request.target_persona} - Mode: {request.mode}")

    # Chuẩn bị Payload
    payload = {
        "inputs": request.inputs or {},
        "query": request.query,
        "response_mode": "streaming",
        "conversation_id": request.conversation_id,
        "user": request.user_id,
        "auto_generate_name": False
    }

    return StreamingResponse(dify_stream_generator(payload, target_key), media_type="text/event-stream")

# --- API 2: N1s Discussion Insight ---
@app.post("/api/discuss")
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
    - **Stream (text/event-stream)**: Dữ liệu SSE. Frontend cần hiển thị text liên tục.

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
    discuss_key = DIFY_KEYS["DISCUSS"]
    
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

    return StreamingResponse(dify_stream_generator(payload, discuss_key), media_type="text/event-stream")


# # --- API 3: Report (Gamma) ---
# @app.post("/api/create-report")
# async def create_report_endpoint(request: ReportRequest):
#     if not GAMMA_API_KEY:
#         raise HTTPException(status_code=500, detail="Missing GAMMA_API_KEY")

#     # Code gọi Gamma thật (Ví dụ)
#     # Lưu ý: Bạn cần check document mới nhất của Gamma API để biết endpoint chính xác
#     # Đây là giả lập call thành công
    
#     return JSONResponse({
#         "status": "success", 
#         "message": "Gamma report creation initiated",
#         "mock_url": "https://gamma.app/docs/generated-id" 
#     })



if __name__ == "__main__":
    import uvicorn
    print("Server running...")
    uvicorn.run(app, host="0.0.0.0", port=8000)