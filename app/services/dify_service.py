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