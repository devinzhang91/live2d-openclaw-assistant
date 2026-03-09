"""
火山引擎流式 ASR 服务实现
基于测试成功的实现重写
"""
import asyncio
import json
import gzip
import numpy as np
import uuid
import struct
from typing import Optional

from backend.services.asr_base import ASRService, ASRSession, ASRStreamCallback


# 协议常量
PROTO_VERSION = 0x1
HEADER_SIZE = 0x1
SERIALIZATION_JSON = 0x1
SERIALIZATION_RAW = 0x0
COMPRESSION_NONE = 0x0
COMPRESSION_GZIP = 0x1

# 消息类型
MSG_TYPE_FULL_REQUEST = 0x01   # Full client request
MSG_TYPE_AUDIO_ONLY = 0x02     # Audio only request
MSG_TYPE_FULL_RESPONSE = 0x09  # Full server response
MSG_TYPE_ERROR = 0x0F          # Error message

# 消息标志
FLAG_NONE = 0x00
FLAG_SEQ_POS = 0x01            # 正数 sequence
FLAG_SEQ_NEG = 0x02            # 负数 sequence（最后一包，不含 seq）
FLAG_SEQ_NEG_WITH_SEQ = 0x03   # 负数 sequence（最后一包，含 seq）


def build_header(message_type: int, flags: int, serialization: int = SERIALIZATION_JSON, compression: int = COMPRESSION_GZIP) -> bytes:
    """
    构建 4 字节协议头
    """
    byte0 = (PROTO_VERSION << 4) | HEADER_SIZE
    byte1 = (message_type << 4) | flags
    byte2 = (serialization << 4) | compression
    byte3 = 0x00  # reserved
    return bytes([byte0, byte1, byte2, byte3])


def parse_asr_response(msg: bytes) -> dict:
    """
    解析 ASR 响应
    """
    response = {
        "code": 0,
        "event": 0,
        "is_last_package": False,
        "payload_sequence": 0,
        "payload_size": 0,
        "payload_msg": None
    }

    if len(msg) < 4:
        return response

    header_size = msg[0] & 0x0f
    message_type = msg[1] >> 4
    message_type_specific_flags = msg[1] & 0x0f
    serialization_method = msg[2] >> 4
    message_compression = msg[2] & 0x0f

    payload = msg[header_size * 4:]

    # 解析 message_type_specific_flags
    if message_type_specific_flags & 0x01:
        response["payload_sequence"] = struct.unpack('>i', payload[:4])[0]
        payload = payload[4:]
    if message_type_specific_flags & 0x02:
        response["is_last_package"] = True
    if message_type_specific_flags & 0x04:
        response["event"] = struct.unpack('>i', payload[:4])[0]
        payload = payload[4:]

    if not payload:
        return response

    # 解析 message_type
    if message_type == MSG_TYPE_FULL_RESPONSE:
        response["payload_size"] = struct.unpack('>I', payload[:4])[0]
        payload = payload[4:]
    elif message_type == MSG_TYPE_ERROR:
        response["code"] = struct.unpack('>i', payload[:4])[0]
        response["payload_size"] = struct.unpack('>I', payload[4:8])[0]
        payload = payload[8:]

    # 解压缩
    if message_compression == COMPRESSION_GZIP:
        try:
            payload = gzip.decompress(payload)
        except Exception:
            return response

    # 解析 payload
    if serialization_method == SERIALIZATION_JSON:
        try:
            response["payload_msg"] = json.loads(payload.decode('utf-8'))
        except Exception:
            pass

    return response


class VolcASRSession(ASRSession):
    """火山引擎 ASR 流式会话"""

    def __init__(
        self,
        session_id: str,
        app_id: str,
        access_key: str,
        resource_id: str,
        ws_url: str,
        language: str = "zh-CN"
    ):
        super().__init__(session_id)
        self.app_id = app_id
        self.access_key = access_key
        self.resource_id = resource_id
        self.ws_url = ws_url
        self.language = language

        self._ws = None
        self._recv_task = None
        self._send_queue = None
        self._send_task = None

        # 状态管理
        self._is_started = False
        self._is_ended = False
        self._final_result = ""
        self._partial_text = ""

        # 序列号管理 - 从 1 开始
        self._seq_num = 1

    async def start(self):
        """启动会话，建立 WebSocket 连接并发送初始化请求"""
        if self.is_active:
            return

        try:
            import websockets
        except ImportError:
            raise ImportError(
                "websockets 库未安装，请运行: pip install websockets"
            )

        headers = {
            "X-Api-App-Key": self.app_id,
            "X-Api-Access-Key": self.access_key,
            "X-Api-Resource-Id": self.resource_id,
            "X-Api-Connect-Id": self.session_id
        }

        try:
            # 建立 WebSocket 连接
            self._ws = await websockets.connect(
                self.ws_url,
                additional_headers=headers,
                ping_interval=None
            )

            # 启动接收任务
            self._recv_task = asyncio.create_task(self._receive_loop())

            # 启动发送任务
            self._send_queue = asyncio.Queue(maxsize=100)
            self._send_task = asyncio.create_task(self._send_loop())

            # 发送 full client request
            await self._send_full_request()

            self.is_active = True
            self._is_started = True



        except Exception as e:
            await self.close()
            raise

    async def _send_full_request(self):
        """发送 full client request"""
        # 构建消息：header(4) + seq(4) + payload_size(4) + payload
        header = build_header(MSG_TYPE_FULL_REQUEST, FLAG_SEQ_POS, SERIALIZATION_JSON, COMPRESSION_GZIP)

        payload = {
            "user": {"uid": "demo_uid"},
            "audio": {
                "format": "pcm",
                "rate": 16000,
                "bits": 16,
                "channel": 1
            },
            "request": {
                "model_name": "bigmodel",
                "enable_itn": True,
                "enable_punc": True,
                "enable_ddc": True,
                "show_utterances": True,
                "enable_nonstream": False,
                "end_window_size": 600  # VAD 停顿检测窗口 600ms，加快句尾识别
            }
        }

        payload_bytes = json.dumps(payload).encode('utf-8')
        compressed_payload = gzip.compress(payload_bytes)
        payload_size = struct.pack('>I', len(compressed_payload))

        request = bytearray()
        request.extend(header)
        request.extend(struct.pack('>i', self._seq_num))  # seq
        self._seq_num += 1
        request.extend(payload_size)
        request.extend(compressed_payload)

        await self._send_queue.put(bytes(request))

    async def send_audio(self, audio: np.ndarray, sample_rate: int):
        """发送音频数据"""
        if not self.is_active:
            raise RuntimeError("Session not active")

        if self._is_ended:
            return

        # 重采样到 16kHz（如果需要）
        if sample_rate != 16000:
            try:
                import torch
                import torchaudio
                audio_tensor = torchaudio.transforms.Resample(
                    orig_freq=sample_rate,
                    new_freq=16000
                )(torch.from_numpy(audio))
                audio = audio_tensor.numpy()
            except ImportError:
                # 如果没有 torch/torchaudio，使用简单的线性插值重采样
                ratio = 16000 / sample_rate
                new_length = int(len(audio) * ratio)
                indices = np.linspace(0, len(audio) - 1, new_length)
                audio = np.interp(indices, np.arange(len(audio)), audio)

        # 转换为 PCM 16bit
        audio = np.clip(audio, -1.0, 1.0)
        audio_pcm = (audio * 32767).astype(np.int16).tobytes()

        # 分段发送（每 200ms）
        segment_duration = 200  # 200ms
        segment_size = 6400  # 200ms at 16kHz, 16-bit, mono

        total_segments = (len(audio_pcm) + segment_size - 1) // segment_size

        for i in range(total_segments):
            start_idx = i * segment_size
            end_idx = min((i + 1) * segment_size, len(audio_pcm))
            segment = audio_pcm[start_idx:end_idx]

            is_last = (i == total_segments - 1)

            # 构建 audio only request
            if is_last:
                flags = FLAG_SEQ_NEG_WITH_SEQ
                seq_to_send = -self._seq_num  # 最后一包发送负序列号
            else:
                flags = FLAG_SEQ_POS
                seq_to_send = self._seq_num
                self._seq_num += 1

            header = build_header(MSG_TYPE_AUDIO_ONLY, flags, SERIALIZATION_RAW, COMPRESSION_GZIP)

            request = bytearray()
            request.extend(header)
            request.extend(struct.pack('>i', seq_to_send))

            compressed_segment = gzip.compress(segment)
            request.extend(struct.pack('>I', len(compressed_segment)))
            request.extend(compressed_segment)

            await self._send_queue.put(bytes(request))

    async def send_audio_chunk_raw(self, pcm_bytes: bytes, is_last: bool = False):
        """
        发送原始 PCM 小块（无人工延迟）。适用于实时流式调用方。
        pcm_bytes: 16kHz / 16-bit / 单声道 PCM 字节
        is_last:   True = 此包为最后一包（负序列号）
        """
        if not self.is_active or self._is_ended:
            return

        if is_last:
            flags = FLAG_SEQ_NEG_WITH_SEQ
            seq_to_send = -self._seq_num
        else:
            flags = FLAG_SEQ_POS
            seq_to_send = self._seq_num
            self._seq_num += 1

        header = build_header(MSG_TYPE_AUDIO_ONLY, flags, SERIALIZATION_RAW, COMPRESSION_GZIP)
        # 确保至少有 2 字节可供压缩
        payload = pcm_bytes if pcm_bytes else b"\x00\x00"
        compressed = gzip.compress(payload)

        request = bytearray()
        request.extend(header)
        request.extend(struct.pack('>i', seq_to_send))
        request.extend(struct.pack('>I', len(compressed)))
        request.extend(compressed)

        await self._send_queue.put(bytes(request))

    async def end(self):
        """结束会话，等待最终结果"""
        if not self.is_active:
            return

        if self._is_ended:
            return

        # 不在此处设置 _is_ended，由 _process_response 收到 is_last_package 后设置
        # 避免提前中止接收循环导致 final_event 永不触发
        try:
            await asyncio.wait_for(
                self._recv_task,
                timeout=10.0
            )
        except asyncio.TimeoutError:
            # 超时兜底：用已有的部分结果作为最终结果
            if not self._final_result and self._partial_text:
                self._final_result = self._partial_text
                self._notify_final(self._partial_text)
            self._is_ended = True
        except asyncio.CancelledError:
            pass

    async def close(self):
        """关闭连接"""
        if not self.is_active:
            return

        self.is_active = False

        # 取消任务
        if self._recv_task and not self._recv_task.done():
            self._recv_task.cancel()

        if self._send_task and not self._send_task.done():
            self._send_task.cancel()

        # 关闭 WebSocket
        if self._ws:
            try:
                await self._ws.close()
            except:
                pass

        self._notify_close()

    async def _send_loop(self):
        """发送循环"""
        try:
            while self.is_active:
                message = await self._send_queue.get()
                if self._ws:
                    await self._ws.send(message)
        except Exception as e:
            if self.is_active:
                self._notify_error(e)

    async def _receive_loop(self):
        """接收循环"""
        try:
            while self.is_active:
                data = await self._ws.recv()
                await self._process_response(data)

                # 如果已经结束，收到消息后退出
                if self._is_ended:
                    break
        except Exception as e:
            if self.is_active:
                self._notify_error(e)

    async def _process_response(self, data: bytes):
        """处理服务器响应"""
        response = parse_asr_response(data)

        # 处理错误
        if response["code"] != 0:
            self._notify_error(Exception(f"ASR Error: {response}"))
            return

        # 处理识别结果
        if response["payload_msg"]:
            if "result" in response["payload_msg"]:
                result_data = response["payload_msg"]["result"]
                text = result_data.get("text", "")
                utterances = result_data.get("utterances", [])

                is_definite = bool(utterances and utterances[-1].get("definite", False))

                if response["is_last_package"]:
                    # 服务端最后一包：触发 final，结束接收
                    final_text = text or self._partial_text
                    self._final_result = final_text
                    self._is_ended = True
                    self._notify_final(final_text)
                elif is_definite and text:
                    # VAD 检测到句子结束（definite=True）：触发 definite 回调，但不结束会话
                    # 允许连续多句输入
                    self._partial_text = text
                    self._notify_definite(text)
                elif text and text != self._partial_text:
                    self._partial_text = text
                    self._notify_partial(text)

        # 确保收到最后一包后退出接收循环
        if response["is_last_package"] and not self._is_ended:
            self._is_ended = True


class VolcASRService(ASRService):
    """火山引擎流式 ASR 服务"""

    def __init__(
        self,
        app_id: str = None,
        access_key: str = None,
        resource_id: str = None,
        ws_url: str = None
    ):
        super().__init__()

        # 从 settings 获取配置
        try:
            from backend.config.settings import settings
            self.app_id = app_id or getattr(settings, 'volc_asr_app_id', '')
            self.access_key = access_key or getattr(settings, 'volc_asr_access_key', '')
            self.resource_id = resource_id or getattr(settings, 'volc_asr_resource_id', 'volc.bigasr.sauc.duration')
            self.ws_url = ws_url or getattr(settings, 'volc_asr_ws_url', 'wss://openspeech.bytedance.com/api/v3/sauc/bigmodel')
        except (ImportError, AttributeError):
            self.app_id = app_id or ''
            self.access_key = access_key or ''
            self.resource_id = resource_id or 'volc.bigasr.sauc.duration'
            self.ws_url = ws_url or 'wss://openspeech.bytedance.com/api/v3/sauc/bigmodel'

        self.sample_rate = 16000

    async def transcribe_file(self, audio_data: bytes, language: str = "zh") -> str:
        """
        语音文件识别（使用流式模式）
        """
        import io
        import soundfile as sf

        # 读取音频
        audio_bytes = io.BytesIO(audio_data)
        audio_array, sr = sf.read(audio_bytes, dtype='float32')
        if len(audio_array.shape) > 1:
            audio_array = audio_array.mean(axis=1)

        # 创建会话并获取结果
        final_text = ""
        final_event = asyncio.Event()

        def get_final(text: str):
            nonlocal final_text
            final_text = text
            final_event.set()

        callback = ASRStreamCallback()
        callback.on_final_result = get_final

        asr_session = VolcASRSession(
            session_id=str(uuid.uuid4()),
            app_id=self.app_id,
            access_key=self.access_key,
            resource_id=self.resource_id,
            ws_url=self.ws_url,
            language=language
        )
        asr_session.set_callback(callback)

        try:
            await asr_session.start()
            await asr_session.send_audio(audio_array, sr)
            await asr_session.end()
            await asyncio.wait_for(final_event.wait(), timeout=10.0)
        finally:
            await asr_session.close()

        return final_text

    async def create_session(
        self,
        session_id: str,
        language: str = "zh",
        callback: Optional[ASRStreamCallback] = None
    ) -> VolcASRSession:
        """
        创建流式识别会话
        """
        lang_map = {"zh": "zh-CN", "en": "en-US"}
        lang_code = lang_map.get(language, language)

        session = VolcASRSession(
            session_id=session_id,
            app_id=self.app_id,
            access_key=self.access_key,
            resource_id=self.resource_id,
            ws_url=self.ws_url,
            language=lang_code
        )

        if callback:
            session.set_callback(callback)

        return session
