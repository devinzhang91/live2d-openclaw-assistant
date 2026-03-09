# -*- coding: utf-8 -*-
"""
OpenClaw WS Service

基于 OpenClaw Gateway 的 WS RPC 通信：
- connect.challenge -> connect 握手（带 device identity）
- chat.send 发送任务
- event.chat(state=final) 获取最终回复

对外保持兼容接口：
- await openclaw_service.call_agent(message) -> str | None
- await openclaw_service.close()
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import time
import uuid
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

import aiohttp
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from backend.config.config_manager import config_manager


def _now_ms() -> int:
    return int(time.time() * 1000)


def _ts() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


class OpenClawService:
    """OpenClaw websocket client (persistent connection + RPC/event routing)."""

    def __init__(self):
        self._session: Optional[aiohttp.ClientSession] = None
        self._ws: Optional[aiohttp.ClientWebSocketResponse] = None
        self._recv_task: Optional[asyncio.Task] = None
        self._conn_lock = asyncio.Lock()

        self._rpc_waiters: dict[str, asyncio.Future] = {}
        self._task_waiters: dict[str, asyncio.Future] = {}

        self._connect_nonce: str = ""
        self._hello_ok = asyncio.Event()

        self._connected = False

        self._base_url = ""
        self._ws_url = ""
        self._origin = ""
        self._token = ""
        self._timeout = 120
        self._session_key = "live2d-ai"

        self._device_id = ""
        self._device_public_key_raw_b64url = ""
        self._device_private_key: Optional[Ed25519PrivateKey] = None

    async def call_agent(self, message: str) -> Optional[str]:
        """Send a message via WS chat.send and wait for final chat event text."""
        if not config_manager.is_openclaw_enabled():
            return None

        try:
            await self._ensure_connected()
            return await self._send_task_and_wait_final(message)
        except asyncio.TimeoutError:
            return f"⏳ OpenClaw 请求超时（>{self._timeout}s），请检查服务状态。"
        except Exception as exc:
            print(f"[OpenClaw] [{_ts()}] WS 调用异常: {exc}")
            return f"❌ OpenClaw 连接失败: {exc}"

    async def close(self):
        """Close websocket and wake pending futures."""
        if self._recv_task and not self._recv_task.done():
            self._recv_task.cancel()
            try:
                await self._recv_task
            except Exception:
                pass

        if self._ws and not self._ws.closed:
            await self._ws.close()

        if self._session and not self._session.closed:
            await self._session.close()

        self._ws = None
        self._session = None
        self._recv_task = None
        self._connected = False

        self._wake_all_waiters(RuntimeError("OpenClaw client closed"))

    async def _ensure_connected(self):
        if self._connected and self._ws and not self._ws.closed:
            return

        async with self._conn_lock:
            if self._connected and self._ws and not self._ws.closed:
                return

            self._load_config()
            self._load_or_create_identity()

            await self._cleanup_before_reconnect()

            headers = {"Origin": self._origin} if self._origin else None
            self._session = aiohttp.ClientSession()
            self._ws = await self._session.ws_connect(
                self._ws_url,
                headers=headers,
                heartbeat=30,
            )

            self._connect_nonce = ""
            self._hello_ok.clear()
            self._recv_task = asyncio.create_task(self._recv_loop())

            await self._wait_for_challenge(timeout=10)
            await self._connect_handshake(timeout=15)

            self._connected = True
            print(f"[OpenClaw] [{_ts()}] WS connected: {self._ws_url}")

    def _load_config(self):
        self._base_url = config_manager.get_openclaw_base_url()
        parsed = urlparse(self._base_url)

        scheme = "wss" if parsed.scheme == "https" else "ws"
        self._ws_url = f"{scheme}://{parsed.netloc}"
        self._origin = f"{parsed.scheme}://{parsed.netloc}"

        self._token = config_manager.get_openclaw_token()
        self._timeout = int(config_manager.get_openclaw_timeout())
        self._session_key = config_manager.get_openclaw_session_key() or "live2d-ai"

    def _identity_path(self) -> Path:
        path_str = os.getenv(
            "OPENCLAW_DEVICE_IDENTITY_PATH",
            "~/.openclaw/identity/device.json",
        )
        return Path(os.path.expanduser(path_str))

    def _load_or_create_identity(self):
        path = self._identity_path()
        path.parent.mkdir(parents=True, exist_ok=True)

        if path.exists():
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                private_key_pem = str(payload.get("private_key_pem", "")).strip()
                if private_key_pem:
                    private_key = serialization.load_pem_private_key(
                        private_key_pem.encode("utf-8"),
                        password=None,
                    )
                    if isinstance(private_key, Ed25519PrivateKey):
                        public_key_raw = private_key.public_key().public_bytes(
                            encoding=serialization.Encoding.Raw,
                            format=serialization.PublicFormat.Raw,
                        )
                        self._device_private_key = private_key
                        self._device_id = hashlib.sha256(public_key_raw).hexdigest()
                        self._device_public_key_raw_b64url = _b64url(public_key_raw)
                        return
            except Exception as exc:
                print(f"[OpenClaw] [{_ts()}] 读取 identity 失败，将重建: {exc}")

        private_key = Ed25519PrivateKey.generate()
        public_key_raw = private_key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        device_id = hashlib.sha256(public_key_raw).hexdigest()

        public_key_pem = private_key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode("utf-8")
        private_key_pem = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ).decode("utf-8")

        data = {
            "version": 1,
            "device_id": device_id,
            "public_key_pem": public_key_pem,
            "private_key_pem": private_key_pem,
            "created_at_ms": _now_ms(),
        }
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass

        self._device_private_key = private_key
        self._device_id = device_id
        self._device_public_key_raw_b64url = _b64url(public_key_raw)

    async def _cleanup_before_reconnect(self):
        if self._recv_task and not self._recv_task.done():
            self._recv_task.cancel()
            try:
                await self._recv_task
            except Exception:
                pass

        if self._ws and not self._ws.closed:
            await self._ws.close()

        if self._session and not self._session.closed:
            await self._session.close()

        self._ws = None
        self._session = None
        self._recv_task = None
        self._connected = False

        self._wake_all_waiters(RuntimeError("OpenClaw reconnecting"))

    async def _wait_for_challenge(self, timeout: float):
        deadline = time.monotonic() + timeout
        while not self._connect_nonce:
            if time.monotonic() > deadline:
                raise TimeoutError("OpenClaw connect.challenge timeout")
            await asyncio.sleep(0.05)

    def _build_device_signature_payload(
        self,
        *,
        device_id: str,
        client_id: str,
        client_mode: str,
        role: str,
        scopes: list[str],
        signed_at_ms: int,
        token: str,
        nonce: str,
    ) -> str:
        return "|".join(
            [
                "v2",
                device_id,
                client_id,
                client_mode,
                role,
                ",".join(scopes),
                str(signed_at_ms),
                token or "",
                nonce,
            ]
        )

    def _build_device_payload(
        self,
        *,
        client_id: str,
        client_mode: str,
        scopes: list[str],
        token: str,
        nonce: str,
    ) -> dict[str, Any]:
        if not self._device_private_key:
            raise RuntimeError("Device identity not loaded")

        signed_at_ms = _now_ms()
        payload = self._build_device_signature_payload(
            device_id=self._device_id,
            client_id=client_id,
            client_mode=client_mode,
            role="operator",
            scopes=scopes,
            signed_at_ms=signed_at_ms,
            token=token,
            nonce=nonce,
        )
        signature = self._device_private_key.sign(payload.encode("utf-8"))
        return {
            "id": self._device_id,
            "publicKey": self._device_public_key_raw_b64url,
            "signature": _b64url(signature),
            "signedAt": signed_at_ms,
            "nonce": nonce,
        }

    async def _connect_handshake(self, timeout: float):
        scopes_env = os.getenv("OPENCLAW_GATEWAY_SCOPES", "operator.admin")
        scopes = [x.strip() for x in scopes_env.split(",") if x.strip()]

        client_id = os.getenv("OPENCLAW_GATEWAY_CLIENT_ID", "openclaw-control-ui")
        client_mode = os.getenv("OPENCLAW_GATEWAY_CLIENT_MODE", "ui")

        params: dict[str, Any] = {
            "minProtocol": 3,
            "maxProtocol": 3,
            "client": {
                "id": client_id,
                "version": "1.0.0",
                "platform": "live2d-ai-assistant",
                "mode": client_mode,
                "instanceId": "live2d-ai-assistant",
            },
            "role": "operator",
            "scopes": scopes,
            "caps": [],
            "locale": "zh-CN",
            "device": self._build_device_payload(
                client_id=client_id,
                client_mode=client_mode,
                scopes=scopes,
                token=self._token,
                nonce=self._connect_nonce,
            ),
        }

        if self._token:
            params["auth"] = {"token": self._token}

        res = await self._rpc("connect", params=params, timeout_s=timeout)
        if isinstance(res, dict) and res.get("type") == "hello-ok":
            self._hello_ok.set()

        await asyncio.wait_for(self._hello_ok.wait(), timeout=timeout)

    async def _send_task_and_wait_final(self, message: str) -> str:
        task_id = str(uuid.uuid4())
        fut = asyncio.get_running_loop().create_future()
        self._task_waiters[task_id] = fut

        payload = {
            "sessionKey": self._normalize_chat_session_key(self._session_key),
            "message": message,
            "deliver": False,
            "idempotencyKey": task_id,
        }

        print(
            f"[OpenClaw] [{_ts()}] WS chat.send payload="
            f"{json.dumps(payload, ensure_ascii=False)}"
        )

        try:
            await self._rpc("chat.send", params=payload, timeout_s=15)
            result = await asyncio.wait_for(fut, timeout=self._timeout)
            return str(result)
        finally:
            self._task_waiters.pop(task_id, None)

    async def _rpc(self, method: str, params: Any, timeout_s: float) -> Any:
        if not self._ws or self._ws.closed:
            raise RuntimeError("OpenClaw WS 未连接")

        req_id = str(uuid.uuid4())
        fut = asyncio.get_running_loop().create_future()
        self._rpc_waiters[req_id] = fut

        frame = {
            "type": "req",
            "id": req_id,
            "method": method,
            "params": params,
        }
        await self._ws.send_str(json.dumps(frame, ensure_ascii=False))

        try:
            return await asyncio.wait_for(fut, timeout=timeout_s)
        finally:
            self._rpc_waiters.pop(req_id, None)

    async def _recv_loop(self):
        try:
            assert self._ws is not None
            async for msg in self._ws:
                if msg.type != aiohttp.WSMsgType.TEXT:
                    continue
                await self._handle_frame(str(msg.data))
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            print(f"[OpenClaw] [{_ts()}] WS recv loop error: {exc}")
        finally:
            self._connected = False
            self._wake_all_waiters(RuntimeError("OpenClaw WS disconnected"))

    async def _handle_frame(self, raw: str):
        try:
            frame = json.loads(raw)
        except Exception:
            return

        frame_type = frame.get("type")

        if frame_type == "res":
            req_id = str(frame.get("id", ""))
            fut = self._rpc_waiters.get(req_id)
            if fut and not fut.done():
                if frame.get("ok"):
                    fut.set_result(frame.get("payload"))
                else:
                    err = frame.get("error")
                    fut.set_exception(RuntimeError(str(err) if err else "rpc failed"))
            return

        if frame_type == "event":
            event = frame.get("event")
            payload = frame.get("payload")

            if event == "connect.challenge" and isinstance(payload, dict):
                self._connect_nonce = str(payload.get("nonce", "")).strip()
                return

            if event == "chat" and isinstance(payload, dict):
                await self._handle_chat_event(payload)
                return

        if frame_type == "hello-ok":
            self._hello_ok.set()

    async def _handle_chat_event(self, payload: dict[str, Any]):
        state = payload.get("state")
        if state and state != "final":
            return

        session_key = str(payload.get("sessionKey", ""))
        expected = self._normalize_chat_session_key(self._session_key)
        if session_key and expected and session_key != expected:
            return

        task_id = ""
        for key in ("idempotencyKey", "taskId", "id"):
            val = payload.get(key)
            if isinstance(val, str) and val:
                task_id = val
                break

        text = self._extract_text(payload.get("message"))

        if task_id and task_id in self._task_waiters:
            fut = self._task_waiters.get(task_id)
            if fut and not fut.done():
                fut.set_result(text)
            return

        # 兼容某些网关版本不回传 idempotencyKey：仅在单 pending 时兜底
        if len(self._task_waiters) == 1:
            _, fut = next(iter(self._task_waiters.items()))
            if fut and not fut.done():
                fut.set_result(text)

    def _extract_text(self, message: Any) -> str:
        if isinstance(message, str):
            return message.strip()

        if isinstance(message, dict):
            content = message.get("content")
            if isinstance(content, str):
                return content.strip()
            if isinstance(content, list):
                parts: list[str] = []
                for part in content:
                    if isinstance(part, dict):
                        txt = part.get("text") or part.get("content") or ""
                        if isinstance(txt, str):
                            parts.append(txt)
                    elif isinstance(part, str):
                        parts.append(part)
                return "".join(parts).strip()
            if isinstance(message.get("text"), str):
                return str(message.get("text", "")).strip()
            if "message" in message:
                return self._extract_text(message.get("message"))

        if isinstance(message, list):
            parts = []
            for item in message:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict):
                    txt = item.get("text") or item.get("content") or ""
                    if isinstance(txt, str):
                        parts.append(txt)
            return "".join(parts).strip()

        return ""

    def _wake_all_waiters(self, exc: Exception):
        for fut in list(self._rpc_waiters.values()):
            if not fut.done():
                fut.set_exception(exc)
        for fut in list(self._task_waiters.values()):
            if not fut.done():
                fut.set_exception(exc)

    @staticmethod
    def _normalize_chat_session_key(session_key: str) -> str:
        key = (session_key or "").strip()
        if not key:
            return "agent:main:main"
        if ":" in key:
            return key
        return f"agent:main:{key}"


openclaw_service = OpenClawService()
