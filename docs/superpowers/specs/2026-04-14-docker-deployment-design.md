# Docker 部署设计方案

## 概述

为 Live2D AI 助手项目提供 Docker 容器化部署方案，支持单机快速部署。

## 架构

```
宿主机
├── .env 配置文件
└── Docker 容器
    └── FastAPI + Uvicorn (后端:8000)
        └── /static/* (前端静态文件)
```

## 方案选择

- **镜像类型**: 单容器（简单、符合项目复杂度）
- **GPU 支持**: 无（CPU-only，按要求）
- **ASR 模型**: 运行时下载（镜像更小）

## Dockerfile 设计

### 基础镜像
`python:3.11-slim` — 轻量级 Python 镜像

### 构建流程
1. 安装系统依赖（用于编译某些 Python 包）
2. 设置工作目录
3. 复制 requirements.txt
4. 安装 Python 依赖
5. 复制项目文件（后端 + 前端）
6. 暴露端口 8000
7. 启动命令使用 uvicorn

### 关键文件
- `Dockerfile` — 镜像构建定义
- `docker-compose.yml` — 容器编排配置
- `.dockerignore` — 排除不需要的文件（.git, __pycache__, .venv, logs 等）

## docker-compose.yml 设计

```yaml
services:
  live2d:
    build: .
    container_name: live2d-assistant
    ports:
      - "8000:8000"
    env_file:
      - .env
    restart: unless-stopped
    volumes:
      # 可选：保持日志和模型在宿主机
      - ./logs:/app/logs
```

## 构建和运行

```bash
# 构建镜像
docker build -t live2d-assistant .

# 运行容器
docker-compose up -d

# 查看日志
docker-compose logs -f
```

## 不包含的内容

- Whisper ASR 模型（首次运行时下载到容器内 `/root/.cache/huggingface`）
- GPU 加速支持
- 多容器架构

## 环境变量

通过 `.env` 文件挂载，所有配置（LLM、TTS、ASR 等）在 `.env.example` 中定义。