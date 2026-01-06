import re, json
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
        "Answer Summary": "Answer Summary", # Để cắt lấy Insight
    }

    # Theo dõi Task nào đã stream chunk để tránh gửi lại full text
    # Set lưu các task_id đã từng bắn chunk
    streamed_tasks = set()
    
    # Dictionary map task_id -> bot_key (để dùng cho event done)
    active_tasks_map = {} 

    async with httpx.AsyncClient(timeout=300.0) as client:
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

                                    # Lấy output, answer hoặc text tùy node
                                    if bot_key == 'Answer Summary':
                                        content = outputs.get("answer")
                                    else:
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
    # Xử lý Insight
    if bot_id == 'Answer Summary':
        bot_id = 'Insight'
        if event_type == 'content':
            payload = format_insight_response(payload.split("[N1s Insight]\n\n", 1)[-1].strip()) # Cắt và xử lý Insight

    # Trả về json
    data = {
        "bot_id": bot_id,      # Ví dụ: "ceo"
        "event": event_type,   # Ví dụ: "start", "content", "done"
        "payload": payload     # Ví dụ: "Xin chào..."
    }
    return f"data: {json.dumps(data)}\n\n"

def format_insight_response(raw_payload):
    """
    Hàm xử lý payload đa định dạng (unstructured) để format thành JSON tiêu chuẩn.
    Chiến lược: Tìm keyword tiêu đề để cắt block, sau đó xử lý mềm dẻo từng dòng.
    """
    # CẮT KHỐI VĂN BẢN (SECTION SLICING)
    # Tìm header Summary (chứa 'サマリ')
    idx_summary = -1
    match_sum = re.search(r"(?:^|\n)\s*(?:【)?.*サマリ.*(?:】)?", raw_payload)
    if match_sum: idx_summary = match_sum.start()

    # Tìm header Highlights (chứa 'ハイライト' hoặc '重要発言')
    idx_high = -1
    match_high = re.search(r"(?:^|\n)\s*(?:【)?.*(?:ハイライト|重要発言).*(?:】)?", raw_payload)
    if match_high: idx_high = match_high.start()

    # Tìm header Reference (chứa '参考' hoặc 'URL')
    idx_ref = -1
    match_ref = re.search(r"(?:^|\n)\s*(?:【)?.*(?:参考|URL).*(?:】)?", raw_payload)
    if match_ref: idx_ref = match_ref.start()

    # Hàm cắt text dựa trên vị trí index
    def get_section_text(start_idx, next_indices):
        if start_idx == -1: return ""
        # Tìm index kế tiếp gần nhất lớn hơn start_idx
        valid_next = [i for i in next_indices if i > start_idx]
        end_idx = min(valid_next) if valid_next else len(raw_payload)
        
        # Lấy text, bỏ dòng header đầu tiên (tiêu đề section)
        text_block = raw_payload[start_idx:end_idx].strip()
        # Xóa dòng đầu tiên (là dòng chứa tiêu đề như 【全体サマリ】)
        first_newline = text_block.find('\n')
        if first_newline != -1:
            return text_block[first_newline+1:].strip()
        return text_block

    # Lấy nội dung thô từng phần
    indices = [idx_summary, idx_high, idx_ref, len(raw_payload)]
    raw_summary = get_section_text(idx_summary, indices)
    raw_highlights = get_section_text(idx_high, indices)
    raw_links = get_section_text(idx_ref, indices)

    # XỬ LÝ SUMMARY
    summary_content = raw_summary

    # XỬ LÝ HIGHLIGHTS
    highlights = process_highlights(raw_highlights)

    # XỬ LÝ REFERENCE LINKS 
    reference_links = process_links(raw_links)

    # Construct Final JSON Structure
    response_structure = {
        "summary": {
            "title": "サマリ",
            "content": summary_content
        },
        "highlights": highlights,
        "reference_links": reference_links
    }
    return response_structure

def process_links(raw_links):
    reference_links = []
    
    if raw_links:
        # Regex tìm URL và Tách chuỗi
        url_pattern = r"(https?://[^\s]+)"
        parts = re.split(url_pattern, raw_links)
        
        # parts[0] là text rác trước link 1.
        # Loop từ 1, bước nhảy 2 (Lấy cặp URL, Description)
        if len(parts) > 1:
            current_id = 1
            for i in range(1, len(parts), 2):                
                url = parts[i].strip()
                
                raw_desc = parts[i+1] if i+1 < len(parts) else ""                       # raw_desc là phần text nằm SAU URL hiện tại
                clean_desc = re.sub(r"[\n\r]", " ", raw_desc)                           # Gộp dòng thành 1 dòng duy nhất
                clean_desc = re.sub(r"\s+[\d\.\-]+\s*$", "", clean_desc)                # Xóa số thứ tự của item tiếp theo
                clean_desc = re.sub(r"^[ \t\-\d\.]+[:：]?\s*", "", clean_desc.strip())  # Xóa ký tự rác ở đầu chuỗi
                clean_desc = clean_desc.strip(" 　（()）")                              # Xóa cả ngoặc tròn fullwidth （） và halfwidth ()

                # Tách title từ description
                description = clean_desc
                title = ""
                
                delimiters = ["：", "・", "。"]
                
                # Tìm delimiter xuất hiện sớm nhất
                positions = [
                    (d, clean_desc.find(d))
                    for d in delimiters
                    if clean_desc.find(d) != -1
                ]

                if not positions:
                    title = clean_desc
                else:
                    delimiter, pos = min(positions, key=lambda x: x[1])
                    title = clean_desc[:pos].strip()
                    
                title = title.lstrip("（(").strip() # Clean đề phòng còn rác

                if url: 
                    reference_links.append({
                        "id": current_id,
                        "title": title,       
                        "description": description, 
                        "url": url
                    })
                    current_id += 1
                    
    return reference_links

def process_highlights(raw_highlights):
    highlights = []
    if raw_highlights:
        # Tách dòng, lọc dòng trống
        lines = [line.strip() for line in raw_highlights.split('\n') if line.strip()]
        
        count_id = 1
        for line in lines:
            # Bỏ ký tự đầu dòng như "1.", "-", "・"
            clean_line = re.sub(r"^[\d\.\-・\s]+", "", line)
            
            # Regex tìm Quote và Author 
            quote_match = re.search(r"(?:「)?(.*?)(?:」)?\s*[（\(](.*?)[）\)]", clean_line)
            
            if quote_match:
                quote = quote_match.group(1).strip()
                author_name = quote_match.group(2).strip()
                
                # Nếu quote quá ngắn (do lỗi parse), bỏ qua
                if len(quote) > 1: 
                    highlights.append({
                        "id": count_id,
                        "quote": quote,
                        "author_name": author_name
                    })
                    count_id += 1
    return highlights

# # --- TEST ---
# input_data = {
# "bot_id": "Answer Summary", "event": "content", "payload": "\u3010\u5168\u4f53\u30b5\u30de\u30ea\u3011\n\u4eca\u5e74\u306eAI\u958b\u767a\u6226\u7565\u306b\u3064\u3044\u3066\u3001\u7d4c\u55b6\u30fb\u4e8b\u696d\u30fb\u6280\u8853\u306e\u89b3\u70b9\u304b\u3089\u8b70\u8ad6\u3055\u308c\u307e\u3057\u305f\u3002\u5e02\u5834\u30cb\u30fc\u30ba\u3084\u30d3\u30b8\u30cd\u30b9\u4fa1\u5024\u3068\u3057\u3066\u306f\u300c\u5358\u306a\u308b\u52b9\u7387\u5316\u300d\u3067\u306f\u306a\u304f\u3001\u65e2\u5b58\u4e8b\u696d\u306e\u975e\u9023\u7d9a\u6210\u9577\u3092\u751f\u307f\u51fa\u3059\u9818\u57df\u3001\u7279\u306b\u73fe\u5834\u306e\u672a\u89e3\u6c7a\u8ab2\u984c\u3092\u76f4\u63a5\u89e3\u6d88\u3059\u308b\u30bd\u30ea\u30e5\u30fc\u30b7\u30e7\u30f3\u304c\u91cd\u8996\u3055\u308c\u3066\u3044\u307e\u3059\u3002\u53ce\u76ca\u6027\u3084ROI\u306e\u89b3\u70b9\u3067\u306f\u3001\u65e2\u5b58\u30a2\u30bb\u30c3\u30c8\u00d7AI\u306b\u3088\u308b\u30d0\u30ea\u30e5\u30fc\u30a2\u30c3\u30d7\u3001\u610f\u601d\u6c7a\u5b9a\u30d7\u30ed\u30bb\u30b9\u306e\u81ea\u52d5\u5316\u30fb\u9ad8\u5ea6\u5316\u3001\u5c02\u9580\u4eba\u6750\u4e0d\u8db3\u3092\u88dc\u3046\u30ca\u30ec\u30c3\u30b8\u30ef\u30fc\u30ab\u30fc\u5411\u3051AI\u304c\u512a\u5148\u9818\u57df\u3068\u3055\u308c\u307e\u3057\u305f\u3002\n\n\u65b0\u898f\u4e8b\u696d\u3084\u30b5\u30fc\u30d3\u30b9\u30e2\u30c7\u30eb\u3068\u3057\u3066\u306f\u3001\u696d\u52d9\u30d7\u30ed\u30bb\u30b9\u306e\u90e8\u5206\u81ea\u52d5\u5316SaaS\u3001\u696d\u754c\u7279\u5316\u578bAI\u30a8\u30fc\u30b8\u30a7\u30f3\u30c8\u3001\u7570\u5e38\u691c\u77e5\uff0b\u610f\u601d\u6c7a\u5b9a\u652f\u63f4\u3001\u30c7\u30fc\u30bf\u30d1\u30fc\u30bd\u30ca\u30e9\u30a4\u30ba\u30b5\u30fc\u30d3\u30b9\u306a\u3069\u304c\u6319\u3052\u3089\u308c\u307e\u3057\u305f\u3002\u305f\u3060\u3057\u5f62\u3060\u3051\u3067\u306a\u304f\u300c\u8ab0\u306e\u3069\u3093\u306a\u6df1\u523b\u306a\u30da\u30a4\u30f3\u300d\u306b\u523a\u3055\u308b\u304b\u304c\u6700\u91cd\u8981\u3067\u3042\u308a\u3001\u5c0f\u898f\u6a21\u3067\u9867\u5ba2\u306b\u58f2\u308a\u8fbc\u307f\u306a\u304c\u3089\u672c\u8cea\u7684\u306a\u8ab2\u984c\u306b\u8feb\u308b\u738b\u9053\u30a2\u30d7\u30ed\u30fc\u30c1\u304c\u63a8\u5968\u3055\u308c\u307e\u3057\u305f\u3002\u30ea\u30b9\u30af\u7ba1\u7406\u3068\u3057\u3066\u306fPoC\u75b2\u308c\u3084\u904b\u7528\u8ca0\u8377\u306a\u3069\u306b\u3082\u6ce8\u610f\u304c\u5fc5\u8981\u3067\u3059\u3002\n\n\u6280\u8853\u9762\u3067\u306f\u3001\u30de\u30a4\u30af\u30ed\u30b5\u30fc\u30d3\u30b9\uff0bAPI\u30d5\u30a1\u30fc\u30b9\u30c8\u8a2d\u8a08\u306b\u3088\u308b\u62e1\u5f35\u6027\u3068\u73fe\u5834\u9069\u5fdc\u901f\u5ea6\u3001LLM\u00d7\u696d\u754c\u7279\u5316\u30ca\u30ec\u30c3\u30b8\u30b0\u30e9\u30d5\u306b\u3088\u308b\u8aac\u660e\u8cac\u4efb\u3068\u900f\u660e\u6027\u62c5\u4fdd\u3001\u9ad8\u901f\u306aMLOps\uff0b\u30bb\u30ad\u30e5\u30ea\u30c6\u30a3/\u30ac\u30d0\u30ca\u30f3\u30b9\u81ea\u52d5\u5316\u306b\u3088\u308b\u5b89\u5fc3\u904b\u7528\u4f53\u5236\u304c\u91cd\u8981\u8996\u3055\u308c\u3066\u3044\u307e\u3059\u3002\u6280\u8853\u7684\u8ab2\u984c\u306b\u306f\u30c7\u30fc\u30bf\u53d6\u5f97\u30b3\u30b9\u30c8\u3084UI\u8a2d\u8a08\u3001\u30e2\u30c7\u30eb\u7cbe\u5ea6\u7dad\u6301\u306a\u3069\u304c\u6319\u3052\u3089\u308c\u307e\u3057\u305f\u3002\n\n\u3010\u7d50\u8ad6\u3011\n\u4eca\u5e74AI\u958b\u767a\u3067\u91cd\u8996\u3059\u3079\u304d\u306f\u3001\u300c\u8ab0\u306e\u3069\u3093\u306a\u672a\u89e3\u6c7a\u8ab2\u984c\u3092\u3069\u3046\u89e3\u6c7a\u3059\u308b\u304b\u300d\u306b\u5fb9\u5e95\u30d5\u30a9\u30fc\u30ab\u30b9\u3057\u3001\u201c\u73fe\u5834\u5b9f\u88c5\u307e\u3067\u30b3\u30df\u30c3\u30c8\u201d\u3059\u308b\u3053\u3068\u3067\u3059\u3002ROI\u6700\u5927\u5316\u306b\u306f\u65e2\u5b58\u8cc7\u7523\u6d3b\u7528\u3084\u610f\u601d\u6c7a\u5b9a\u652f\u63f4\u9818\u57df\u3078\u306e\u96c6\u4e2d\u6295\u8cc7\u304c\u6709\u52b9\u3067\u3042\u308a\u3001\u5c0f\u898f\u6a21\u5b9f\u8a3c\u2192\u30d5\u30a3\u30fc\u30c9\u30d0\u30c3\u30af\u6539\u5584\u2192\u4e00\u70b9\u7a81\u7834\u578b\u5c55\u958b\u304c\u6210\u529f\u78ba\u7387\u3092\u9ad8\u3081\u307e\u3059\u3002\u6280\u8853\u9078\u5b9a\u3082\u73fe\u5834\u5bc6\u7740\u30fb\u900f\u660e\u6027\u30fb\u904b\u7528\u81ea\u52d5\u5316\u3092\u8ef8\u306b\u884c\u3044\u307e\u3057\u3087\u3046\u3002\n\n\u3010\u30ad\u30fc\u30cf\u30a4\u30e9\u30a4\u30c8\uff08\u91cd\u8981\u767a\u8a00\uff09\u3011\n\n- \u300c\u5358\u306a\u308b\u52b9\u7387\u5316\u3067\u306f\u306a\u304f\u3001\u201c\u73fe\u5834\u306e\u75db\u307f\u201d\u3084\u201c\u672a\u89e3\u6c7a\u8ab2\u984c\u201d\u3092\u76f4\u63a5\u89e3\u6d88\u3067\u304d\u308b\u30bd\u30ea\u30e5\u30fc\u30b7\u30e7\u30f3\u3053\u305d\u5727\u5012\u7684\u306b\u4fa1\u5024\u304c\u3042\u308b\u300d\uff08CEO\u91fc\u6301\uff09\n- \u300c\u6700\u91cd\u8981\u306a\u306e\u306f\u300e\u8ab0\u306e\u300f\u300e\u3069\u3093\u306a\u6df1\u523b\u306a\u30da\u30a4\u30f3\u300f\u306b\u523a\u3055\u308b\u304b\uff1f\u307e\u305a\u9867\u5ba2\u306b\u805e\u304d\u3001\u5c0f\u3055\u304f\u58f2\u308a\u3001\u57f7\u5ff5\u6df1\u304f\u6539\u5584\u3057\u7d9a\u3051\u308b\u3053\u3068\u300d\uff08\u53d6\u7de0\u5f79\u4e2d\u6751\uff09\n- \u300c\u30de\u30a4\u30af\u30ed\u30b5\u30fc\u30d3\u30b9\uff0bAPI\u30d5\u30a1\u30fc\u30b9\u30c8\u8a2d\u8a08\u3068LLM\u00d7\u30ca\u30ec\u30c3\u30b8\u30b0\u30e9\u30d5\u9023\u643a\u3001\u201cExplainable AI\u201d\u201c\u904b\u7528\u81ea\u52d5\u5316\u201d\u4e09\u4f4d\u4e00\u4f53\u304c\u4eca\u5e74\u306e\u52dd\u3061\u7b4b\u300d\uff08Tech\u7d71\u62ec\u57f7\u884c\u5f79\u54e1 \u5c0f\u6751\uff09\n\n\u3010\u53c2\u8003URL\u30fb\u8cc7\u6599\u30ea\u30f3\u30af\u3011\n\n1. https://www.mckinsey.com/capabilities/quantumblack/our-insights/the-economic-potential-of-generative-ai-the-next-productivity-frontier  \n\u3000\uff08\u751f\u6210AI\u306b\u3088\u308b\u7d4c\u6e08\u52b9\u679c\u3068ROI\u5411\u4e0a\u7b56\u306b\u3064\u3044\u3066\u5177\u4f53\u7684\u306a\u5206\u6790\u3002\u53ce\u76ca\u6027\u30fb\u5c0e\u5165\u9818\u57df\u9078\u5b9a\u306e\u53c2\u8003\u306b\u306a\u308b\uff09\n\n2. https://www.gartner.com/en/articles/7-ai-trends-that-will-shape-2024  \n\u3000\uff082024\u5e74\u306eAI\u30c8\u30ec\u30f3\u30c9\uff1a\u696d\u754c\u7279\u5316\u578bAI\u3084Explainable AI\u7b49\u3001\u672c\u8b70\u8ad6\u5185\u5bb9\u3068\u5408\u81f4\u3059\u308b\u6f6e\u6d41\uff09\n\n3. https://forbesjapan.com/articles/detail/69299  \n\u3000\uff08\u65e5\u672c\u4f01\u696d\u306b\u304a\u3051\u308bAI\u5c0e\u5165\u5931\u6557\u4f8b\u3068\u6210\u529f\u8981\u56e0\u3002\u300cPoC\u75b2\u308c\u300d\u3084\u73fe\u5834\u5b9f\u88c5\u8ab2\u984c\u3082\u8a18\u8f09\uff09\n\n4. https://enablex-inc.com/info  \n\u3000\uff08enableX\u793e\u306e\u304a\u77e5\u3089\u305b\u30fb\u6700\u65b0\u30d7\u30ed\u30c0\u30af\u30c8\u60c5\u5831\u3002\u5b9f\u88c5\u529b\u00d7\u904b\u7528\u529b\u3067\u5dee\u5225\u5316\u3059\u308b\u53d6\u308a\u7d44\u307f\u4e8b\u4f8b\u3042\u308a\uff09\n\n5. https://note.com/enablexinc/n/nf2e6c3f8d7d0  \n\u3000\uff08enableX\u793e\u306b\u3088\u308b\u300c\u696d\u754c\u5225AI\u5c0e\u5165\u30ce\u30a6\u30cf\u30a6\u300d\u3002\u73fe\u5834\u5bc6\u7740\u578b\u30a2\u30d7\u30ed\u30fc\u30c1\u3084\u904b\u7528\u30ce\u30a6\u30cf\u30a6\u3082\u8c4a\u5bcc\uff09\n\n\u5404URL\u306f\u5e02\u5834\u52d5\u5411\u628a\u63e1\u30fb\u6226\u7565\u7acb\u6848\u30fb\u6280\u8853\u9078\u5b9a\u30fb\u73fe\u5834\u5b9f\u88c5\u30ce\u30a6\u30cf\u30a6\u78ba\u8a8d\u306b\u6709\u7528\u3067\u3059\u3002"}
# print(format_sse(input_data["bot_id"], input_data["event"], input_data["payload"]))