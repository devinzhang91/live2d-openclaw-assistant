#!/bin/bash

# Live2D AI Assistant 启动脚本

# PID 和日志文件
PID_FILE=".live2d_assistant.pid"
LOG_FILE="logs/server.log"
LOG_ERROR_FILE="logs/server_error.log"

# 创建日志目录
mkdir -p logs

# 日志函数
log_info() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] INFO: $1" | tee -a "$LOG_FILE"
}

log_error() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ERROR: $1" | tee -a "$LOG_ERROR_FILE"
}

# 检查服务是否已在运行
if [ -f "$PID_FILE" ]; then
    OLD_PID=$(cat "$PID_FILE")
    if ps -p "$OLD_PID" > /dev/null 2>&1; then
        echo "================================"
        echo "服务已在运行中"
        echo "================================"
        echo "PID: $OLD_PID"
        echo "如需重启服务，请先运行: bash stop.sh"
        exit 1
    else
        log_info "旧的 PID 文件存在但进程不存在，清理 PID 文件"
        rm -f "$PID_FILE"
    fi
fi

echo "================================"
echo "Live2D AI Assistant 启动脚本"
echo "================================"
echo ""

# 虚拟环境目录
VENV_DIR="venv"
PYTHON_CMD="python3"

# 检查是否已存在虚拟环境
if [ -d "$VENV_DIR" ]; then
    log_info "虚拟环境已存在: $VENV_DIR"
else
    echo "→ 创建虚拟环境..."
    $PYTHON_CMD -m venv "$VENV_DIR" 2>> "$LOG_ERROR_FILE"
    if [ $? -eq 0 ]; then
        log_info "虚拟环境创建成功: $VENV_DIR"
    else
        log_error "虚拟环境创建失败"
        exit 1
    fi
fi

# 激活虚拟环境
log_info "激活虚拟环境..."
source "$VENV_DIR/bin/activate"

# 检查 Python 版本
PYTHON_VERSION=$(python --version)
log_info "Python 版本: $PYTHON_VERSION"

# 升级 pip
log_info "升级 pip..."
pip install --upgrade pip -q 2>> "$LOG_ERROR_FILE"

# 检查是否存在 requirements.txt
if [ -f "requirements.txt" ]; then
    log_info "安装依赖..."
    pip install -r requirements.txt -q 2>> "$LOG_ERROR_FILE"
    if [ $? -eq 0 ]; then
        log_info "依赖安装成功"
    else
        log_error "依赖安装失败，请查看 $LOG_ERROR_FILE"
        exit 1
    fi
else
    log_info "未找到 requirements.txt 文件"
fi

# 检查 .env 文件
if [ ! -f ".env" ]; then
    if [ -f ".env.example" ]; then
        cp .env.example .env
        log_info ".env 文件创建成功（从 .env.example 复制）"
        echo ""
        echo "⚠ 重要提示: 请编辑 .env 文件，填入你的 API Key 和配置"
    else
        log_info "未找到 .env.example 文件"
    fi
else
    log_info ".env 文件已存在"
fi

# 启动服务器
echo ""
echo "================================"
echo "→ 启动服务器..."
echo "================================"
echo ""

# 运行服务器
if [ -f "backend/main.py" ]; then
    nohup python -u -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload >> "$LOG_FILE" 2>> "$LOG_ERROR_FILE" &
    SERVER_PID=$!
elif [ -f "main.py" ]; then
    nohup python main.py >> "$LOG_FILE" 2>> "$LOG_ERROR_FILE" &
    SERVER_PID=$!
elif [ -f "app.py" ]; then
    nohup python app.py >> "$LOG_FILE" 2>> "$LOG_ERROR_FILE" &
    SERVER_PID=$!
else
    log_error "未找到入口文件 (backend/main.py, main.py 或 app.py)"
    exit 1
fi

# 保存 PID
echo "$SERVER_PID" > "$PID_FILE"

echo "================================"
echo "✓ 服务启动成功"
echo "================================"
echo "PID: $SERVER_PID"
echo "访问地址: http://localhost:8000"
echo "日志文件: $LOG_FILE"
echo "错误日志: $LOG_ERROR_FILE"
echo ""
echo "停止服务: bash stop.sh"
echo "查看日志: tail -f $LOG_FILE"
