"""
火山引擎 TTS 服务实现（V3 双向流式）

架构亮点：
  - VolcTTSSession 内部持有一个后台 _recv_loop Task，持续收音频帧入队。
  - send_task(text) 只发 TaskRequest，立即返回，不阻塞。
  - finish_session() 发 FinishSession 后等待 _session_finished 事件（由 recv loop 触发）。
  - get_audio_chunks() 是异步生成器，从队列逐帧产出，直到收到 None 哨兵。

这使得外部可以把 LLM token 流直接喂给 send_task()，同时并发地从
get_audio_chunks() 读取并转发音频，实现最低首字延时。
"""
import asyncio
import json
import struct
import uuid
from typing import AsyncGenerator, Optional

from backend.services.tts_base import TTSService, TTSSession, TTSStreamCallback


# 协议常量
PROTO_VERSION = 0x1
HEADER_SIZE = 0x1
SERIALIZATION_RAW = 0x0
SERIALIZATION_JSON = 0x1
COMPRESSION_NONE = 0x0

# 消息类型
MSG_TYPE_FULL_CLIENT_REQUEST = 0x01
MSG_TYPE_FULL_SERVER_RESPONSE = 0x09
MSG_TYPE_AUDIO_ONLY_RESPONSE = 0x0B
MSG_TYPE_ERROR = 0x0F

# 标志位
FLAG_NONE = 0x00
FLAG_WITH_EVENT = 0x04

# Event 定义
EVENT_START_CONNECTION = 1
EVENT_FINISH_CONNECTION = 2
EVENT_CONNECTION_STARTED = 50
EVENT_CONNECTION_FAILED = 51
EVENT_CONNECTION_FINISHED = 52
EVENT_START_SESSION = 100
EVENT_FINISH_SESSION = 102
EVENT_SESSION_STARTED = 150
EVENT_SESSION_FINISHED = 152
EVENT_SESSION_FAILED = 153
EVENT_TASK_REQUEST = 200
EVENT_TTS_RESPONSE = 352


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))


def _speed_ratio_to_speech_rate(speed_ratio: float) -> int:
    if speed_ratio is None:
        return 0
    return _clamp(int(round((speed_ratio - 1.0) * 100)), -50, 100)


def _default_resource_id(voice_type: str) -> str:
    if voice_type and voice_type.startswith("S_"):
        return "volc.megatts.default"
    return "volc.service_type.10029"


def _build_header(
    message_type: int,
    flags: int,
    serialization: int = SERIALIZATION_JSON,
    compression: int = COMPRESSION_NONE,
) -> bytes:
    byte0 = (PROTO_VERSION << 4) | HEADER_SIZE
    byte1 = (message_type << 4) | flags
    byte2 = (serialization << 4) | compression
    byte3 = 0x00
    return bytes([byte0, byte1, byte2, byte3])


def _build_event_message(
    message_type: int,
    event: int,
    payload: bytes,
    session_id: Optional[str] = None,
    serialization: int = SERIALIZATION_JSON,
    compression: int = COMPRESSION_NONE,
) -> bytes:
    buf = bytearray()
    buf.extend(_build_header(message_type, FLAG_WITH_EVENT, serialization, compression))
    buf.extend(struct.pack(">i", event))

    # Connection 类事件不带 session_id
    if event not in {
        EVENT_START_CONNECTION,
        EVENT_FINISH_CONNECTION,
        EVENT_CONNECTION_STARTED,
        EVENT_CONNECTION_FAILED,
        EVENT_CONNECTION_FINISHED,
    }:
        session_bytes = (session_id or "").encode("utf-8")
        buf.extend(struct.pack(">I", len(session_bytes)))
        if session_bytes:
            buf.extend(session_bytes)

    buf.extend(struct.pack(">I", len(payload)))
    if payload:
        buf.extend(payload)
    return bytes(buf)


def _parse_message(data: bytes) -> dict:
    if len(data) < 8:
        raise ValueError("Invalid frame: too short")

    header_size = data[0] & 0x0F
    message_type = (data[1] >> 4) & 0x0F
    flags = data[1] & 0x0F
    serialization = (data[2] >> 4) & 0x0F
    compression = data[2] & 0x0F

    offset = header_size * 4
    event = None
    session_id = ""
    connect_id = ""
    error_code = None

    # 兼容 sequence 帧（当前 TTS 主链路不依赖）
    seq_kind = flags & 0x03
    if seq_kind in (0x01, 0x03):
        if len(data) < offset + 4:
            raise ValueError("Invalid frame: missing sequence")
        offset += 4

    has_event = (flags & FLAG_WITH_EVENT) != 0
    if has_event:
        if len(data) < offset + 4:
            raise ValueError("Invalid frame: missing event")
        event = struct.unpack(">i", data[offset:offset + 4])[0]
        offset += 4

        if event in {EVENT_CONNECTION_STARTED, EVENT_CONNECTION_FAILED, EVENT_CONNECTION_FINISHED}:
            if len(data) < offset + 4:
                raise ValueError("Invalid frame: missing connect_id size")
            connect_id_size = struct.unpack(">I", data[offset:offset + 4])[0]
            offset += 4
            if connect_id_size > 0:
                if len(data) < offset + connect_id_size:
                    raise ValueError("Invalid frame: incomplete connect_id")
                connect_id = data[offset:offset + connect_id_size].decode("utf-8", errors="ignore")
                offset += connect_id_size
        elif event is not None:
            if len(data) < offset + 4:
                raise ValueError("Invalid frame: missing session_id size")
            session_id_size = struct.unpack(">I", data[offset:offset + 4])[0]
            offset += 4
            if session_id_size > 0:
                if len(data) < offset + session_id_size:
                    raise ValueError("Invalid frame: incomplete session_id")
                session_id = data[offset:offset + session_id_size].decode("utf-8", errors="ignore")
                offset += session_id_size

    if message_type == MSG_TYPE_ERROR:
        if len(data) < offset + 8:
            raise ValueError("Invalid error frame")
        error_code = struct.unpack(">i", data[offset:offset + 4])[0]
        offset += 4

    if len(data) < offset + 4:
        raise ValueError("Invalid frame: missing payload size")

    payload_size = struct.unpack(">I", data[offset:offset + 4])[0]
    offset += 4

    if len(data) < offset + payload_size:
        raise ValueError("Invalid frame: incomplete payload")

    payload = data[offset:offset + payload_size]

    if compression != COMPRESSION_NONE:
        # 当前实现按官方 demo 使用 no compression
        raise ValueError(f"Unsupported compression: {compression}")

    payload_json = None
    if serialization == SERIALIZATION_JSON and payload:
        try:
            payload_json = json.loads(payload.decode("utf-8"))
        except Exception:
            payload_json = None

    return {
        "message_type": message_type,
        "flags": flags,
        "serialization": serialization,
        "compression": compression,
        "event": event,
        "session_id": session_id,
        "connect_id": connect_id,
        "error_code": error_code,
        "payload": payload,
        "payload_json": payload_json,
    }


class VolcTTSSession(TTSSession):
    """火山引擎 TTS V3 双向流式会话

    生命周期:
      start()            ── 握手完成后启动后台 _recv_loop Task
      send_task(text)    ── 发 TaskRequest，立即返回（不等服务器）
      finish_session()   ── 发 FinishSession，等待 _session_finished 事件
      get_audio_chunks() ── 异步生成器，从 _audio_queue 取帧，None 为结束哨兵
      close()            ── 取消 recv_loop，发 FinishConnection，关闭 WS

    兼容接口:
      send_text(text)    ── send_task + finish_session（一次性合成整段文本）
      get_audio_stream() ── 等同 get_audio_chunks()
    """

    def __init__(
        self,
        session_id: str,
        app_id: str,
        access_token: str,
        ws_url: str,
        resource_id: str,
        voice_type: str = "zh_female_cancan_mars_bigtts",
        encoding: str = "mp3",
        speed_ratio: float = 1.0,
    ):
        super().__init__(session_id)
        self.app_id = app_id
        self.access_token = access_token
        self.ws_url = ws_url
        self.resource_id = resource_id or _default_resource_id(voice_type)
        self.voice_type = voice_type
        self.encoding = encoding
        self.speed_ratio = speed_ratio

        self._ws = None
        self._audio_queue: asyncio.Queue = asyncio.Queue()
        self._recv_task: Optional[asyncio.Task] = None
        self._session_finished = asyncio.Event()
        self._synthesis_error: Optional[Exception] = None

    # ------------------------------------------------------------------
    # 连接握手
    # ------------------------------------------------------------------

    async def start(self):
        if self.is_active:
            return

        try:
            import websockets
        except ImportError:
            raise ImportError("websockets 库未安装，请运行: pip install websockets")

        headers = {
            "X-Api-App-Key": self.app_id,
            "X-Api-Access-Key": self.access_token,
            "X-Api-Resource-Id": self.resource_id,
            "X-Api-Connect-Id": str(uuid.uuid4()),
        }

        try:
            self._ws = await websockets.connect(
                self.ws_url,
                additional_headers=headers,
                ping_interval=None,
                max_size=10 * 1024 * 1024,
            )

            # StartConnection
            await self._ws.send(
                _build_event_message(
                    message_type=MSG_TYPE_FULL_CLIENT_REQUEST,
                    event=EVENT_START_CONNECTION,
                    payload=b"{}",
                    serialization=SERIALIZATION_JSON,
                )
            )
            await self._wait_event(EVENT_CONNECTION_STARTED)

            # StartSession
            start_payload = {
                "user": {"uid": self.session_id},
                "event": EVENT_START_SESSION,
                "namespace": "BidirectionalTTS",
                "req_params": {
                    "speaker": self.voice_type,
                    "audio_params": {
                        "format": self.encoding,
                        "sample_rate": 24000,
                        "speech_rate": _speed_ratio_to_speech_rate(self.speed_ratio),
                    },
                    "additions": json.dumps({"disable_markdown_filter": True}),
                },
            }

            await self._ws.send(
                _build_event_message(
                    message_type=MSG_TYPE_FULL_CLIENT_REQUEST,
                    event=EVENT_START_SESSION,
                    payload=json.dumps(start_payload, ensure_ascii=False).encode("utf-8"),
                    session_id=self.session_id,
                    serialization=SERIALIZATION_JSON,
                )
            )
            await self._wait_event(EVENT_SESSION_STARTED)

            self.is_active = True

            # 启动后台接收循环
            self._recv_task = asyncio.create_task(self._recv_loop())

        except Exception:
            await self.close()
            raise

    async def _wait_event(self, expected_event: int) -> dict:
        """在握手阶段（recv_loop 启动前）同步等待特定事件帧"""
        while True:
            frame = await self._read_frame()
            event = frame.get("event")

            if frame["message_type"] == MSG_TYPE_ERROR:
                message = "Unknown error"
                if frame.get("payload_json"):
                    message = frame["payload_json"].get("message", message)
                raise RuntimeError(f"TTS Error(code={frame.get('error_code')}): {message}")

            if event == expected_event:
                return frame

            if event in {EVENT_CONNECTION_FAILED, EVENT_SESSION_FAILED}:
                message = "Connection/Session failed"
                if frame.get("payload_json"):
                    message = frame["payload_json"].get("message", message)
                raise RuntimeError(message)

    async def _read_frame(self) -> dict:
        data = await self._ws.recv()
        if isinstance(data, str):
            raise RuntimeError(f"Unexpected text frame: {data}")
        return _parse_message(data)

    # ------------------------------------------------------------------
    # 后台接收循环
    # ------------------------------------------------------------------

    async def _recv_loop(self):
        """持续从 WebSocket 读帧，将音频入队，SessionFinished 时放 None 哨兵"""
        try:
            while True:
                frame = await self._read_frame()
                msg_type = frame["message_type"]
                event = frame.get("event")

                if msg_type == MSG_TYPE_AUDIO_ONLY_RESPONSE:
                    audio = frame.get("payload", b"")
                    if audio:
                        self._audio_queue.put_nowait(audio)
                        self._notify_audio_chunk(audio)
                    continue

                if msg_type == MSG_TYPE_ERROR:
                    message = "Unknown error"
                    if frame.get("payload_json"):
                        message = frame["payload_json"].get("message", message)
                    err = RuntimeError(f"TTS Error(code={frame.get('error_code')}): {message}")
                    self._synthesis_error = err
                    self._session_finished.set()
                    self._audio_queue.put_nowait(None)
                    self._notify_error(err)
                    return

                if event == EVENT_SESSION_FAILED:
                    message = "Session failed"
                    if frame.get("payload_json"):
                        message = frame["payload_json"].get("message", message)
                    err = RuntimeError(message)
                    self._synthesis_error = err
                    self._session_finished.set()
                    self._audio_queue.put_nowait(None)
                    self._notify_error(err)
                    return

                if event == EVENT_SESSION_FINISHED:
                    self._session_finished.set()
                    self._audio_queue.put_nowait(None)
                    self._notify_complete()
                    return

        except asyncio.CancelledError:
            # close() 中取消此 task，正常退出
            return
        except Exception as e:
            self._synthesis_error = e
            self._session_finished.set()
            self._audio_queue.put_nowait(None)
            self._notify_error(e)

    # ------------------------------------------------------------------
    # 发送 API
    # ------------------------------------------------------------------

    async def send_task(self, text: str):
        """发 TaskRequest，立即返回，不等服务器响应。
        可多次调用以向同一 session 流式喂入文本。"""
        if not self.is_active or not self._ws:
            raise RuntimeError("Session not active")

        task_payload = {
            "event": EVENT_TASK_REQUEST,
            "namespace": "BidirectionalTTS",
            "req_params": {"text": text},
        }
        await self._ws.send(
            _build_event_message(
                message_type=MSG_TYPE_FULL_CLIENT_REQUEST,
                event=EVENT_TASK_REQUEST,
                payload=json.dumps(task_payload, ensure_ascii=False).encode("utf-8"),
                session_id=self.session_id,
                serialization=SERIALIZATION_JSON,
            )
        )

    async def finish_session(self):
        """发 FinishSession，阻塞至 _recv_loop 触发 _session_finished 事件"""
        if not self.is_active or not self._ws:
            return

        await self._ws.send(
            _build_event_message(
                message_type=MSG_TYPE_FULL_CLIENT_REQUEST,
                event=EVENT_FINISH_SESSION,
                payload=b"{}",
                session_id=self.session_id,
                serialization=SERIALIZATION_JSON,
            )
        )
        await self._session_finished.wait()

    async def send_text(self, text: str):
        """兼容接口：send_task + finish_session（一次性合成整段文本）"""
        await self.send_task(text)
        await self.finish_session()

    # ------------------------------------------------------------------
    # 音频读取
    # ------------------------------------------------------------------

    async def get_audio_chunks(self) -> AsyncGenerator[bytes, None]:
        """从 _audio_queue 逐帧产出，None 为结束哨兵"""
        while True:
            chunk = await self._audio_queue.get()
            if chunk is None:
                if self._synthesis_error:
                    raise self._synthesis_error
                return
            yield chunk

    async def get_audio_stream(self) -> AsyncGenerator[bytes, None]:
        """get_audio_chunks 的别名，保持向后兼容"""
        async for chunk in self.get_audio_chunks():
            yield chunk

    # ------------------------------------------------------------------
    # 关闭
    # ------------------------------------------------------------------

    async def close(self):
        # 取消后台接收 task
        if self._recv_task and not self._recv_task.done():
            self._recv_task.cancel()
            try:
                await self._recv_task
            except (asyncio.CancelledError, Exception):
                pass

        if not self._ws:
            self.is_active = False
            return

        try:
            try:
                await self._ws.send(
                    _build_event_message(
                        message_type=MSG_TYPE_FULL_CLIENT_REQUEST,
                        event=EVENT_FINISH_CONNECTION,
                        payload=b"{}",
                        serialization=SERIALIZATION_JSON,
                    )
                )
            except Exception:
                pass

            await self._ws.close()
        finally:
            self.is_active = False
            self._ws = None
            self._notify_close()


class VolcTTSService(TTSService):
    """火山引擎 TTS 服务（V3 双向流式）"""

    def __init__(
        self,
        app_id: str = None,
        access_token: str = None,
        ws_url: str = None,
        resource_id: str = None,
        voice_type: str = None,
        encoding: str = "mp3",
        speed_ratio: float = 1.0,
    ):
        super().__init__()

        default_url = "wss://openspeech.bytedance.com/api/v3/tts/bidirection"

        try:
            from backend.config.settings import settings
            self.app_id = app_id or getattr(settings, "volc_tts_app_id", "")
            self.access_token = access_token or getattr(settings, "volc_tts_access_token", "")
            self.ws_url = ws_url or getattr(settings, "volc_tts_ws_url", default_url)
            self.voice_type = voice_type or getattr(
                settings,
                "volc_tts_voice_type",
                "zh_female_cancan_mars_bigtts",
            )
            setting_resource_id = getattr(settings, "volc_tts_resource_id", "")
            self.resource_id = resource_id or setting_resource_id or _default_resource_id(self.voice_type)
        except (ImportError, AttributeError):
            self.app_id = app_id or ""
            self.access_token = access_token or ""
            self.ws_url = ws_url or default_url
            self.voice_type = voice_type or "zh_female_cancan_mars_bigtts"
            self.resource_id = resource_id or _default_resource_id(self.voice_type)

        self.encoding = encoding
        self.speed_ratio = speed_ratio
        self.sample_rate = 24000

    async def _synthesize_text_internal(
        self,
        text: str,
        voice: str = None,
        speed_ratio: float = None,
    ) -> bytes:
        all_audio = bytearray()

        session = VolcTTSSession(
            session_id=str(uuid.uuid4()),
            app_id=self.app_id,
            access_token=self.access_token,
            ws_url=self.ws_url,
            resource_id=self.resource_id,
            voice_type=voice or self.voice_type,
            encoding=self.encoding,
            speed_ratio=speed_ratio if speed_ratio is not None else self.speed_ratio,
        )

        try:
            await session.start()
            await session.send_text(text)
            async for chunk in session.get_audio_stream():
                all_audio.extend(chunk)
        finally:
            await session.close()

        return bytes(all_audio)

    async def synthesize_text(
        self,
        text: str,
        voice: str = None,
        speed_ratio: float = None,
    ) -> bytes:
        return await self._synthesize_text_internal(text, voice, speed_ratio)

    async def synthesize_stream(
        self,
        text_stream: AsyncGenerator[str, None],
        voice: str = None,
    ) -> AsyncGenerator[bytes, None]:
        async for text in text_stream:
            if not text.strip():
                continue
            audio = await self._synthesize_text_internal(text, voice)
            yield audio

    async def create_session(
        self,
        session_id: str,
        voice: str = None,
        speed_ratio: float = None,
        encoding: Optional[str] = None,
        callback: Optional[TTSStreamCallback] = None,
    ) -> VolcTTSSession:
        session = VolcTTSSession(
            session_id=session_id,
            app_id=self.app_id,
            access_token=self.access_token,
            ws_url=self.ws_url,
            resource_id=self.resource_id,
            voice_type=voice or self.voice_type,
            encoding=encoding or self.encoding,
            speed_ratio=speed_ratio if speed_ratio is not None else self.speed_ratio,
        )

        if callback:
            session.set_callback(callback)

        await session.start()
        return session
