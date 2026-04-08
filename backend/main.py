"""
FastAPI 主程序
"""
import os
import logging
from contextlib import asynccontextmanager
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


def _setup_realtime_logging():
    """在 uvicorn 启动后配置实时语音日志处理器

    注意：必须在 uvicorn 初始化日志系统之后执行，否则会被覆盖。
    因此放在 FastAPI lifespan 中配置。
    """
    from logging.handlers import RotatingFileHandler

    logs_dir = Path(__file__).parent.parent / "logs"
    logs_dir.mkdir(exist_ok=True)

    realtime_handler = RotatingFileHandler(
        logs_dir / "realtime.log",
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    realtime_handler.setLevel(logging.DEBUG)
    realtime_handler.setFormatter(
        logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )

    app_handler = RotatingFileHandler(
        logs_dir / "server.log",
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    app_handler.setLevel(logging.INFO)
    app_handler.setFormatter(
        logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )

    # 直接在目标 logger 上添加 handler（不受 uvicorn 日志重置影响）
    rt_logger = logging.getLogger("backend.services.realtime_volc")
    rt_logger.setLevel(logging.DEBUG)
    rt_logger.addHandler(realtime_handler)
    rt_logger.addHandler(app_handler)

    ws_logger = logging.getLogger("backend.api.websocket")
    ws_logger.setLevel(logging.INFO)
    ws_logger.addHandler(realtime_handler)
    ws_logger.addHandler(app_handler)

    rt_logger.info("[Logger] 实时语音日志系统初始化完成")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理（uvicorn 初始化完成后执行）"""
    _setup_realtime_logging()
    yield  # 应用运行中


# 创建 FastAPI 应用
app = FastAPI(
    title="Live2D AI Assistant",
    description="Live2D 看板娘 AI 助手",
    version="1.0.0",
    lifespan=lifespan,
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
