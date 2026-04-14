FROM python:3.11-slim

# 设置工作目录
WORKDIR /app

# 安装系统依赖（用于编译 faster-whisper 等包）
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libsndfile1 \
    && rm -rf /var/lib/apt/lists/* \
    && ldconfig

# 设置动态链接器路径 (aarch64 for Apple Silicon, x86_64 for Intel)
RUN mkdir -p /etc/ld.so.conf.d && \
    echo "/usr/lib/aarch64-linux-gnu" > /etc/ld.so.conf.d/arm64.conf && \
    echo "/usr/lib" >> /etc/ld.so.conf.d/arm64.conf && \
    ldconfig

# 复制依赖文件
COPY requirements.txt .

# 安装 Python 依赖
RUN pip install --no-cache-dir -r requirements.txt

# 复制项目文件
COPY backend/ ./backend/
COPY frontend/ ./frontend/
COPY start.py .
COPY docs/ ./docs/

# 创建日志目录
RUN mkdir -p /app/logs

# 暴露端口
EXPOSE 8000

# 启动命令
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]