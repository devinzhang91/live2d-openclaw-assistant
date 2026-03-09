#!/bin/bash

# Live2D AI Assistant 停止脚本

# PID 和日志文件
PID_FILE=".live2d_assistant.pid"
LOG_FILE="logs/server.log"

echo "================================"
echo "Live2D AI Assistant 停止脚本"
echo "================================"
echo ""

# 检查 PID 文件是否存在
if [ ! -f "$PID_FILE" ]; then
    echo "⚠ 未找到 PID 文件，服务可能未通过 start.sh 启动"
    echo ""
    echo "尝试查找运行中的 uvicorn 进程..."
    PIDS=$(pgrep -f "uvicorn backend.main:app")
    if [ -n "$PIDS" ]; then
        echo "找到运行中的进程:"
        echo "$PIDS"
        echo ""
        read -p "是否停止这些进程? (y/n) " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            echo "$PIDS" | xargs kill
            echo "✓ 已停止进程"
        fi
    else
        echo "未找到运行中的进程"
    fi
    exit 0
fi

# 读取 PID
PID=$(cat "$PID_FILE")

# 检查进程是否存在
if ps -p "$PID" > /dev/null 2>&1; then
    echo "→ 正在停止服务 (PID: $PID)..."
    kill "$PID"

    # 等待进程结束
    TIMEOUT=10
    COUNT=0
    while ps -p "$PID" > /dev/null 2>&1 && [ $COUNT -lt $TIMEOUT ]; do
        sleep 1
        COUNT=$((COUNT + 1))
        echo -n "."
    done
    echo ""

    # 检查进程是否已停止
    if ps -p "$PID" > /dev/null 2>&1; then
        echo "⚠ 进程未响应，强制停止..."
        kill -9 "$PID"
        sleep 1
    fi

    echo "✓ 服务已停止"
else
    echo "⚠ 进程不存在 (PID: $PID)，清理 PID 文件"
fi

# 删除 PID 文件
rm -f "$PID_FILE"

echo "================================"
echo "完成"
echo "================================"
