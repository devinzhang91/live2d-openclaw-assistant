"""
火山引擎端到端实时语音服务实现

基于 WebSocket 协议，支持低延迟、多模式交互的语音到语音对话
文档: https://www.volcengine.com/docs/6561/1594356

关键协议发现 (来自测试验证):
- 音频帧使用 NO_SEQUENCE flag (0x00)，音频数据需 gzip 压缩
- StartSession 必须包含 system_role、speaking_style、location 等完整配置
- push_to_talk 模式发送完音频后必须发送 END_ASR 信号
"""
import asyncio
import gzip
import json
import struct
import uuid
from typing import Optional

from backend.services.realtime_base import RealtimeCallback, RealtimeSession, RealtimeService

import logging
logger = logging.getLogger("backend.services.realtime_volc")

SUPPORTED_REALTIME_VOICES = {
    "zh_male_yunzhou_jupiter_bigtts",
    "zh_female_xiaohe_jupiter_bigtt",
    "zh_male_xiaotian_jupiter_bigtt",
}
DEFAULT_REALTIME_VOICE = "zh_male_yunzhou_jupiter_bigtts"


# =============================================================================
# 协议常量
# =============================================================================

PROTO_VERSION = 0x1
HEADER_SIZE = 0x1
SERIALIZATION_RAW = 0x0
SERIALIZATION_JSON = 0x1
COMPRESSION_NONE = 0x0
COMPRESSION_GZIP = 0x1

# 消息类型
MSG_TYPE_FULL_CLIENT_REQUEST = 0x01
MSG_TYPE_FULL_SERVER_RESPONSE = 0x09
MSG_TYPE_AUDIO_ONLY_REQUEST = 0x02
MSG_TYPE_AUDIO_ONLY_RESPONSE = 0x0B
MSG_TYPE_ERROR = 0x0F

# Flags
FLAG_NONE = 0x00
FLAG_WITH_EVENT = 0x04
FLAG_WITH_SEQUENCE = 0x01
FLAG_WITH_SEQUENCE_END = 0x02
FLAG_WITH_SEQUENCE_END_NEGATIVE = 0x03

# 客户端事件
EVENT_START_CONNECTION = 1
EVENT_FINISH_CONNECTION = 2
EVENT_START_SESSION = 100
EVENT_FINISH_SESSION = 102
EVENT_TASK_REQUEST = 200
EVENT_END_ASR = 400
EVENT_CHAT_TEXT_QUERY = 501

# 服务端事件
EVENT_CONNECTION_STARTED = 50
EVENT_CONNECTION_FAILED = 51
EVENT_CONNECTION_FINISHED = 52
EVENT_SESSION_STARTED = 150
EVENT_SESSION_FINISHED = 152
EVENT_SESSION_FAILED = 153
EVENT_USAGE_RESPONSE = 154
EVENT_CONFIG_UPDATED = 251
EVENT_TTS_SENTENCE_START = 350
EVENT_TTS_SENTENCE_END = 351
EVENT_TTS_RESPONSE = 352
EVENT_TTS_ENDED = 359
EVENT_ASR_INFO = 450
EVENT_ASR_RESPONSE = 451
EVENT_ASR_ENDED = 459
EVENT_CHAT_RESPONSE = 550
EVENT_CHAT_TEXT_QUERY_CONFIRMED = 553
EVENT_CHAT_ENDED = 559
EVENT_DIALOG_COMMON_ERROR = 599


# =============================================================================
# 协议工具函数
# =============================================================================

def _build_header(
    message_type: int,
    flags: int,
    serialization: int = SERIALIZATION_JSON,
    compression: int = COMPRESSION_NONE,
) -> bytes:
    """构建 4 字节协议头"""
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
    sequence: Optional[int] = None,
    serialization: int = SERIALIZATION_JSON,
    compression: int = COMPRESSION_NONE,
) -> bytes:
    """构建事件消息帧"""
    # 计算 flags
    flags = FLAG_WITH_EVENT
    if sequence is not None:
        if sequence < 0:
            flags |= FLAG_WITH_SEQUENCE_END_NEGATIVE
        elif sequence == 0:
            flags |= FLAG_WITH_SEQUENCE
        else:
            flags |= FLAG_WITH_SEQUENCE_END

    buf = bytearray()
    buf.extend(_build_header(message_type, flags, serialization, compression))

    # Event (必须)
    buf.extend(struct.pack(">i", event))

    # Sequence (可选)
    if sequence is not None:
        buf.extend(struct.pack(">i", sequence))

    # Session ID (Session 类事件)
    if session_id is not None:
        session_bytes = session_id.encode("utf-8")
        buf.extend(struct.pack(">I", len(session_bytes)))
        buf.extend(session_bytes)
    elif event not in {
        EVENT_START_CONNECTION,
        EVENT_FINISH_CONNECTION,
        EVENT_CONNECTION_STARTED,
        EVENT_CONNECTION_FAILED,
        EVENT_CONNECTION_FINISHED,
    }:
        # Session 类事件但没有 session_id
        buf.extend(struct.pack(">I", 0))

    # Payload size + payload
    buf.extend(struct.pack(">I", len(payload)))
    if payload:
        buf.extend(payload)

    return bytes(buf)


def _build_audio_message(
    audio_chunk: bytes,
    session_id: str,
) -> bytes:
    """构建音频数据帧 (Audio-only request)

    协议关键发现 (来自 demo 对比测试):
    - message_type = AUDIO_ONLY_REQUEST (0x02)
    - flags = MSG_WITH_EVENT (0x04) - 不带 sequence，但必须带 event 字段
    - serialization = NO_SERIALIZATION (0x0)
    - compression = GZIP (0x1) - 音频数据必须 gzip 压缩
    """
    flags = FLAG_WITH_EVENT

    buf = bytearray()
    buf.extend(_build_header(MSG_TYPE_AUDIO_ONLY_REQUEST, flags, SERIALIZATION_RAW, COMPRESSION_GZIP))

    # Event
    buf.extend(struct.pack(">i", EVENT_TASK_REQUEST))

    # Session ID
    session_bytes = session_id.encode("utf-8")
    buf.extend(struct.pack(">I", len(session_bytes)))
    buf.extend(session_bytes)

    # Payload size + audio (gzip compressed)
    payload_bytes = gzip.compress(audio_chunk)
    buf.extend(struct.pack(">I", len(payload_bytes)))
    buf.extend(payload_bytes)

    return bytes(buf)


def _parse_message(data: bytes) -> dict:
    """解析接收到的消息帧"""
    if len(data) < 4:
        raise ValueError("Invalid frame: too short")

    proto_version = (data[0] >> 4) & 0x0F
    header_size_bytes = data[0] & 0x0F
    message_type = (data[1] >> 4) & 0x0F
    flags = data[1] & 0x0F
    serialization = (data[2] >> 4) & 0x0F
    compression = data[2] & 0x0F

    offset = header_size_bytes * 4

    event = None
    sequence = None
    session_id = ""
    connect_id = ""
    error_code = None

    # Sequence
    seq_kind = flags & 0x03
    if seq_kind in (0x01, 0x02, 0x03):
        if len(data) < offset + 4:
            raise ValueError("Invalid frame: missing sequence")
        seq_val = struct.unpack(">i", data[offset:offset + 4])[0]
        if seq_kind == 0x03:  # Negative sequence
            sequence = -abs(seq_val)
        else:
            sequence = seq_val
        offset += 4

    # Event
    has_event = (flags & FLAG_WITH_EVENT) != 0
    if has_event:
        if len(data) < offset + 4:
            raise ValueError("Invalid frame: missing event")
        event = struct.unpack(">i", data[offset:offset + 4])[0]
        offset += 4

        if event in {EVENT_CONNECTION_STARTED, EVENT_CONNECTION_FAILED, EVENT_CONNECTION_FINISHED}:
            # Connect 类事件
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
            # Session 类事件
            if len(data) < offset + 4:
                raise ValueError("Invalid frame: missing session_id size")
            session_id_size = struct.unpack(">I", data[offset:offset + 4])[0]
            offset += 4
            if session_id_size > 0:
                if len(data) < offset + session_id_size:
                    raise ValueError("Invalid frame: incomplete session_id")
                session_id = data[offset:offset + session_id_size].decode("utf-8", errors="ignore")
                offset += session_id_size

    # Error code (仅 Error 消息)
    if message_type == MSG_TYPE_ERROR:
        if len(data) < offset + 4:
            raise ValueError("Invalid frame: missing error_code")
        error_code = struct.unpack(">i", data[offset:offset + 4])[0]
        offset += 4

    # Payload
    if len(data) < offset + 4:
        raise ValueError("Invalid frame: missing payload size")
    payload_size = struct.unpack(">I", data[offset:offset + 4])[0]
    offset += 4

    payload = b""
    if payload_size > 0:
        if len(data) < offset + payload_size:
            raise ValueError("Invalid frame: incomplete payload")
        payload = data[offset:offset + payload_size]

    # 解压缩
    if compression == COMPRESSION_GZIP:
        try:
            payload = gzip.decompress(payload)
        except Exception:
            pass  # 忽略解压缩错误

    # JSON 解析
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
        "sequence": sequence,
        "session_id": session_id,
        "connect_id": connect_id,
        "error_code": error_code,
        "payload": payload,
        "payload_json": payload_json,
    }


# =============================================================================
# VolcRealtimeSession
# =============================================================================

class VolcRealtimeSession(RealtimeSession):
    """火山端到端实时语音会话

    生命周期:
      start_session()  → 建立连接，初始化会话
      send_audio()     → 流式发送音频数据
      end_asr()        → 通知音频输入结束 (push_to_talk 模式)
      send_text()      → 发送文本（text 模式）
      finish_session() → 结束会话
      close()          → 关闭连接
    """

    def __init__(
        self,
        session_id: str,
        app_id: str,
        access_key: str,
        resource_id: str,
        app_key: str,
        ws_url: str,
        model: str = "1.2.1.1",
        voice: str = "zh_male_yunzhou_jupiter_bigtts",
        enable_websearch: bool = False,
        enable_music: bool = False,
        input_mod: str = "push_to_talk",
        tts_format: str = "pcm_s16le",
        tts_sample_rate: int = 24000,
        recv_timeout: int = 120,
    ):
        self.session_id = session_id
        self.is_active = False
        self.app_id = app_id
        self.access_key = access_key
        self.resource_id = resource_id
        self.app_key = app_key
        self.ws_url = ws_url
        self.model = model
        self.voice = voice
        self.enable_websearch = enable_websearch
        self.enable_music = enable_music
        self.input_mod = input_mod
        self.tts_format = tts_format
        self.tts_sample_rate = tts_sample_rate
        self.recv_timeout = recv_timeout

        self._ws = None
        self._recv_task: Optional[asyncio.Task] = None
        self._session_finished = asyncio.Event()
        self._session_failed = asyncio.Event()
        self._dialog_id: Optional[str] = None
        self._error_message: Optional[str] = None

    async def start_session(self):
        """启动会话，建立 WebSocket 连接并初始化"""
        if self.is_active:
            return

        try:
            import websockets
        except ImportError:
            raise ImportError("websockets 库未安装，请运行: pip install websockets")

        # WebSocket headers
        headers = {
            "X-Api-App-Key": self.app_key,
            "X-Api-Access-Key": self.access_key,
            "X-Api-Resource-Id": self.resource_id,
            "X-Api-App-ID": self.app_id,
            "X-Api-Connect-Id": str(uuid.uuid4()),
        }

        try:
            # 建立连接
            self._ws = await websockets.connect(
                self.ws_url,
                additional_headers=headers,
                ping_interval=None,
                max_size=50 * 1024 * 1024,  # 50MB
            )

            # 1. StartConnection
            await self._ws.send(
                _build_event_message(
                    message_type=MSG_TYPE_FULL_CLIENT_REQUEST,
                    event=EVENT_START_CONNECTION,
                    payload=b"{}",
                )
            )
            await self._wait_for_event(EVENT_CONNECTION_STARTED, {EVENT_CONNECTION_FAILED})

            # 2. StartSession (包含完整配置，避免 InvalidSpeaker 错误)
            start_payload = {
                "event": EVENT_START_SESSION,
                "namespace": "S2SAudioDialogue",
                "tts": {
                    "audio_config": {
                        "format": self.tts_format,
                        "sample_rate": self.tts_sample_rate,
                        "channel": 1,
                    },
                    "speaker": self.voice,
                },
                "asr": {
                    "extra": {
                        "end_smooth_window_ms": 1500,
                    }
                },
                "dialog": {
                    "bot_name": "豆包",
                    "system_role": "你使用活泼灵动的女声，性格开朗，热爱生活。",
                    "speaking_style": "你的说话风格简洁明了，语速适中，语调自然。",
                    "location": {
                        "city": "北京",
                    },
                    "extra": {
                        "model": self.model,
                        "enable_volc_websearch": self.enable_websearch,
                        "enable_music": self.enable_music,
                        "recv_timeout": self.recv_timeout,
                        "input_mod": self.input_mod,
                    }
                },
            }

            await self._ws.send(
                _build_event_message(
                    message_type=MSG_TYPE_FULL_CLIENT_REQUEST,
                    event=EVENT_START_SESSION,
                    payload=json.dumps(start_payload, ensure_ascii=False).encode("utf-8"),
                    session_id=self.session_id,
                )
            )

            frame = await self._wait_for_event(EVENT_SESSION_STARTED, {EVENT_SESSION_FAILED})
            if frame.get("event") == EVENT_SESSION_FAILED:
                error_msg = self._get_error_message(frame)
                raise RuntimeError(f"Session failed: {error_msg}")

            self._dialog_id = frame.get("payload_json", {}).get("dialog_id")
            self.is_active = True

            logger.info(f"[{self.session_id}] 会话启动成功, dialog_id={self._dialog_id}, input_mod={self.input_mod}, recv_timeout={self.recv_timeout}s")

            # 启动后台接收循环
            self._recv_task = asyncio.create_task(self._recv_loop())

            # 通知会话启动
            self._notify_session_started({"dialog_id": self._dialog_id})

        except Exception:
            await self.close()
            raise

    async def _wait_for_event(self, expected_event: int, error_events: set = None) -> dict:
        """等待特定事件帧（用于握手阶段）"""
        error_events = error_events or set()

        while True:
            frame = await self._read_frame()

            if frame["message_type"] == MSG_TYPE_ERROR:
                error_msg = self._get_error_message(frame)
                raise RuntimeError(f"Connection error: {error_msg}")

            event = frame.get("event")

            if event in error_events:
                error_msg = self._get_error_message(frame)
                err = RuntimeError(f"Connection failed: {error_msg}")
                self._notify_error(err)
                self._session_failed.set()
                raise err

            if event == expected_event:
                return frame

    async def _read_frame(self) -> dict:
        """读取一帧数据"""
        data = await self._ws.recv()
        if isinstance(data, str):
            raise RuntimeError(f"Unexpected text frame: {data}")
        return _parse_message(data)

    def _get_error_message(self, frame: dict) -> str:
        """从错误帧中提取错误信息"""
        if frame.get("payload_json"):
            return frame["payload_json"].get("error", "Unknown error")
        if frame.get("error_code") is not None:
            return f"Error code: {frame['error_code']}"
        return "Unknown error"

    async def _recv_loop(self):
        """后台接收循环，处理所有服务端事件"""
        try:
            while True:
                frame = await self._read_frame()
                msg_type = frame["message_type"]
                event = frame.get("event")

                # 处理不同类型的消息
                if msg_type == MSG_TYPE_ERROR:
                    error_msg = self._get_error_message(frame)
                    self._error_message = error_msg
                    self._notify_session_failed(error_msg)
                    self._session_failed.set()
                    return

                if event == EVENT_SESSION_FAILED:
                    error_msg = self._get_error_message(frame)
                    logger.warning(f"[{self.session_id}] SessionFailed: {error_msg}")
                    self._error_message = error_msg
                    self.is_active = False
                    self._notify_session_failed(error_msg)
                    self._session_failed.set()
                    return

                if event == EVENT_SESSION_FINISHED:
                    logger.info(f"[{self.session_id}] 会话正常结束 (recv_timeout)")
                    self.is_active = False
                    self._notify_session_finished()
                    self._session_finished.set()
                    return

                if event == EVENT_CONNECTION_FAILED:
                    error_msg = self._get_error_message(frame)
                    self._error_message = error_msg
                    self.is_active = False
                    self._notify_error(RuntimeError(f"Connection failed: {error_msg}"))
                    return

                if event == EVENT_CONNECTION_FINISHED:
                    self.is_active = False
                    self._notify_close()
                    return

                # TTS 音频数据
                if msg_type == MSG_TYPE_AUDIO_ONLY_RESPONSE or event == EVENT_TTS_RESPONSE:
                    audio = frame.get("payload", b"")
                    if audio:
                        self._notify_tts_response(audio)
                        logger.debug(f"[{self.session_id}] TTS 音频帧 {len(audio)} bytes")

                # TTS 句子开始
                if event == EVENT_TTS_SENTENCE_START:
                    data = frame.get("payload_json", {})
                    text = data.get("text", "")[:30]
                    logger.debug(f"[{self.session_id}] TTS 句子开始: {text}...")
                    self._notify_tts_sentence_start(data)

                # TTS 句子结束
                if event == EVENT_TTS_SENTENCE_END:
                    data = frame.get("payload_json", {})
                    self._notify_tts_sentence_end(data)

                # TTS 结束
                if event == EVENT_TTS_ENDED:
                    data = frame.get("payload_json", {})
                    logger.info(f"[{self.session_id}] TTS 回复结束")
                    self._notify_tts_ended(data)

                # ASR 识别结果
                if event == EVENT_ASR_RESPONSE:
                    results = frame.get("payload_json", {}).get("results", [])
                    if results:
                        text = results[0].get("text", "")
                        is_interim = results[0].get("is_interim", False)
                        if is_interim:
                            logger.debug(f"[{self.session_id}] ASR interim: {text}")
                        self._notify_asr_response(text, is_interim)

                # 用户说话结束
                if event == EVENT_ASR_ENDED:
                    logger.info(f"[{self.session_id}] ASR 说话结束")
                    self._notify_asr_ended()

                # 模型回复文本
                if event == EVENT_CHAT_RESPONSE:
                    data = frame.get("payload_json", {})
                    content = data.get("content", "")[:30]
                    logger.debug(f"[{self.session_id}] LLM 回复: {content}...")
                    self._notify_chat_response(data)

                # 模型回复结束
                if event == EVENT_CHAT_ENDED:
                    data = frame.get("payload_json", {})
                    logger.info(f"[{self.session_id}] LLM 回复结束")
                    self._notify_chat_ended(data)

        except asyncio.CancelledError:
            return
        except Exception as e:
            self._error_message = str(e)
            self.is_active = False
            self._notify_error(e)

    async def send_audio(self, audio_chunk: bytes):
        """发送音频数据"""
        if not self.is_active or not self._ws:
            raise RuntimeError("Session not active")

        frame = _build_audio_message(
            audio_chunk=audio_chunk,
            session_id=self.session_id,
        )
        try:
            await self._ws.send(frame)
        except Exception as e:
            self._error_message = str(e)
            self.is_active = False
            raise

    async def end_asr(self):
        """发送 END_ASR 信号，通知服务器音频输入结束（push_to_talk 模式）

        关键发现: push_to_talk 模式发送完音频后必须发送 END_ASR，
        否则服务器会报 DialogAudioIdleTimeoutError
        """
        if not self.is_active or not self._ws:
            return

        try:
            await self._ws.send(
                _build_event_message(
                    message_type=MSG_TYPE_FULL_CLIENT_REQUEST,
                    event=EVENT_END_ASR,
                    payload=b"{}",
                    session_id=self.session_id,
                )
            )
        except Exception as e:
            self._error_message = str(e)
            self.is_active = False
            raise

    async def send_text(self, text: str):
        """发送文本（text 模式）"""
        if not self.is_active or not self._ws:
            raise RuntimeError("Session not active")

        payload = {
            "event": EVENT_CHAT_TEXT_QUERY,
            "namespace": "S2SAudioDialogue",
            "req_params": {
                "content": text,
            }
        }

        await self._ws.send(
            _build_event_message(
                message_type=MSG_TYPE_FULL_CLIENT_REQUEST,
                event=EVENT_CHAT_TEXT_QUERY,
                payload=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                session_id=self.session_id,
            )
        )

    async def finish_session(self):
        """结束会话"""
        if not self.is_active or not self._ws:
            return

        await self._ws.send(
            _build_event_message(
                message_type=MSG_TYPE_FULL_CLIENT_REQUEST,
                event=EVENT_FINISH_SESSION,
                payload=b"{}",
                session_id=self.session_id,
            )
        )

        # 等待会话结束
        try:
            await asyncio.wait_for(self._session_finished.wait(), timeout=30.0)
        except asyncio.TimeoutError:
            pass  # 超时继续关闭

    async def close(self):
        """关闭连接"""
        # 取消后台接收任务
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
                    )
                )
            except Exception:
                pass

            await self._ws.close()
        finally:
            self.is_active = False
            self._ws = None
            self._notify_close()


# =============================================================================
# VolcRealtimeService
# =============================================================================

class VolcRealtimeService(RealtimeService):
    """火山端到端实时语音服务

    配置优先级: 构造函数参数 > settings > 默认值

    验证过的音色 ID (必须带 _bigtts 后缀):
    - zh_male_yunzhou_jupiter_bigtts (男声，清爽沉稳)
    - zh_female_xiaohe_jupiter_bigtt (女声，甜美活泼)
    - zh_male_xiaotian_jupiter_bigtt (男声，清爽磁性)
    """

    def __init__(
        self,
        app_id: str = None,
        access_key: str = None,
        resource_id: str = None,
        app_key: str = None,
        ws_url: str = None,
        model: str = None,
        voice: str = None,
        enable_websearch: bool = None,
        enable_music: bool = None,
        input_mod: str = "audio",
        tts_format: str = "pcm_s16le",
        tts_sample_rate: int = 24000,
        recv_timeout: int = 120,
    ):
        def _sanitize_voice(raw_voice: str) -> str:
            candidate = (raw_voice or "").strip()
            if candidate in SUPPORTED_REALTIME_VOICES:
                return candidate
            if candidate:
                logger.warning(
                    "[realtime_volc] Invalid speaker '%s', fallback to '%s'",
                    candidate,
                    DEFAULT_REALTIME_VOICE,
                )
            return DEFAULT_REALTIME_VOICE

        # 加载配置
        try:
            from backend.config.settings import settings
            self.app_id = app_id or getattr(settings, "volc_realtime_app_id", "")
            self.access_key = access_key or getattr(settings, "volc_realtime_access_key", "")
            self.resource_id = resource_id or getattr(settings, "volc_realtime_resource_id", "volc.speech.dialog")
            self.app_key = app_key or getattr(settings, "volc_realtime_app_key", "PlgvMymc7f3tQnJ6")
            self.ws_url = ws_url or getattr(settings, "volc_realtime_ws_url", "wss://openspeech.bytedance.com/api/v3/realtime/dialogue")
            self.model = model or getattr(settings, "volc_realtime_model", "1.2.1.1")
            configured_voice = voice or getattr(settings, "volc_realtime_voice", DEFAULT_REALTIME_VOICE)
            self.voice = _sanitize_voice(configured_voice)
            self.enable_websearch = enable_websearch if enable_websearch is not None else getattr(settings, "volc_realtime_enable_websearch", False)
            self.enable_music = enable_music if enable_music is not None else getattr(settings, "volc_realtime_enable_music", False)
        except (ImportError, AttributeError):
            self.app_id = app_id or ""
            self.access_key = access_key or ""
            self.resource_id = resource_id or "volc.speech.dialog"
            self.app_key = app_key or "PlgvMymc7f3tQnJ6"
            self.ws_url = ws_url or "wss://openspeech.bytedance.com/api/v3/realtime/dialogue"
            self.model = model or "1.2.1.1"
            self.voice = _sanitize_voice(voice or DEFAULT_REALTIME_VOICE)
            self.enable_websearch = enable_websearch or False
            self.enable_music = enable_music or False

        self.input_mod = input_mod
        self.tts_format = tts_format
        self.tts_sample_rate = tts_sample_rate
        self.recv_timeout = recv_timeout

    async def create_session(
        self,
        session_id: str,
        config: dict = None,
        callback: RealtimeCallback = None,
    ) -> VolcRealtimeSession:
        """创建端到端实时语音会话"""
        config = config or {}

        session = VolcRealtimeSession(
            session_id=session_id,
            app_id=config.get("app_id", self.app_id),
            access_key=config.get("access_key", self.access_key),
            resource_id=config.get("resource_id", self.resource_id),
            app_key=config.get("app_key", self.app_key),
            ws_url=config.get("ws_url", self.ws_url),
            model=config.get("model", self.model),
            voice=config.get("voice", self.voice),
            enable_websearch=config.get("enable_websearch", self.enable_websearch),
            enable_music=config.get("enable_music", self.enable_music),
            input_mod=config.get("input_mod", self.input_mod),
            tts_format=config.get("tts_format", self.tts_format),
            tts_sample_rate=config.get("tts_sample_rate", self.tts_sample_rate),
            recv_timeout=config.get("recv_timeout", self.recv_timeout),
        )

        if callback:
            session.set_callback(callback)

        await session.start_session()

        # 通知会话启动（回调在 start_session 内部调用）
        return session
