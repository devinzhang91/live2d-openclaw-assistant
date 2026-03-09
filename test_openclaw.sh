#!/usr/bin/env bash
# Test script for OpenClaw webhook (WS auth + POST /hooks/agent)
# Usage:
#   ./test_openclaw.sh [MESSAGE]
# Environment variables (optional):
#   BASE_URL (default: http://127.0.0.1:18789)
#   TOKEN    (default: taken from backend config if available)
#   SESSION_KEY (default: live2d-ai)

set -euo pipefail
ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_PY="$ROOT_DIR/venv/bin/python3"

# Default parameters (can be overridden via flags)
MESSAGE="你好，测试一下我的回复。"
BASE_URL="http://127.0.0.1:18789"
# Hardcoded token as requested
TOKEN="5f1acae55f18604ac326259b3423e39987dbe6b6d55100b8"
SESSION_KEY="live2d-ai"
DELIVER="false"
WAKE_MODE="next-heartbeat"
CHANNEL=""
HOOK_NAME="Live2D"
MODEL=""
THINKING=""
TIMEOUT_SECONDS=""

usage() {
    cat <<'EOF'
Usage: $0 [-m message] [-t token] [-u base_url] [-s session_key] [-d deliver] [-w wakeMode] [-c channel] [-n hook_name] [-M model] [-k thinking] [-T timeoutSeconds]

Options:
    -m MESSAGE     Message to send (default: "$MESSAGE")
    -t TOKEN       OpenClaw hook token (default hardcoded)
    -u BASE_URL    Base URL (default: $BASE_URL)
    -s SESSION_KEY Session key (default: $SESSION_KEY)
    -d DELIVER     deliver true/false (default: $DELIVER)
    -w WAKE_MODE   wakeMode (now | next-heartbeat) (default: $WAKE_MODE)
    -c CHANNEL     channel name (e.g., feishu)
    -n HOOK_NAME   Hook `name` field (default: $HOOK_NAME)
    -M MODEL       model override (optional)
    -k THINKING    thinking level (low|medium|high) (optional)
    -T TIMEOUT     timeoutSeconds (number) (optional)
    -h             show this help
EOF
}

while getopts "m:t:u:s:d:w:c:n:M:k:T:h" opt; do
    case "$opt" in
        m) MESSAGE="$OPTARG" ;; 
        t) TOKEN="$OPTARG" ;; 
        u) BASE_URL="$OPTARG" ;; 
        s) SESSION_KEY="$OPTARG" ;; 
        d) DELIVER="$OPTARG" ;; 
        w) WAKE_MODE="$OPTARG" ;; 
        c) CHANNEL="$OPTARG" ;; 
        n) HOOK_NAME="$OPTARG" ;; 
        M) MODEL="$OPTARG" ;; 
        k) THINKING="$OPTARG" ;; 
        T) TIMEOUT_SECONDS="$OPTARG" ;; 
        h) usage; exit 0 ;; 
        *) usage; exit 2 ;;
    esac
done

# Allow env vars to override defaults if provided
MESSAGE="${MESSAGE:-$MESSAGE}"
BASE_URL="${BASE_URL:-$BASE_URL}"
TOKEN="${TOKEN:-$TOKEN}"
SESSION_KEY="${SESSION_KEY:-$SESSION_KEY}"
DELIVER="${DELIVER:-$DELIVER}"
WAKE_MODE="${WAKE_MODE:-$WAKE_MODE}"
CHANNEL="${CHANNEL:-$CHANNEL}"
HOOK_NAME="${HOOK_NAME:-$HOOK_NAME}"
MODEL="${MODEL:-$MODEL}"
THINKING="${THINKING:-$THINKING}"
TIMEOUT_SECONDS="${TIMEOUT_SECONDS:-$TIMEOUT_SECONDS}"

if [ ! -x "$VENV_PY" ]; then
  echo "Warning: project venv python not found at $VENV_PY"
  echo "Falling back to system python3. Make sure required packages (websockets,httpx) are installed."
  VENV_PY="$(command -v python3 || true)"
  if [ -z "$VENV_PY" ]; then
    echo "python3 not found. Install Python 3.8+ and try again." >&2
    exit 1
  fi
fi

cat <<'PY' > /tmp/_oc_test.py
import asyncio
import json
import os
import sys
from urllib.parse import urlparse

import websockets
import httpx

BASE_URL = os.environ.get('BASE_URL', 'http://127.0.0.1:18789')
TOKEN = os.environ.get('TOKEN', '')
SESSION_KEY = os.environ.get('SESSION_KEY', 'live2d-ai')
MESSAGE = os.environ.get('MESSAGE', '你好，测试一下我的回复。')

async def ws_listen_and_post():
    parsed = urlparse(BASE_URL)
    ws_url = f"ws://{parsed.netloc}"
    origin = f"http://{parsed.netloc}"

    print(f"Connecting to WS: {ws_url} (Origin: {origin})")
    async with websockets.connect(ws_url, open_timeout=10, additional_headers={"Origin": origin}) as ws:
        # discard initial welcome
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=5)
            print("[WS] Initial message:", raw)
        except Exception:
            pass

        # send auth connect
        cid = 'cli-' + os.urandom(4).hex()
        connect_msg = {
            "type": "req",
            "id": cid,
            "method": "connect",
            "params": {
                "minProtocol": 3,
                "maxProtocol": 3,
                "client": {"id": "cli", "version": "1.0", "platform": "test", "mode": "webchat", "instanceId": "test-cli"},
                "role": "operator",
                "scopes": ["operator.admin"],
                "caps": [],
                "auth": {"token": TOKEN},
                "userAgent": "openclaw-test/1.0",
                "locale": "zh-CN",
            }
        }
        await ws.send(json.dumps(connect_msg, ensure_ascii=False))
        print(f"[WS] Sent connect req id={cid}")

        # wait for auth reply
        deadline = asyncio.get_event_loop().time() + 10
        authed = False
        while asyncio.get_event_loop().time() < deadline:
            try:
                rem = deadline - asyncio.get_event_loop().time()
                raw = await asyncio.wait_for(ws.recv(), timeout=rem)
            except Exception:
                break
            try:
                msg = json.loads(raw)
            except Exception:
                continue
            if msg.get('id') == cid:
                if msg.get('ok'):
                    print('[WS] Auth OK')
                    authed = True
                else:
                    print('[WS] Auth failed:', msg)
                break

        if not authed:
            print('[WS] Warning: auth not confirmed. Continuing to POST but WS may refuse messages.')

        # start receiver task
        async def receiver():
            print('[WS] Listening for events (will stop after receiving chat/final for sessionKey)')
            while True:
                try:
                    raw = await ws.recv()
                except Exception as e:
                    print('[WS] recv error:', e)
                    return None
                try:
                    msg = json.loads(raw)
                except Exception:
                    continue
                if msg.get('type') != 'event' or msg.get('event') != 'chat':
                    # print('[WS] other event:', msg)
                    continue
                payload = msg.get('payload', {})
                if payload.get('sessionKey') != f"agent:main:{SESSION_KEY}":
                    # not our session
                    continue
                if payload.get('state') != 'final':
                    continue
                # extract text
                content = payload.get('message', {}).get('content', [])
                text = ''
                if isinstance(content, str):
                    text = content
                elif isinstance(content, list):
                    parts = []
                    for p in content:
                        if isinstance(p, dict):
                            parts.append(p.get('text') or p.get('content') or '')
                        elif isinstance(p, str):
                            parts.append(p)
                    text = ''.join(parts)
                print('\n[WS] Final reply:')
                print(text)
                return text

        recv_task = asyncio.create_task(receiver())

        # send POST /hooks/agent
        payload = {
            'message': MESSAGE,
            'name': os.environ.get('HOOK_NAME', 'Live2D'),
            'sessionKey': SESSION_KEY,
            'deliver': (os.environ.get('DELIVER', 'false').lower() in ['1','true','yes','y']),
            'wakeMode': os.environ.get('WAKE_MODE', 'next-heartbeat'),
        }
        # optional fields
        ch = os.environ.get('CHANNEL', '')
        if ch:
            payload['channel'] = ch
        m = os.environ.get('MODEL', '')
        if m:
            payload['model'] = m
        th = os.environ.get('THINKING', '')
        if th:
            payload['thinking'] = th
        to = os.environ.get('TIMEOUT_SECONDS', '')
        if to:
            try:
                payload['timeoutSeconds'] = int(to)
            except Exception:
                pass
        headers = {'Content-Type': 'application/json'}
        if TOKEN:
            headers['Authorization'] = f'Bearer {TOKEN}'

        async with httpx.AsyncClient(timeout=15) as client:
            print('[HTTP] POSTing /hooks/agent ->', payload)
            resp = await client.post(f"{BASE_URL}/hooks/agent", headers=headers, json=payload)
            print('[HTTP] status:', resp.status_code)
            try:
                print('[HTTP] body:', resp.json())
            except Exception:
                print('[HTTP] body:', resp.text)

        # wait for receiver to return (or timeout)
        try:
            return await asyncio.wait_for(recv_task, timeout=120)
        except asyncio.TimeoutError:
            print('[WS] Timed out waiting for final event')
            return None


if __name__ == '__main__':
    res = asyncio.run(ws_listen_and_post())
    if res:
        print('\nTest completed: got final reply')
        sys.exit(0)
    else:
        print('\nTest completed: no final reply')
        sys.exit(2)
PY

# export envs for python script
export BASE_URL="$BASE_URL"
export TOKEN="$TOKEN"
export SESSION_KEY="$SESSION_KEY"
export MESSAGE="$MESSAGE"
export DELIVER="$DELIVER"
export WAKE_MODE="$WAKE_MODE"
export CHANNEL="$CHANNEL"
export HOOK_NAME="$HOOK_NAME"
export MODEL="$MODEL"
export THINKING="$THINKING"
export TIMEOUT_SECONDS="$TIMEOUT_SECONDS"

# run using venv python
"$VENV_PY" /tmp/_oc_test.py

# cleanup
rm -f /tmp/_oc_test.py
