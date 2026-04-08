#!/usr/bin/env python3
"""
快速启动脚本 - 检查依赖并启动服务
"""
import sys
import os
import subprocess
from pathlib import Path


def check_env_file():
    """检查 .env 文件是否存在"""
    env_file = Path(".env")
    env_example = Path(".env.example")

    if not env_file.exists():
        print("❌ 未找到 .env 文件")
        print(f"正在从 {env_example} 创建 .env 文件...")

        if env_example.exists():
            import shutil
            shutil.copy(env_example, env_file)
            print("✅ 已创建 .env 文件")
            print("⚠️  请编辑 .env 文件，设置 LLM_API_KEY")
            print()
            return False
        else:
            print("❌ 未找到 .env.example 文件")
            return False

    # 检查 API Key 是否已配置
    with open(env_file, "r") as f:
        env_content = f.read()

    if "your-openai-api-key-here" in env_content or "sk-" not in env_content:
        print("⚠️  检测到 LLM_API_KEY 未配置")
        print("请编辑 .env 文件，设置正确的 API Key")
        print()
        return False

    return True


def check_dependencies():
    """检查依赖是否已安装"""
    try:
        import fastapi
        import faster_whisper
        import edge_tts
        import openai
        print("✅ 依赖已安装")
        return True
    except ImportError as e:
        print(f"❌ 依赖未完全安装: {e}")
        print("请运行: pip install -r requirements.txt")
        print()
        return False


def clear_logs():
    """清空 logs 目录"""
    import shutil
    logs_dir = Path(__file__).parent / "logs"
    if logs_dir.exists():
        for f in logs_dir.glob("*"):
            try:
                f.unlink()
            except Exception:
                pass
    else:
        logs_dir.mkdir(exist_ok=True)


def setup_logging():
    """配置应用日志"""
    import logging
    from logging.handlers import RotatingFileHandler

    logs_dir = Path(__file__).parent / "logs"
    logs_dir.mkdir(exist_ok=True)

    # 应用日志
    app_log = logs_dir / "server.log"
    app_handler = RotatingFileHandler(app_log, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8")
    app_handler.setLevel(logging.INFO)
    app_handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    ))

    # 实时语音详细日志
    realtime_log = logs_dir / "realtime.log"
    realtime_handler = RotatingFileHandler(realtime_log, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8")
    realtime_handler.setLevel(logging.DEBUG)
    realtime_handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    ))

    # 配置根日志
    logging.basicConfig(level=logging.INFO, handlers=[app_handler])

    # 配置实时语音模块专属 logger
    rt_logger = logging.getLogger("backend.services.realtime_volc")
    rt_logger.setLevel(logging.DEBUG)
    rt_logger.addHandler(realtime_handler)
    rt_logger.addHandler(app_handler)

    ws_logger = logging.getLogger("backend.api.websocket")
    ws_logger.setLevel(logging.INFO)
    ws_logger.addHandler(realtime_handler)
    ws_logger.addHandler(app_handler)


def start_server():
    """启动服务器"""
    clear_logs()
    setup_logging()
    print("🚀 启动 Live2D AI 助手...")
    print("📍 访问地址: http://localhost:8000")
    print("📚 API 文档: http://localhost:8000/docs")
    print()
    print("⏳ 正在初始化服务...")
    print("   - 加载 Whisper ASR 模型（首次会下载，约 150MB）")
    print("   - 初始化 Edge-TTS")
    print("   - 初始化 VAD")
    print("   - 连接 LLM")
    print()

    from backend.main import app
    from backend.config.settings import settings

    import uvicorn

    # 使用 127.0.0.1 而不是 settings.host，确保麦克风可用
    uvicorn.run(
        app,
        host="127.0.0.1",  # 强制使用 localhost
        port=settings.port,
        reload=settings.debug,
    )


if __name__ == "__main__":
    # 添加项目根目录到 Python 路径
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

    print("=" * 50)
    print("  Live2D AI 助手 - 快速启动")
    print("=" * 50)
    print()

    # 检查环境
    if not check_env_file():
        print("请配置完成后重新运行此脚本")
        sys.exit(1)

    # 检查依赖
    if not check_dependencies():
        print("请安装依赖后重新运行此脚本")
        sys.exit(1)

    # 启动服务器
    try:
        start_server()
    except KeyboardInterrupt:
        print("\n\n👋 服务已停止")
    except Exception as e:
        print(f"\n\n❌ 启动失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
