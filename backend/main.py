"""
FastAPI 主程序
"""
import os
from dotenv import load_dotenv

# 加载环境变量，指定 .env 文件路径
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, Response
from pathlib import Path

from backend.api.rest import router as rest_router
from backend.api.websocket import router as ws_router
from backend.config.settings import settings


# 创建 FastAPI 应用
app = FastAPI(
    title="Live2D AI Assistant",
    description="Live2D 看板娘 AI 助手",
    version="1.0.0",
)

# 挂载静态文件
static_dir = Path(__file__).parent.parent / "frontend" / "static"
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

# 配置模板
templates_dir = Path(__file__).parent.parent / "frontend" / "templates"
templates = Jinja2Templates(directory=str(templates_dir))

# 注册路由
app.include_router(rest_router, prefix="/api", tags=["REST API"])
app.include_router(ws_router, prefix="/api", tags=["WebSocket"])


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    """Suppress browser 404 for favicon"""
    return Response(status_code=204)


@app.get("/", response_class=HTMLResponse)
async def root():
    """主页"""
    return templates.TemplateResponse("index.html", {"request": {}})


@app.get("/health")
async def health():
    """健康检查"""
    return {"status": "ok", "message": "Live2D AI Assistant is running"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
    )
