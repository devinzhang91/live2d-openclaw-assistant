"""
VAD 服务 - 优先使用 Silero TorchScript（silero-vad 包），降级到 ONNX，
再降级到 RMS 能量检测。
优先级：_SileroTorch > _SileroONNX > RMS 能量
"""
import logging
import numpy as np
from pathlib import Path
from typing import List, Tuple, Optional, Callable
import asyncio

from backend.config.settings import settings
from backend.services.asr_base import ASRService, ASRSession, ASRStreamCallback

logger = logging.getLogger(__name__)

# Silero VAD 要求 16 kHz，每次处理 512 samples（32 ms）
_CHUNK_SIZE = 512
_SAMPLE_RATE = 16000


class _SileroONNX:
    """
    Silero VAD ONNX 底层推理封装（兼容 op18_ifless 变体）。
    维护 LSTM 隐藏状态（h, c），可跨调用复用，也可在语音结束后 reset()。

    关键约定：
    - 16 kHz → chunk size = 512 samples (32 ms)
    - 8 kHz  → chunk size = 256 samples (32 ms)  [本服务统一重采样至 16 kHz]
    - state shape = [2, batch, 128]
    """

    _OUT_NAMES = ["output", "stateN"]

    def __init__(self, model_path: str):
        import onnxruntime as ort
        opts = ort.SessionOptions()
        opts.inter_op_num_threads = 1
        opts.intra_op_num_threads = 1
        opts.log_severity_level = 4   # suppress unused-initializer warnings
        self._sess = ort.InferenceSession(model_path, sess_options=opts)
        # 确认模型实际暴露的输出名，支持多种 ONNX 导出变体
        actual_out_names = [o.name for o in self._sess.get_outputs()]
        self._out_names = [n for n in self._OUT_NAMES if n in actual_out_names]
        if not self._out_names:
            self._out_names = None   # 回退：按位置取
        self._sr = np.array(_SAMPLE_RATE, dtype=np.int64)
        self._call_count = 0
        self.reset()

    def reset(self):
        """重置 LSTM 隐藏状态（每段新语音前调用）。"""
        # shape [2, 1, 128]：2=h/c, 1=batch, 128=hidden
        self._state = np.zeros((2, 1, 128), dtype=np.float32)
        self._call_count = 0

    @property
    def state_norm(self) -> float:
        """返回当前 LSTM 状态的 L2 范数（用于诊断 state 是否发散）。"""
        return float(np.linalg.norm(self._state))

    def __call__(self, chunk: np.ndarray) -> float:
        """
        推理一个 512-sample 块。
        chunk: float32 array, shape (512,)，已是 16 kHz。
        返回: 语音概率 [0.0, 1.0]
        """
        x = chunk.astype(np.float32).reshape(1, -1)
        out = self._sess.run(
            self._out_names,
            {"input": x, "sr": self._sr, "state": self._state},
        )
        # 取 output：named 模式 out = {name: val}，positional 模式 out = [val, ...]
        if isinstance(out, dict):
            prob_raw = out["output"]
            state_raw = out.get("stateN", self._state)
        else:
            prob_raw = out[0]
            state_raw = out[1] if len(out) > 1 else self._state

        prob = float(np.squeeze(prob_raw))

        # ── state reshape 保护 ────────────────────────────────────────
        # op18_ifless 应返回 [2, 1, 128]；不符时尝试 reshape，失败则保留旧 state
        expected = (2, 1, 128)
        if state_raw.shape == expected:
            self._state = state_raw.astype(np.float32)
        else:
            try:
                self._state = state_raw.reshape(expected).astype(np.float32)
            except ValueError:
                pass   # 保留旧 state，避免崩溃

        # 诊断：每 50 帧打印一次 state_norm，便于发现发散
        self._call_count += 1
        if self._call_count % 50 == 1:
            logger.debug(
                f"[SileroONNX] frame={self._call_count} prob={prob:.4f} "
                f"state_norm={self.state_norm:.3f}"
            )

        return prob

    def clone_stateless(self) -> "_SileroONNX":
        """创建一个共享 session、但有独立全零状态的实例（用于单次检测）。"""
        obj = _SileroONNX.__new__(_SileroONNX)
        obj._sess = self._sess
        obj._sr = self._sr
        obj._out_names = self._out_names
        obj.reset()
        return obj


# ---------------------------------------------------------------------------


class _SileroTorch:
    """
    Silero VAD TorchScript 封装，使用官方 silero_vad 包。
    已验证在 16kHz 音频上能正确输出高概率（~0.99997），比 ONNX 可靠。
    接口与 _SileroONNX 完全相同，可直接替换。
    """

    def __init__(self):
        from silero_vad import load_silero_vad
        import torch
        self._model = load_silero_vad()
        self._model.eval()
        self._torch = torch
        self._call_count = 0
        self.reset()

    def reset(self):
        """重置 LSTM 隐藏状态。"""
        self._model.reset_states()
        self._call_count = 0

    def __call__(self, chunk: np.ndarray) -> float:
        """
        推理一个 512-sample 块（16 kHz）。
        返回: 语音概率 [0.0, 1.0]
        """
        x = self._torch.from_numpy(
            chunk.astype(np.float32).reshape(1, -1)
        )
        with self._torch.no_grad():
            prob = float(self._model(x, _SAMPLE_RATE).item())

        self._call_count += 1
        if self._call_count % 50 == 1:
            logger.debug(
                f"[SileroTorch] frame={self._call_count} prob={prob:.4f}"
            )
        return prob

    def clone_stateless(self) -> "_SileroTorch":
        """创建独立状态的实例（注意：Torch 模型不共享，重新加载以避免状态污染）。"""
        obj = _SileroTorch.__new__(_SileroTorch)
        from silero_vad import load_silero_vad
        import torch
        obj._model = load_silero_vad()
        obj._model.eval()
        obj._torch = torch
        obj._call_count = 0
        obj.reset()
        return obj


# ---------------------------------------------------------------------------


class _EnergyVAD:
    """
    RMS 能量检测兜底 VAD（无模型依赖）。
    当 Silero（Torch 和 ONNX）均不可用时使用。
    """

    def __init__(self, rms_threshold: float = 0.01):
        self._thresh = rms_threshold
        self._call_count = 0

    def reset(self):
        self._call_count = 0

    def __call__(self, chunk: np.ndarray) -> float:
        rms = float(np.sqrt(np.mean(chunk.astype(np.float32) ** 2)))
        self._call_count += 1
        # 映射到 [0,1]：rms/thresh 截断到 1.0
        return min(rms / max(self._thresh, 1e-9), 1.0)

    def clone_stateless(self) -> "_EnergyVAD":
        return _EnergyVAD(self._thresh)


# ---------------------------------------------------------------------------


def _resample(audio: np.ndarray, src_sr: int, dst_sr: int) -> np.ndarray:
    """重采样到目标采样率。优先 scipy，不可用时线性插值降级。"""
    if src_sr == dst_sr:
        return audio.astype(np.float32)
    try:
        from scipy.signal import resample_poly
        from math import gcd
        g = gcd(src_sr, dst_sr)
        return resample_poly(audio, dst_sr // g, src_sr // g).astype(np.float32)
    except ImportError:
        new_len = int(len(audio) * dst_sr / src_sr)
        indices = np.linspace(0, len(audio) - 1, new_len)
        return np.interp(indices, np.arange(len(audio)), audio).astype(np.float32)


# ---------------------------------------------------------------------------


class VADService:
    """
    Silero VAD 服务（单例）。

    公开接口（兼容旧版调用）：
      is_speech(audio, sr) -> bool
      process_stream_chunk(audio, sr) -> Optional[np.ndarray]
      flush_buffer() -> Optional[np.ndarray]
      get_speech_segments(audio, sr) -> List[(start_ms, end_ms)]
      filter_audio_by_vad(audio, sr) -> np.ndarray
      set_asr_service(svc)
      set_streaming_callback(cb)
    """

    def __init__(self):
        self.sample_rate = _SAMPLE_RATE
        self.threshold: float = float(getattr(settings, "vad_threshold", 0.5))
        self._vad = None
        self._vad_backend: str = "none"
        self._load_model()

        self.buffer: List[float] = []
        self.buffer_size_samples = int(self.sample_rate * 0.5)
        self.is_speaking: bool = False
        self.silence_counter: int = 0
        self.max_silence_duration: int = int(self.sample_rate * 0.8)
        self._tail: np.ndarray = np.empty(0, dtype=np.float32)

        self._streaming_session: Optional[ASRSession] = None
        self._asr_service: Optional[ASRService] = None
        self._streaming_callback: Optional[Callable[[str], None]] = None

    def _load_model(self):
        # ── 优先级 1：Silero TorchScript（silero-vad 包）────────────────
        try:
            self._vad = _SileroTorch()
            self._vad_backend = "torch"
            print("✅ Silero VAD [TorchScript] 已就绪"
                  f"（阈值={self.threshold}，chunk={_CHUNK_SIZE} samples @ {_SAMPLE_RATE} Hz）")
            return
        except Exception as e:
            logger.warning(f"[VAD] TorchScript 不可用，尝试 ONNX: {e}")

        # ── 优先级 2：Silero ONNX ──────────────────────────────────────
        model_path = (
            Path(__file__).parent.parent.parent / "models" / "vad" / "silero_vad.onnx"
        )
        if not model_path.exists():
            model_path = Path(getattr(settings, "vad_model_path", ""))

        if model_path.exists():
            try:
                print(f"正在加载 Silero VAD ONNX 模型: {model_path} ...")
                self._vad = _SileroONNX(str(model_path))
                self._vad_backend = "onnx"
                print(f"✅ Silero VAD [ONNX] 已就绪（阈值={self.threshold}，"
                      f"chunk={_CHUNK_SIZE} samples @ {_SAMPLE_RATE} Hz）")
                print("  ⚠️  注意：ONNX 在 16kHz 路径上存在 state 发散问题，建议安装 silero-vad 包")
                return
            except Exception as e:
                logger.warning(f"[VAD] ONNX 加载失败，使用 RMS 能量检测: {e}")
        else:
            print(f"⚠️  未找到 Silero VAD ONNX 模型: {model_path}")

        # ── 优先级 3：RMS 能量检测兜底 ────────────────────────────────
        rms_thresh = float(getattr(settings, "vad_rms_threshold", 0.01))
        self._vad = _EnergyVAD(rms_threshold=rms_thresh)
        self._vad_backend = "energy"
        print(f"✅ VAD [RMS Energy fallback] 已就绪（rms_threshold={rms_thresh}）")

    @property
    def model(self):
        """兼容 rest.py 中 vad_service.model 判断服务是否就绪。"""
        return self._vad

    def _run_chunks(self, audio_16k: np.ndarray, vad: _SileroONNX) -> List[float]:
        """对整段音频按 CHUNK_SIZE 分块推理，返回每块的语音概率列表。"""
        total = len(audio_16k)
        if total == 0:
            return []
        if total < _CHUNK_SIZE:
            padded = np.pad(audio_16k, (0, _CHUNK_SIZE - total))
            return [vad(padded)]
        probs = []
        for i in range(0, total - _CHUNK_SIZE + 1, _CHUNK_SIZE):
            probs.append(vad(audio_16k[i: i + _CHUNK_SIZE]))
        return probs

    def is_speech(self, audio_data: np.ndarray, sample_rate: int = None) -> bool:
        """判断一段音频是否包含语音（独立 VAD 状态，不影响流式状态）。"""
        if self._vad is None:
            return True
        sr = sample_rate or self.sample_rate
        audio_16k = _resample(audio_data, sr, self.sample_rate)
        tmp = self._vad.clone_stateless()
        probs = self._run_chunks(audio_16k, tmp)
        return float(np.mean(probs)) > self.threshold if probs else False

    def process_stream_chunk(
        self, audio_chunk: np.ndarray, sample_rate: int = None
    ) -> Optional[np.ndarray]:
        """
        流式处理一个音频块。
        使用共享 LSTM 状态逐帧推理；静音超过阈值时返回完整语音段。
        """
        if self._vad is None:
            return None

        sr = sample_rate or self.sample_rate
        audio_16k = _resample(audio_chunk, sr, self.sample_rate)

        if len(self._tail) > 0:
            audio_16k = np.concatenate([self._tail, audio_16k])

        total = len(audio_16k)
        n_chunks = total // _CHUNK_SIZE
        self._tail = audio_16k[n_chunks * _CHUNK_SIZE:]

        speech_detected = False
        for i in range(n_chunks):
            prob = self._vad(audio_16k[i * _CHUNK_SIZE: (i + 1) * _CHUNK_SIZE])
            if prob > self.threshold:
                speech_detected = True
                break

        chunk_samples = audio_16k[: n_chunks * _CHUNK_SIZE]
        self.buffer.extend(chunk_samples.tolist())

        if speech_detected:
            self.silence_counter = 0
            if not self.is_speaking:
                self.is_speaking = True
                print("\U0001f3a4 [Silero VAD] 检测到语音开始")
        else:
            if self.is_speaking:
                self.silence_counter += len(chunk_samples)
                if self.silence_counter >= self.max_silence_duration:
                    speech_audio = np.array(self.buffer, dtype=np.float32)
                    self._reset_stream_state()
                    print("\U0001f3a4 [Silero VAD] 检测到语音结束")
                    return speech_audio
            else:
                if len(self.buffer) > self.buffer_size_samples:
                    self.buffer = self.buffer[-self.buffer_size_samples:]

        return None

    def flush_buffer(self) -> Optional[np.ndarray]:
        """刷新缓冲区，返回剩余语音数据（audio_end 时调用）。
        前端 VAD 已完成语音分段，audio_end 时 buffer 里的内容即为有效语音，
        直接返回不再检查 is_speaking 标志。
        """
        if len(self.buffer) > 0:
            speech_audio = np.array(self.buffer, dtype=np.float32)
            self._reset_stream_state()
            return speech_audio
        self._reset_stream_state()
        return None

    def _reset_stream_state(self):
        self.buffer = []
        self._tail = np.empty(0, dtype=np.float32)
        self.is_speaking = False
        self.silence_counter = 0
        if self._vad:
            self._vad.reset()

    def get_speech_segments(
        self,
        audio_data: np.ndarray,
        sample_rate: int = None,
        min_speech_duration_ms: int = 250,
        min_silence_duration_ms: int = 100,
    ) -> List[Tuple[int, int]]:
        """返回 [(start_ms, end_ms), ...] 格式的语音片段列表。"""
        if self._vad is None:
            sr = sample_rate or self.sample_rate
            return [(0, len(audio_data) * 1000 // sr)]

        sr = sample_rate or self.sample_rate
        audio_16k = _resample(audio_data, sr, self.sample_rate)
        tmp = self._vad.clone_stateless()

        min_speech_samples = _SAMPLE_RATE * min_speech_duration_ms // 1000
        min_silence_samples = _SAMPLE_RATE * min_silence_duration_ms // 1000

        segments: List[Tuple[int, int]] = []
        speech_start: Optional[int] = None
        silence_acc = 0

        for i in range(0, len(audio_16k) - _CHUNK_SIZE + 1, _CHUNK_SIZE):
            prob = tmp(audio_16k[i: i + _CHUNK_SIZE])
            is_sp = prob > self.threshold
            sample_pos = i + _CHUNK_SIZE

            if is_sp:
                silence_acc = 0
                if speech_start is None:
                    speech_start = i
            else:
                if speech_start is not None:
                    silence_acc += _CHUNK_SIZE
                    if silence_acc >= min_silence_samples:
                        end_sample = sample_pos - silence_acc
                        if (end_sample - speech_start) >= min_speech_samples:
                            segments.append((
                                speech_start * 1000 // _SAMPLE_RATE,
                                end_sample * 1000 // _SAMPLE_RATE,
                            ))
                        speech_start = None
                        silence_acc = 0

        if speech_start is not None:
            end_sample = len(audio_16k)
            if (end_sample - speech_start) >= min_speech_samples:
                segments.append((
                    speech_start * 1000 // _SAMPLE_RATE,
                    end_sample * 1000 // _SAMPLE_RATE,
                ))

        return segments if segments else [(0, len(audio_data) * 1000 // sr)]

    def filter_audio_by_vad(
        self,
        audio_data: np.ndarray,
        sample_rate: int = None,
    ) -> np.ndarray:
        """根据 VAD 结果过滤音频，只保留语音部分。"""
        sr = sample_rate or self.sample_rate
        segments = self.get_speech_segments(audio_data, sr)
        if not segments:
            return np.array([], dtype=np.float32)
        parts = []
        for start_ms, end_ms in segments:
            s = start_ms * sr // 1000
            e = end_ms * sr // 1000
            parts.append(audio_data[s:e])
        return np.concatenate(parts) if parts else np.array([], dtype=np.float32)

    def set_asr_service(self, asr_service: ASRService):
        self._asr_service = asr_service

    def set_streaming_callback(self, callback: Callable[[str], None]):
        self._streaming_callback = callback

    async def _start_streaming_asr(self):
        if not self._asr_service:
            return

        async def on_partial(text: str):
            if self._streaming_callback:
                self._streaming_callback(text)

        async def on_final(text: str):
            if self._streaming_callback:
                self._streaming_callback(text)

        cb = ASRStreamCallback()
        cb.on_partial_result = on_partial
        cb.on_final_result = on_final

        import uuid
        self._streaming_session = await self._asr_service.create_session(
            session_id=str(uuid.uuid4()),
            language="zh",
            callback=cb,
        )
        await self._streaming_session.start()
        if self.buffer:
            await self._streaming_session.send_audio(
                np.array(self.buffer, dtype=np.float32), self.sample_rate
            )

    async def _end_streaming_asr(self):
        if self._streaming_session:
            try:
                await self._streaming_session.end()
                await self._streaming_session.close()
            except Exception as e:
                print(f"结束流式 ASR 会话错误: {e}")
            finally:
                self._streaming_session = None

    async def process_stream_chunk_with_streaming_asr(
        self,
        audio_chunk: np.ndarray,
        sample_rate: int = None,
    ) -> Optional[np.ndarray]:
        """流式 ASR 版本（streaming_asr_enabled=True 时使用）。"""
        sr = sample_rate or self.sample_rate
        audio_16k = _resample(audio_chunk, sr, self.sample_rate)

        if len(self._tail) > 0:
            audio_16k = np.concatenate([self._tail, audio_16k])
        total = len(audio_16k)
        n_chunks = total // _CHUNK_SIZE
        self._tail = audio_16k[n_chunks * _CHUNK_SIZE:]

        speech_detected = False
        if self._vad:
            for i in range(n_chunks):
                if self._vad(audio_16k[i * _CHUNK_SIZE: (i + 1) * _CHUNK_SIZE]) > self.threshold:
                    speech_detected = True
                    break

        chunk_samples = audio_16k[: n_chunks * _CHUNK_SIZE]
        self.buffer.extend(chunk_samples.tolist())

        if speech_detected:
            self.silence_counter = 0
            if not self.is_speaking:
                self.is_speaking = True
                await self._start_streaming_asr()
            elif self._streaming_session:
                await self._streaming_session.send_audio(audio_chunk, sr)
        else:
            if self.is_speaking:
                self.silence_counter += len(chunk_samples)
                if self._streaming_session:
                    await self._streaming_session.send_audio(audio_chunk, sr)
                if self.silence_counter >= self.max_silence_duration:
                    speech_audio = np.array(self.buffer, dtype=np.float32)
                    await self._end_streaming_asr()
                    self._reset_stream_state()
                    return speech_audio
            else:
                if len(self.buffer) > self.buffer_size_samples:
                    self.buffer = []
                    self.silence_counter = 0
        return None


# 全局单例
vad_service = VADService()
