# -*- coding: utf-8 -*-
# 作者: cing  ·  https://github.com/cingzz
# 许可: GPL-3.0 + 商业授权（闭源/商用需向作者申请授权），见 LICENSE 与 LICENSE-COMMERCIAL.md
#
"""语音断句：silero VAD 流式推理（onnxruntime）+ RMS 能量兜底。

输入可变长 16k 单声道 float32 块（音频回调线程），内部 FIFO 缓冲切 512 样本定长块
喂 VAD；输出句段（含 3 秒预缓冲，实机测出的平衡点）：
    Segmenter.push(block) -> 句段完成时回调 on_segment(float32数组)

v0.2.16 同传增量：说话期间每 draft_interval_s 回调一次 on_draft(当前已积累音频)，
管线用它先出一版「草稿字幕」；说完后的最终段照常走 on_segment，替换草稿。

v0.2.16 修掉两个断句器 bug（都实测影响真实对局）：
  1. 15s 上限曾把「块数×采样率」当成样本数来比较，实际上限 468 秒
     —— 连续说话/误触发不闭合时能积累 7.8 分钟才断，最后丢一个
     巨型 WAV 给 ASR。
  2. 单帧误触发（枪声/键盘）进入 in_speech 后，若 speech_run 没攒到
     最小说话时长，段**永不闭合**，把之后的沉默+语音全并进一段。
     现在静音攒够即整体丢弃复位，不 emit。
"""
from __future__ import annotations

import math
import os
import threading
from collections import deque
from pathlib import Path
from typing import Callable

import numpy as np

TARGET_SR = 16000
CHUNK = 512        # 32ms
CTX = 64           # silero v5 上下文
SPEECH_TH = 0.5


def _asset(name: str) -> Path:
    here = Path(__file__).resolve().parent.parent.parent / "assets"
    p = here / name
    if not p.exists():
        alt = Path(os.environ.get("VALTRANS_ASSETS", "")) / name
        if alt.exists():
            return alt
        raise FileNotFoundError(f"缺少资源文件: {p}")
    return p


class _Silero:
    """silero v5 onnx 直推（无 torch 依赖）。"""

    def __init__(self):
        import onnxruntime as ort
        opts = ort.SessionOptions()
        opts.inter_op_num_threads = 1
        opts.intra_op_num_threads = 1
        opts.log_severity_level = 3
        self.sess = ort.InferenceSession(str(_asset("silero_vad.onnx")), sess_options=opts,
                                         providers=["CPUExecutionProvider"])
        self.state = np.zeros((2, 1, 128), dtype=np.float32)
        self.context = np.zeros(CTX, dtype=np.float32)
        self.lock = threading.Lock()

    def reset(self) -> None:
        with self.lock:
            self.state = np.zeros((2, 1, 128), dtype=np.float32)
            self.context = np.zeros(CTX, dtype=np.float32)

    def prob(self, block: np.ndarray) -> float:
        with self.lock:
            x = np.concatenate([self.context, block]).astype(np.float32).reshape(1, CTX + CHUNK)
            out, state = self.sess.run(None, {"input": x, "state": self.state})
            self.state = state
            self.context = x[0, -CTX:]
            return float(out[0][0])


class Segmenter:
    def __init__(self,
                 on_segment: Callable[[np.ndarray], None],
                 vad_mode: str = "silero",
                 rms_threshold: float = 0.01,
                 prebuffer_seconds: float = 3.0,
                 min_speech_ms: int = 250,
                 silence_ms: int = 300,
                 max_segment_s: float = 15.0,
                 on_draft: Callable[[np.ndarray], None] | None = None,
                 draft_interval_s: float = 1.0):
        self.on_segment = on_segment
        self.on_draft = on_draft
        self.vad_mode = vad_mode
        self.rms_threshold = rms_threshold
        self.prebuf: deque[np.ndarray] = deque(
            maxlen=max(1, int(prebuffer_seconds * TARGET_SR / CHUNK)))
        # ★ v0.2.16：ceil——floor 曾让 250ms 变 224ms、300ms 变 288ms，
        # 代码与声明的参数值不符
        self.min_speech_chunks = max(1, math.ceil(min_speech_ms / 32))
        self.silence_chunks = max(1, math.ceil(silence_ms / 32))
        self.max_chunks = int(max_segment_s * TARGET_SR / CHUNK)
        # 同传草稿：说话期间每隔 draft_every 块（32ms/块）送一版已积累音频
        self.draft_every = max(4, int(draft_interval_s * TARGET_SR / CHUNK))
        self._since_draft = 0
        # ★ v0.2.16：预构建 VAD 会话——此前在音频回调里懒加载，几十~几百 ms
        #   的 InferenceSession 创建发生在 PortAudio 回调线程上，
        #   刚 start 的第一批音频就有 overflow 风险
        self._vad = _Silero() if vad_mode == "silero" else None
        self._pending = np.zeros(0, dtype=np.float32)   # 变长输入 FIFO
        self._reset()
        self.lock = threading.Lock()

    # ---------- 内部状态 ----------
    def _reset(self) -> None:
        self.in_speech = False
        self.speech_run = 0
        self.silence_run = 0
        self.cur: list[np.ndarray] = []
        self.cur_len = 0
        self._since_draft = 0

    def _vad_speech(self, block: np.ndarray) -> bool:
        if self.vad_mode == "silero":
            if self._vad is None:
                self._vad = _Silero()
            return self._vad.prob(block) > SPEECH_TH
        return float(np.sqrt(np.mean(block ** 2))) > self.rms_threshold

    # ---------- 主入口（音频回调线程） ----------
    def push(self, block: np.ndarray) -> None:
        block = np.asarray(block, dtype=np.float32).ravel()
        if self._pending.size:
            self._pending = np.concatenate([self._pending, block])
        else:
            self._pending = block.copy()
        while self._pending.size >= CHUNK:
            chunk = self._pending[:CHUNK]
            self._pending = self._pending[CHUNK:]
            self._process_chunk(chunk)

    def _process_chunk(self, chunk: np.ndarray) -> None:
        self.prebuf.append(chunk)
        speech = self._vad_speech(chunk)
        with self.lock:
            if not self.in_speech:
                if speech:
                    self.in_speech = True
                    self.speech_run = 1
                    self.silence_run = 0
                    self.cur = list(self.prebuf)      # 句首含 3 秒预缓冲
                    self.cur_len = 512 * len(self.cur)
            else:
                self.cur.append(chunk)
                self.cur_len += CHUNK
                if speech:
                    self.speech_run += 1
                    self.silence_run = 0
                else:
                    self.silence_run += 1
                self._since_draft += 1
                # ★ v0.2.16 同传增量：确认真在说话（当前块仍是语音、
                #   不是误触发也没进入收尾静音）时，定期把已积累的
                #   音频送出去先出一版草稿
                if (self.on_draft is not None
                        and speech
                        and self.speech_run >= self.min_speech_chunks
                        and self._since_draft >= self.draft_every):
                    self._since_draft = 0
                    try:
                        self.on_draft(np.concatenate(self.cur))
                    except Exception:
                        pass      # 草稿是尽力而为，绝不拖垮音频回调线程
                # ★ v0.2.16 误触发丢弃：in_speech 可能只是一帧误判，
                #   speech_run 没攒到最小说话时长且静音已够 -> 整体丢弃复位。
                #   此前这种段永不闭合（配合上限写错最长吞 7.8 分钟）。
                if (self.silence_run >= self.silence_chunks
                        and self.speech_run < self.min_speech_chunks):
                    self._reset()
                    if self._vad is not None:
                        self._vad.reset()
                    return
                # ★ v0.2.16：上限比较单位修复（max_chunks 是块数，乘 CHUNK
                #   才是样本数；曾乘 TARGET_SR 让 15s 上限变成 468s）
                if ((self.silence_run >= self.silence_chunks and self.speech_run >= self.min_speech_chunks)
                        or self.cur_len >= self.max_chunks * CHUNK):
                    self._emit()

    def _emit(self) -> None:
        seg = np.concatenate(self.cur) if self.cur else np.zeros(0, dtype=np.float32)
        self._reset()
        if self._vad is not None:
            self._vad.reset()
        if len(seg) >= TARGET_SR // 4:  # 至少 0.25s
            self.on_segment(seg)
