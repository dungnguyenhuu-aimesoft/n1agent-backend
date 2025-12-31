from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api import chat, report

app = FastAPI(title="N1s Assistant API")

# Cấu hình CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include Router
app.include_router(chat.router, prefix="/api", tags=["Chat"])
app.include_router(report.router, prefix="/api", tags=["Report"])

# Health check
@app.get("/")
def read_root():
    return {"status": "running"}