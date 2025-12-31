import httpx
from fastapi import HTTPException
from app.core.config import settings
from app.schemas.report import ReportRequest

GAMMA_API_URL = "https://public-api.gamma.app/v1.0/generations"

async def create_gamma_presentation(request: ReportRequest):
    api_key = settings.GAMMA_API_KEY
    
    if not api_key:
        raise HTTPException(status_code=500, detail="Missing GAMMA_API_KEY")

    headers = {
        "Content-Type": "application/json",
        "X-API-KEY": api_key
    }

    payload = {
        "inputText": request.content, # Nội dung thảo luận
        "textMode": "preserve",       # Không thay đổi nội dung prompt (generate, condense)
        "format": request.format,     # Mặc định là presentation
        "cardSplit": "auto",          # Tự động chia slide
        "numCards": request.numCards,
        "exportAs": "pptx",
        
        # Hướng dẫn bổ sung để AI biết đây là báo cáo tổng hợp
        "additionalInstructions": f"Create a professional summary report about '{request.content}'. Focus on key insights, decisions, and action items from the discussion.",
        
        "textOptions": {
            "language": "en" 
        },
        
        # Chọn ảnh minh họa AI
        "imageOptions": {
            "source": "aiGenerated",
            "style": "photorealistic, minimal"
        }
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            response = await client.post(GAMMA_API_URL, json=payload, headers=headers)
            
            if response.status_code == 200:
                data = response.json()
                # Trả về URL của file Gamma vừa tạo
                return data 
            else:
                raise HTTPException(status_code=response.status_code, detail=response.text)
                
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
        
async def get_generation_status(generation_id: str, api_key: str = None):
    """
    Gọi Gamma để kiểm tra xem quá trình tạo slide đã xong chưa.
    """
    real_key = api_key or settings.GAMMA_API_KEY
    if not real_key:
        raise HTTPException(status_code=500, detail="Missing GAMMA_API_KEY")

    headers = {
        "Content-Type": "application/json",
        "X-API-KEY": real_key
    }
    
    url = f"https://public-api.gamma.app/v1.0/generations/{generation_id}"

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.get(url, headers=headers)
            
            if response.status_code == 200:
                return response.json() # Trả về status (pending/completed) và url (nếu xong)
            elif response.status_code == 404:
                raise HTTPException(status_code=404, detail="Generation ID not found")
            else:
                raise HTTPException(status_code=response.status_code, detail=response.text)
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))