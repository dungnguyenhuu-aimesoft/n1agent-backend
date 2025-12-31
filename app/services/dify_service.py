import json
import httpx
from app.core.config import settings, DIFY_KEYS

def get_api_key(persona: str, mode: str):
    persona_config = DIFY_KEYS.get(persona)
    if not persona_config:
        return None
    if mode in persona_config:
        return persona_config[mode]
    return persona_config.get("default") or persona_config.get("response")

async def dify_stream_generator(payload, api_key):
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    async with httpx.AsyncClient(timeout=120.0) as client:
        try:
            async with client.stream("POST", f"{settings.DIFY_API_URL}/chat-messages", headers=headers, json=payload) as response:
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
                            if event in ["message", "agent_message"]:
                                yield f"data: {json.dumps({'text': data_json.get('answer', '')})}\n\n"
                            elif event == "message_end":
                                yield f"data: {json.dumps({'conversation_id': data_json.get('conversation_id'), 'is_finished': True})}\n\n"
                                yield "data: [DONE]\n\n"
                        except: continue
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"


async def dify_discuss_stream_generator(payload, api_key):
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    BOT_MAPPING = {
        "経営者": "ceo", 
        "事業開発エキスパート": "biz_dev",
        "AI・DXテクニカルエキスパート": "tech_lead",
        "Facilitator": "facilitator",
        "Insight": "Insight"
    }

    # Theo dõi Task nào đã stream chunk để tránh gửi lại full text
    # Set lưu các task_id đã từng bắn chunk
    streamed_tasks = set()
    
    # Dictionary map task_id -> bot_key (để dùng cho event done)
    active_tasks_map = {} 

    async with httpx.AsyncClient(timeout=120.0) as client:
        try:
            async with client.stream("POST", f"{settings.DIFY_API_URL}/chat-messages", headers=headers, json=payload) as response:
                if response.status_code != 200:
                    error_text = await response.aread()
                    yield f"data: {json.dumps({'error': error_text.decode()})}\n\n"
                    return

                async for line in response.aiter_lines():
                    if not line.startswith("data:"): continue
                    data_str = line[5:].strip()
                    if not data_str or data_str == "[DONE]": continue

                    try:
                        data_json = json.loads(data_str)
                        event = data_json.get("event")
                        task_id = data_json.get("task_id")
                        
                        # KHI BOT BẮT ĐẦU
                        if event == "node_started":
                            node_data = data_json.get("data", {})
                            title = node_data.get("title")
                            
                            if title in BOT_MAPPING:
                                bot_key = BOT_MAPPING[title]
                                active_tasks_map[task_id] = bot_key
                                yield format_sse(bot_key, "start", None)

                        # KHI STREAM TEXT (Hiệu ứng gõ chữ)
                        elif event == "text_chunk" or event == "message":
                            if task_id in active_tasks_map:
                                bot_key = active_tasks_map[task_id]
                                text = data_json.get("data", {}).get("text", "")
                                
                                if text:
                                    # Đánh dấu là task này ĐÃ stream
                                    streamed_tasks.add(task_id) 
                                    yield format_sse(bot_key, "content", text)

                        # KHI BOT HOÀN TẤT
                        elif event == "node_finished":
                            if task_id in active_tasks_map:
                                bot_key = active_tasks_map[task_id]
                                
                                # Chỉ gửi nội dung full NẾU chưa từng gửi chunk nào (Fallback)
                                # Giúp tránh lỗi hiển thị 2 lần văn bản
                                if task_id not in streamed_tasks:
                                    node_data = data_json.get("data", {})
                                    outputs = node_data.get("outputs", {})
                                    # Lấy output hoặc text tùy node
                                    content = outputs.get("output") or outputs.get("text")
                                    if content:
                                        yield format_sse(bot_key, "content", content)
                                
                                # Báo hiệu kết thúc bot này
                                yield format_sse(bot_key, "done", None)
                                
                                # Dọn dẹp
                                active_tasks_map.pop(task_id, None)
                                if task_id in streamed_tasks:
                                    streamed_tasks.remove(task_id)

                        # KẾT THÚC TOÀN BỘ
                        elif event == "message_end":
                            yield "data: [DONE]\n\n"

                    except Exception:
                        continue
                        
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"


# Helper function để format JSON chuẩn cho FE
def format_sse(bot_id, event_type, payload):
    data = {
        "bot_id": bot_id,      # Ví dụ: "ceo"
        "event": event_type,   # Ví dụ: "start", "content", "done"
        "payload": payload     # Ví dụ: "Xin chào..."
    }
    return f"data: {json.dumps(data)}\n\n"