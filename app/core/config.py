import os
from pydantic_settings import BaseSettings # Cần cài thư viện pydantic-settings

class Settings(BaseSettings):
    DIFY_API_URL: str = "https://api.dify.ai/v1"
    GAMMA_API_KEY: str = ""
    
    # Tech Keys
    DIFY_KEY_TECH_RESPONSE: str = ""
    DIFY_KEY_TECH_SEARCH: str = ""
    DIFY_KEY_TECH_THINKING: str = ""
    
    # Other Keys
    DIFY_KEY_IR: str = ""
    DIFY_KEY_DISCUSS: str = ""

    # Gamma key
    GAMMA_API_KEY: str = os.getenv("GAMMA_API_KEY", "")

    class Config:
        env_file = ".env"

settings = Settings()

# Logic lấy key tổ chức lại ở đây hoặc trong service, nhưng data lấy từ settings
DIFY_KEYS = {
    "TECH": {
        "response": settings.DIFY_KEY_TECH_RESPONSE,
        "search": settings.DIFY_KEY_TECH_SEARCH,
        "thinking": settings.DIFY_KEY_TECH_THINKING
    },
    "IR": {
        "default": settings.DIFY_KEY_IR
    },
    "DISCUSS": {
        "default": settings.DIFY_KEY_DISCUSS
    }
}