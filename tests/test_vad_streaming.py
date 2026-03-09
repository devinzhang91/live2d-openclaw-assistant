#!/usr/bin/env python3
"""
流式 VAD 验证脚本
====================
模拟麦克风实时输入：将 test_output.mp3 按固定帧大小逐块喂入 Silero VAD，
检测语音段的起止时间。

用法:
    python tests/test_vad_streaming.py [--audio PATH] [--chunk-ms N] [--threshold F]

默认:
    --audio       tests/test_output.mp3
    --chunk-ms    200        （每次模拟推入 200ms，贴近真实麦克风采集粒度）
    --threshold   0.5
"""

import argparse
import sys
import time
from pathlib import Path
from typing import List, Tuple

import numpy as np

# ── 路径设置 ────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# ── 常量 ────────────────────────────────────────────────────────────────
SAMPLE_RATE = 16_000   # Silero VAD 要求 16 kHz（或 8kHz，传入 sr 参数即可）
CHUNK_SAMPLES = 512    # Silero VAD 单次推理帧大小（512/16000 = 32ms）
MODEL_PATH = ROOT / "models" / "vad" / "silero_vad.onnx"  # 仅用于说明，JIT 模式不使用

# ANSI 颜色
_GREEN  = "\033[92m"
_YELLOW = "\033[93m"
_RED    = "\033[91m"
_CYAN   = "\033[96m"
_RESET  = "\033[0m"
_BOLD   = "\033[1m"


# ── 音频加载 ────────────────────────────────────────────────────────────

def load_audio(path: str) -> Tuple[np.ndarray, int]:
    """加载音频文件，返回 (float32 mono array, 原始采样率)"""
    import soundfile as sf

    # soundfile 直接支持 mp3 需要 libsndfile >= 1.1.0
    try:
        audio, sr = sf.read(path, dtype="float32")
        if audio.ndim > 1:
            audio = audio.mean(axis=1)
        return audio, sr
    except Exception:
        pass

    # fallback: librosa（内部用 audioread / ffmpeg）
    try:
        import librosa  # type: ignore
        audio, sr = librosa.load(path, sr=None, mono=True, dtype=np.float32)
        return audio, int(sr)
    except ImportError:
        pass

    # fallback: pydub → numpy
    try:
        from pydub import AudioSegment  # type: ignore
        seg = AudioSegment.from_file(path)
        seg = seg.set_channels(1)
        sr = seg.frame_rate
        samples = np.array(seg.get_array_of_samples(), dtype=np.float32)
        samples /= 2 ** (seg.sample_width * 8 - 1)
        return samples, sr
    except ImportError:
        pass

    raise RuntimeError(
        "无法加载音频。请安装以下任意一个库：soundfile(>=1.1.0), librosa, pydub"
    )


# ── 重采样 ──────────────────────────────────────────────────────────────

def resample(audio: np.ndarray, src_sr: int, dst_sr: int) -> np.ndarray:
    if src_sr == dst_sr:
        return audio.astype(np.float32)
    try:
        from scipy.signal import resample_poly
        from math import gcd
        g = gcd(src_sr, dst_sr)
        return resample_poly(audio, dst_sr // g, src_sr // g).astype(np.float32)
    except ImportError:
        new_len = int(len(audio) * dst_sr / src_sr)
        return np.interp(
            np.linspace(0, len(audio) - 1, new_len),
            np.arange(len(audio)),
            audio,
        ).astype(np.float32)


# ── Silero VAD 封装 ──────────────────────────────────────────────────────

class SileroVAD:
    """
    Silero VAD TorchScript（JIT）流式封装。
    使用官方 silero-vad 包（pip install silero-vad）加载 TorchScript 模型。

    与 ONNX 方案的核心区别：
      - LSTM 隐藏状态由 TorchScript 模型内部自动维护，无需手动传入/接收 state 张量。
      - 调用接口：model(chunk_tensor, sr) → 直接返回概率标量。
      - reset_states() 重置内部隐藏状态（开始新一段对话前调用）。
      - 帧大小同样是 512 samples @ 16kHz（32ms），8kHz 时 512 samples = 64ms。

    参数
    ----
    sr : int
        音频采样率，传给模型用于选择内部权重（支持 8000 和 16000）。
    threshold : float
        语音判定概率阈值，默认 0.5。
    """

    def __init__(self, sr: int = SAMPLE_RATE, threshold: float = 0.5):
        from silero_vad import load_silero_vad
        import torch
        self._model = load_silero_vad()
        self._model.eval()
        self._torch = torch
        self._sr = sr
        self.threshold = threshold
        self._frame_count = 0
        print(f"  [SileroVAD-JIT] 模型已加载（TorchScript），"
              f"sr={sr}Hz，chunk={CHUNK_SAMPLES} samples（{CHUNK_SAMPLES*1000//sr}ms），"
              f"阈值={threshold}  ✅")

    def reset(self):
        """重置模型内部 LSTM 隐藏状态（每段新语音前调用）。"""
        self._model.reset_states()
        self._frame_count = 0

    def __call__(self, chunk: np.ndarray) -> float:
        """
        流式推理 512-sample 帧，返回语音概率 [0.0, 1.0]。
        TorchScript 模型内部自动维护 LSTM 状态，每帧结果受前序帧历史影响。
        """
        x = self._torch.from_numpy(chunk.astype(np.float32).reshape(1, -1))
        with self._torch.no_grad():
            prob = float(self._model(x, self._sr).item())

        # 首帧打印确认
        if self._frame_count == 0:
            print(f"  [SileroVAD-JIT] 首帧概率={prob:.5f}  "
                  f"(LSTM state 由 TorchScript 模型内部管理，流式 ✅)")
        self._frame_count += 1
        return prob

    @property
    def state_norm(self) -> float:
        """TorchScript 模型内部管理状态，此处始终返回 0.0（无法直接访问）。"""
        return 0.0

    def is_speech(self, chunk: np.ndarray) -> bool:
        return self.__call__(chunk) >= self.threshold


# ── 流式 VAD 状态机 ────────────────────────────────────────────────────

class StreamingVAD:
    """
    逐块喂入音频（任意长度），维护 LSTM 状态，检测语音起止。
    同时维护一个基于 RMS 能量的并行检测器（用于合成语音 / TTS 音频兜底）。

    onset_chunks  : 连续多少个 speech chunk 才确认语音开始（防止假阳）
    offset_chunks : 连续多少个 silence chunk 才确认语音结束
    """

    def __init__(
        self,
        vad: SileroVAD,
        onset_chunks: int = 2,
        offset_chunks: int = 25,      # ≈ 800ms at 32ms/chunk
        energy_onset_chunks: int = 3,
        energy_offset_chunks: int = 20,
        energy_threshold: float = 0.01,  # RMS 能量阈值（归一化 [-1,1]）
    ):
        self.vad = vad
        self.onset_chunks = onset_chunks
        self.offset_chunks = offset_chunks
        self.energy_onset_chunks = energy_onset_chunks
        self.energy_offset_chunks = energy_offset_chunks
        self.energy_threshold = energy_threshold

        # Silero 状态
        self._is_speaking = False
        self._speech_start_sample: int = 0
        self._consecutive_speech = 0
        self._consecutive_silence = 0
        self._pending_start_sample: int = 0
        self._tail = np.empty(0, dtype=np.float32)
        self._elapsed_samples = 0

        # 能量检测状态
        self._e_is_speaking = False
        self._e_start_sample: int = 0
        self._e_onset_count = 0
        self._e_offset_count = 0
        self._e_pending_start: int = 0

        # 每帧数据（用于 verbose 输出）
        self.frame_log: List[dict] = []

    def reset(self):
        self.vad.reset()
        self._is_speaking = False
        self._speech_start_sample = 0
        self._consecutive_speech = 0
        self._consecutive_silence = 0
        self._pending_start_sample = 0
        self._tail = np.empty(0, dtype=np.float32)
        self._elapsed_samples = 0
        self._e_is_speaking = False
        self._e_start_sample = 0
        self._e_onset_count = 0
        self._e_offset_count = 0
        self._e_pending_start = 0
        self.frame_log.clear()

    def feed(self, chunk_16k: np.ndarray) -> List[dict]:
        """
        喂入已转为 16kHz float32 的音频块。
        返回触发的事件列表，每项是 dict：
          {"event": "speech_start"|"speech_end", "detector": "silero"|"energy",
           "time_s": float, ...}
        """
        audio = np.concatenate([self._tail, chunk_16k]) if len(self._tail) else chunk_16k

        n_frames = len(audio) // CHUNK_SAMPLES
        self._tail = audio[n_frames * CHUNK_SAMPLES:]

        events = []

        for i in range(n_frames):
            frame = audio[i * CHUNK_SAMPLES: (i + 1) * CHUNK_SAMPLES]
            sample_pos = self._elapsed_samples + (i + 1) * CHUNK_SAMPLES
            time_s = sample_pos / SAMPLE_RATE

            # ── Silero VAD ────────────────────────────────────────────
            vad_prob = self.vad(frame)
            is_sp = vad_prob >= self.vad.threshold

            # ── 能量 VAD ──────────────────────────────────────────────
            rms = float(np.sqrt(np.mean(frame ** 2)))
            is_energy_sp = rms >= self.energy_threshold

            # 记录帧日志（JIT 模式 state_norm=0 为正常，LSTM 状态由 TorchScript 内部管理）
            self.frame_log.append({
                "sample": sample_pos,
                "time_s": time_s,
                "vad_prob": vad_prob,
                "rms": rms,
                "is_sp": is_sp,
                "is_energy_sp": is_energy_sp,
                "state_norm": self.vad.state_norm,
            })

            # ── Silero 状态机 ─────────────────────────────────────────
            if not self._is_speaking:
                if is_sp:
                    self._consecutive_speech += 1
                    if self._consecutive_speech == 1:
                        self._pending_start_sample = sample_pos - CHUNK_SAMPLES
                    if self._consecutive_speech >= self.onset_chunks:
                        self._is_speaking = True
                        self._speech_start_sample = self._pending_start_sample
                        self._consecutive_silence = 0
                        events.append({
                            "event": "speech_start", "detector": "silero",
                            "sample": self._speech_start_sample,
                            "time_s": self._speech_start_sample / SAMPLE_RATE,
                        })
                else:
                    self._consecutive_speech = 0
            else:
                if is_sp:
                    self._consecutive_silence = 0
                else:
                    self._consecutive_silence += 1
                    if self._consecutive_silence >= self.offset_chunks:
                        end_sample = sample_pos - self._consecutive_silence * CHUNK_SAMPLES
                        duration = (end_sample - self._speech_start_sample) / SAMPLE_RATE
                        events.append({
                            "event": "speech_end", "detector": "silero",
                            "sample": end_sample,
                            "time_s": end_sample / SAMPLE_RATE,
                            "start_sample": self._speech_start_sample,
                            "start_time_s": self._speech_start_sample / SAMPLE_RATE,
                            "duration_s": duration,
                        })
                        self._is_speaking = False
                        self._consecutive_speech = 0
                        self._consecutive_silence = 0

            # ── 能量状态机 ────────────────────────────────────────────
            if not self._e_is_speaking:
                if is_energy_sp:
                    self._e_onset_count += 1
                    if self._e_onset_count == 1:
                        self._e_pending_start = sample_pos - CHUNK_SAMPLES
                    if self._e_onset_count >= self.energy_onset_chunks:
                        self._e_is_speaking = True
                        self._e_start_sample = self._e_pending_start
                        self._e_offset_count = 0
                        events.append({
                            "event": "speech_start", "detector": "energy",
                            "sample": self._e_start_sample,
                            "time_s": self._e_start_sample / SAMPLE_RATE,
                        })
                else:
                    self._e_onset_count = 0
            else:
                if is_energy_sp:
                    self._e_offset_count = 0
                else:
                    self._e_offset_count += 1
                    if self._e_offset_count >= self.energy_offset_chunks:
                        end_sample = sample_pos - self._e_offset_count * CHUNK_SAMPLES
                        duration = (end_sample - self._e_start_sample) / SAMPLE_RATE
                        events.append({
                            "event": "speech_end", "detector": "energy",
                            "sample": end_sample,
                            "time_s": end_sample / SAMPLE_RATE,
                            "start_sample": self._e_start_sample,
                            "start_time_s": self._e_start_sample / SAMPLE_RATE,
                            "duration_s": duration,
                        })
                        self._e_is_speaking = False
                        self._e_onset_count = 0
                        self._e_offset_count = 0

        self._elapsed_samples += n_frames * CHUNK_SAMPLES
        return events

    def flush(self) -> List[dict]:
        """文件结束时调用，若仍在语音中则强制关闭最后一段"""
        events = []
        if self._is_speaking:
            end_sample = self._elapsed_samples
            duration = (end_sample - self._speech_start_sample) / SAMPLE_RATE
            events.append({
                "event": "speech_end", "detector": "silero",
                "sample": end_sample,
                "time_s": end_sample / SAMPLE_RATE,
                "start_sample": self._speech_start_sample,
                "start_time_s": self._speech_start_sample / SAMPLE_RATE,
                "duration_s": duration,
            })
            self._is_speaking = False
        if self._e_is_speaking:
            end_sample = self._elapsed_samples
            duration = (end_sample - self._e_start_sample) / SAMPLE_RATE
            events.append({
                "event": "speech_end", "detector": "energy",
                "sample": end_sample,
                "time_s": end_sample / SAMPLE_RATE,
                "start_sample": self._e_start_sample,
                "start_time_s": self._e_start_sample / SAMPLE_RATE,
                "duration_s": duration,
            })
            self._e_is_speaking = False
        return events


# ── 主流程 ──────────────────────────────────────────────────────────────

def run(audio_path: str, chunk_ms: int, threshold: float, energy_threshold: float,
        realtime_sim: bool, verbose: bool):
    print(f"\n{_BOLD}{'='*62}{_RESET}")
    print(f"{_BOLD}  Silero VAD 流式验证（双检测器）{_RESET}")
    print(f"{'='*62}")
    print(f"  音频文件      : {audio_path}")
    print(f"  模型          : silero-vad TorchScript（官方 JIT，内部管理 LSTM 状态）")
    print(f"  推进帧长      : {chunk_ms} ms（模拟麦克风采集粒度）")
    print(f"  Silero 阈值   : {threshold}")
    print(f"  能量 RMS 阈值 : {energy_threshold}")
    print(f"  实时模拟      : {'是（含 sleep）' if realtime_sim else '否（快速扫描）'}")
    print(f"  Verbose       : {'是' if verbose else '否（-v 启用逐帧概率）'}")
    print(f"{'='*62}\n")

    # 加载模型（TorchScript JIT）
    try:
        vad_model = SileroVAD(threshold=threshold)
    except Exception as e:
        print(f"{_RED}[ERROR] 无法加载 silero-vad TorchScript 模型: {e}{_RESET}")
        print("  请先执行: pip install silero-vad")
        sys.exit(1)

    # 加载音频
    print(f"加载音频: {audio_path}...", end=" ", flush=True)
    audio_raw, src_sr = load_audio(audio_path)
    total_duration = len(audio_raw) / src_sr
    rms_raw = float(np.sqrt(np.mean(audio_raw ** 2)))
    print(f"✅  ({src_sr} Hz, {total_duration:.2f}s, peak={np.abs(audio_raw).max():.3f}, RMS={rms_raw:.4f})")

    # 重采样到 16kHz
    if src_sr != SAMPLE_RATE:
        print(f"重采样 {src_sr}→{SAMPLE_RATE} Hz...", end=" ", flush=True)
        audio_16k = resample(audio_raw, src_sr, SAMPLE_RATE)
        print("✅")
    else:
        audio_16k = audio_raw.astype(np.float32)

    total_16k_samples = len(audio_16k)
    total_16k_duration = total_16k_samples / SAMPLE_RATE

    chunk_samples_16k = int(SAMPLE_RATE * chunk_ms / 1000)
    n_chunks = (total_16k_samples + chunk_samples_16k - 1) // chunk_samples_16k

    print(f"\n推进块大小 : {chunk_samples_16k} samples ({chunk_ms}ms)")
    print(f"总块数     : {n_chunks}")
    print(f"VAD 帧大小  : {CHUNK_SAMPLES} samples ({CHUNK_SAMPLES*1000//SAMPLE_RATE}ms)\n")

    print(f"{'─'*62}")
    print(f"  {'时间':>8}  {'检测器':^8}  事件")
    print(f"{'─'*62}")

    # 流式 VAD（双检测器）
    streaming_vad = StreamingVAD(
        vad=vad_model,
        onset_chunks=2,
        offset_chunks=max(1, int(800 / 32)),   # 800ms 静音 → 结束
        energy_onset_chunks=3,
        energy_offset_chunks=max(1, int(600 / 32)),
        energy_threshold=energy_threshold,
    )

    silero_segments: List[dict] = []
    energy_segments: List[dict] = []
    start_wall = time.monotonic()
    chunk_duration_s = chunk_ms / 1000.0

    _DETECTOR_COLOR = {"silero": _GREEN, "energy": _CYAN}
    _DETECTOR_LABEL = {"silero": "Silero", "energy": "Energy"}

    def _fmt_ev(ev: dict) -> str:
        c = _DETECTOR_COLOR.get(ev["detector"], "")
        lbl = _DETECTOR_LABEL.get(ev["detector"], ev["detector"])
        t = ev["time_s"]
        if ev["event"] == "speech_start":
            return (f"  {c}{t:>7.3f}s{_RESET}  {c}[{lbl:^6}]{_RESET}"
                    f"  🎙  {c}{_BOLD}语音开始{_RESET}")
        else:
            ts = ev["start_time_s"]
            te = ev["time_s"]
            dur = ev["duration_s"]
            return (f"  {_YELLOW}{te:>7.3f}s{_RESET}  {c}[{lbl:^6}]{_RESET}"
                    f"  🔇  {_YELLOW}{_BOLD}语音结束{_RESET}"
                    f"  （开始={c}{ts:.3f}s{_RESET}  时长={c}{dur:.3f}s{_RESET}）")

    for i in range(n_chunks):
        s = i * chunk_samples_16k
        e = min(s + chunk_samples_16k, total_16k_samples)
        chunk = audio_16k[s:e]
        audio_time = e / SAMPLE_RATE

        events = streaming_vad.feed(chunk)

        for ev in events:
            print(_fmt_ev(ev))
            seg_entry = {"idx": 0, "start": ev.get("start_time_s", ev["time_s"]),
                         "end": ev["time_s"], "duration": ev.get("duration_s", 0.0)}
            if ev["event"] == "speech_end":
                if ev["detector"] == "silero":
                    seg_entry["idx"] = len(silero_segments) + 1
                    silero_segments.append(seg_entry)
                else:
                    seg_entry["idx"] = len(energy_segments) + 1
                    energy_segments.append(seg_entry)

        if realtime_sim:
            target_wall = start_wall + audio_time
            now_wall = time.monotonic()
            sleep_s = target_wall - now_wall
            if sleep_s > 0:
                time.sleep(sleep_s)

    # 文件结束：冲洗最后一段
    for ev in streaming_vad.flush():
        print(_fmt_ev(ev))
        seg_entry = {"idx": 0, "start": ev.get("start_time_s", ev["time_s"]),
                     "end": ev["time_s"], "duration": ev.get("duration_s", 0.0)}
        if ev["detector"] == "silero":
            seg_entry["idx"] = len(silero_segments) + 1
            silero_segments.append(seg_entry)
        else:
            seg_entry["idx"] = len(energy_segments) + 1
            energy_segments.append(seg_entry)

    wall_elapsed = time.monotonic() - start_wall
    print(f"{'─'*62}")

    # ── Verbose：每帧 VAD 概率 & 能量 ───────────────────────────────────
    if verbose and streaming_vad.frame_log:
        print(f"\n{_BOLD}逐帧明细{_RESET}（每 {CHUNK_SAMPLES*1000//SAMPLE_RATE}ms 一帧，StateNorm=0 表示 JIT 内部管理状态）")
        print(f"{'─'*74}")
        print(f"  {'时间':>8}  {'Silero概率':>10}  {'RMS':>8}  {'StateNorm':>9}  VAD EN")
        print(f"{'─'*74}")
        for f in streaming_vad.frame_log:
            sp = "🟢" if f["is_sp"] else "⚫"
            ep = "🔵" if f["is_energy_sp"] else "⚫"
            bar_v = int(f["vad_prob"] * 30)
            bar_e = int(f["rms"] / 0.3 * 20)
            sn = f.get("state_norm", 0.0)
            print(
                f"  {f['time_s']:>7.3f}s  {f['vad_prob']:>10.5f}  {f['rms']:>8.5f}"
                f"  {sn:>9.4f}  "
                f"{sp} {ep}  {'█'*bar_v}{'░'*(30-bar_v)} | {'█'*min(bar_e,20)}"
            )
        print(f"{'─'*74}")

    # ── 汇总 ────────────────────────────────────────────────────────────
    print(f"\n{_BOLD}汇总{_RESET}")
    print(f"{'─'*62}")
    print(f"  音频总时长     : {total_16k_duration:.3f} s")
    print(f"  处理耗时       : {wall_elapsed:.3f} s  "
          f"({'实时' if realtime_sim else '快速扫描, '}RTF={wall_elapsed/total_16k_duration:.2f}x)")

    # Silero 汇总
    max_vad_prob = max((f["vad_prob"] for f in streaming_vad.frame_log), default=0.0)
    print(f"\n  {_GREEN}{_BOLD}[Silero VAD JIT]{_RESET}  最大概率={_GREEN}{max_vad_prob:.5f}{_RESET}"
          f"  阈值={threshold}"
          f"  {'✅' if max_vad_prob >= threshold else '⚠️  未超过阈值（音频域不匹配或音量过低）'}")
    _print_segs(silero_segments, total_16k_duration, _GREEN)

    # Energy 汇总
    max_rms = max((f["rms"] for f in streaming_vad.frame_log), default=0.0)
    print(f"\n  {_CYAN}{_BOLD}[Energy VAD]{_RESET}  最大RMS={_CYAN}{max_rms:.5f}{_RESET}"
          f"  阈值={energy_threshold}")
    _print_segs(energy_segments, total_16k_duration, _CYAN)

    print(f"{'─'*62}\n")


def _print_segs(segments: List[dict], total_dur: float, color: str):
    if not segments:
        print(f"    {_RED}未检测到语音段{_RESET}")
        return
    total_speech = sum(s["duration"] for s in segments)
    speech_ratio = total_speech / total_dur * 100
    print(f"    检测到 {_BOLD}{len(segments)}{_RESET} 段，总语音时长 {color}{total_speech:.3f}s{_RESET}"
          f"（占比 {speech_ratio:.1f}%）")
    print(f"    {'#':>3}  {'起始':>8}  {'结束':>8}  {'时长':>8}")
    print(f"    {'─'*3}  {'─'*8}  {'─'*8}  {'─'*8}")
    for s in segments:
        print(f"    {s['idx']:>3}  {color}{s['start']:>7.3f}s{_RESET}"
              f"  {color}{s['end']:>7.3f}s{_RESET}"
              f"  {color}{s['duration']:>7.3f}s{_RESET}")


# ── 入口 ────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="流式 Silero VAD 验证脚本（双检测器）")
    parser.add_argument(
        "--audio",
        default=str(ROOT / "tests" / "test_output.mp3"),
        help="测试音频路径（默认: tests/test_output.mp3）",
    )
    parser.add_argument(
        "--chunk-ms",
        type=int,
        default=200,
        help="模拟麦克风每次推入的音频长度（毫秒，默认 200）",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.5,
        help="Silero VAD 语音概率阈值（默认 0.5）",
    )
    parser.add_argument(
        "--energy-threshold",
        type=float,
        default=0.01,
        help="能量（RMS）检测阈值（默认 0.01，适用于归一化 [-1,1] 音频）",
    )
    parser.add_argument(
        "--realtime",
        action="store_true",
        help="启用实时模拟（按音频时长 sleep），默认快速扫描",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="显示每帧 Silero 概率和 RMS 能量",
    )
    args = parser.parse_args()
    run(args.audio, args.chunk_ms, args.threshold, args.energy_threshold,
        args.realtime, args.verbose)


if __name__ == "__main__":
    main()
