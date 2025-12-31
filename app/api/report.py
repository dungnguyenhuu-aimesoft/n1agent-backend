from fastapi import APIRouter
from app.schemas.report import ReportRequest
from app.services.gamma_service import create_gamma_presentation, get_generation_status

router = APIRouter()

@router.post("/create-report")
async def create_report_endpoint(request: ReportRequest):
    """
    **Chức năng:** Gửi nội dung thảo luận lên Gamma để bắt đầu quá trình tạo slide tự động.
    
    **Cơ chế:** - API này hoạt động **Bất đồng bộ**. 
    - Nó sẽ trả về ngay lập tức một `generation_id` (Job ID).
    - Client cần dùng ID này để gọi API `/status/{id}` kiểm tra tiến độ.
    
    **Tham số đầu vào:**
    - `content`: Nội dung thô cần chuyển đổi.
    - `format`: Mặc định là 'presentation' (Allowed:presentation, document, webpage, social).
    - `numcard`: Số lượng trang muốn tạo

    **Example Body:**
    ```json
    {
    "content": "Good backend development is not just about making APIs work. It’s about designing systems that are predictable, scalable, and easy to maintain.",
    "format": "presentation",
    "numcard": 1
    }
    ```
    """
    result = await create_gamma_presentation(request)
    return {
        "status": "success",
        "data": result
    }

@router.get("/status/{generation_id}")
async def get_report_status(generation_id: str):
    """
    **Chức năng:** Kiểm tra xem Gamma đã tạo xong slide chưa.
    
    **Hướng dẫn tích hợp (Frontend):** 
    1. Gọi API này mỗi **3-5 giây** (Polling).  
    2. Nếu `data.status` == `"pending"` hoặc `"processing"`: Tiếp tục chờ và hiển thị loading.  
    3. Nếu `data.status` == `"completed"`: Lấy link từ `data.url` (hoặc output object) để hiển thị.
    4. Nếu `data.status` == `"error"`: Thông báo lỗi.
    """
    result = await get_generation_status(generation_id)
    return {
        "status": "success",
        "data": result
    }