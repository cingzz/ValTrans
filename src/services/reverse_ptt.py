# -*- coding: utf-8 -*-
# 作者: cing  ·  https://github.com/cingzz
# 许可: GPL-3.0 + 商业授权（闭源/商用需向作者申请授权），见 LICENSE 与 LICENSE-COMMERCIAL.md
#
"""反向翻译（PTT）：按住热键说中文 -> 云端识别 -> 翻译成目标外语 -> 自动复制剪贴板。"""
from __future__ import annotations

import logging
import threading
import time
from typing import Callable

import numpy as np
import sounddevice as sd

TARGET_SR = 16000

log = logging.getLogger("valtrans.ptt")


class ReversePTT:
    """按住 PTT 键录音，松开后：云端识别(zh) -> 翻译 -> 复制剪贴板。

    on_result(translated_text, original_text) 与 on_state(str) 均在后台线程回调。
    """

    def __init__(self, cfg, asr, translator,
                 on_result: Callable[[str, str], None],
                 on_state: Callable[[str], None] | None = None):
        self.cfg = cfg
        self.asr = asr
        self.translator = translator
        self.on_result = on_result
        self.on_state = on_state or (lambda s: None)
        self._listener = None
        self._recording = False
        self._frames: list[np.ndarray] = []
        self._stream = None
        self._lock = threading.Lock()
        self._ptt_tail = None
        self._ptt_mods: set = set()
        self._ptt_pressed: set = set()
        # 录音期间累积的麦克风电平（RMS），供 UI 画律动条
        self._level: float = 0.0

    # ---------- 生命周期 ----------
    def start(self) -> None:
        from pynput import keyboard
        # ★ v0.2.16：PTT = 热键序列的**最后一个键** + **修饰键必须按住**。
        #   旧实现只匹配尾键且完全不校验修饰键——默认 <ctrl>+<alt>+s 时，
        #   游戏里裸按 S（倒退键）、聊天打字带 s 都会触发送话开麦。
        #   单键热键（无修饰键）行为不变：空修饰键集合恒为按住。
        keys = keyboard.HotKey.parse(self.cfg.hotkey_ptt)
        self._ptt_tail = keys[-1]
        self._ptt_mods: set = set(keys[:-1])
        self._ptt_pressed: set = set()   # 当前按住的修饰键
        self._listener = keyboard.Listener(on_press=self._on_press, on_release=self._on_release)
        self._listener.start()

    def stop(self) -> None:
        if self._listener is not None:
            self._listener.stop()
            self._listener = None
        self._stop_mic()

    # ---------- 按键 ----------
    def _canon(self, key):
        """按键归一（Key.ctrl_l -> Key.ctrl、大小写等），与 HotKey.parse 同一套。"""
        try:
            return self._listener.canonical(key)
        except Exception:
            return key

    def _on_press(self, key) -> None:
        k = self._canon(key)
        if k in self._ptt_mods:
            self._ptt_pressed.add(k)
            return
        if k == self._ptt_tail and self._ptt_mods.issubset(self._ptt_pressed):
            self._start_mic()

    def _on_release(self, key) -> None:
        k = self._canon(key)
        self._ptt_pressed.discard(k)
        if k == self._ptt_tail:
            self._finish()

    # ---------- 麦克风 ----------
    def _mic_device(self) -> int | None:
        name = self.cfg.mic_device
        if name:
            for i, d in enumerate(sd.query_devices()):
                if name.lower() in d["name"].lower() and d["max_input_channels"] > 0:
                    return i
        return None

    def _start_mic(self) -> None:
        with self._lock:
            if self._recording:
                return
            self._recording = True
            self._frames = []
            try:
                def _cb(ind, f, t, st):
                    import numpy as _np
                    mono = ind.mean(axis=1) if ind.ndim > 1 else ind
                    # 指数平滑，视觉上更像真实音量
                    inst = float(_np.sqrt(_np.mean(mono ** 2)))
                    self._level = inst * 0.6 + self._level * 0.4
                    self._frames.append(ind.copy())

                t0 = time.perf_counter()
                self._stream = sd.InputStream(
                    samplerate=TARGET_SR, channels=1, dtype="float32",
                    device=self._mic_device(), blocksize=480,
                    callback=_cb)
                self._stream.start()
                log.info("PTT 开始录音（开麦 %.0fms）",
                         (time.perf_counter() - t0) * 1000)
                self.on_state("recording")
            except Exception as e:
                self._recording = False
                # ★ v0.2.16：建流失败要关掉半成品流对象，否则下次覆盖泄漏
                try:
                    if self._stream is not None:
                        self._stream.close()
                except Exception:
                    pass
                self._stream = None
                self.on_state(f"mic_error:{e}")

    def _stop_mic(self) -> None:
        """stop() 的对外入口（api.stop 调）：连流带状态一起清。"""
        with self._lock:
            stream = self._stream
            self._stream = None
            self._level = 0.0
            self._recording = False
            self._frames = []
        self._close_stream(stream)

    @staticmethod
    def _close_stream(stream) -> None:
        """关流放后台线程：stream.stop() 要等驱动收尾，实测可能卡几百毫秒——
        绝不能挡在「松开」的关键路径上（否则橙色高亮赖着不走）。"""
        if stream is None:
            return
        try:
            stream.stop()
            stream.close()
        except Exception:
            log.debug("关闭录音流失败", exc_info=True)

    def _finish(self) -> None:
        # ★ 只做一次极快的「摘走状态」：帧列表、流句柄全部摘下来就放锁，
        #   _recording 立刻归 False（用户马上再按也能接住）。
        with self._lock:
            was = self._recording
            frames = self._frames
            stream = self._stream
            self._frames = []
            self._stream = None
            self._recording = False
            self._level = 0.0
        if not was or not frames:
            self._close_stream(stream)
            return
        # ★ 反馈先行：松开瞬间就退橙色高亮、显示「识别+翻译中…」，
        #   开麦/关流的驱动耗时全部挪到后台，绝不挡在状态推送前面。
        self.on_state("translating")
        threading.Thread(target=self._process, args=(frames,),
                         daemon=True).start()
        threading.Thread(target=self._close_stream, args=(stream,),
                         daemon=True).start()

    def _process(self, frames: list[np.ndarray]) -> None:
        t_total = time.perf_counter()
        try:
            audio = np.concatenate(frames)[:, 0]
            if len(audio) < TARGET_SR // 4:  # <0.25s 视为误触
                self.on_state("too_short")
                return
            t0 = time.perf_counter()
            text, _ = self.asr.transcribe(audio, TARGET_SR, language="zh")
            # ★ v0.2.16：日志只记耗时/长度，不落说话内容（语音是个人数据）
            log.info("PTT ASR %.0fms 音频%.1fs 文本%d字",
                     (time.perf_counter() - t0) * 1000, len(audio) / TARGET_SR,
                     len(text or ""))
            if not text:
                self.on_state("empty_result")
                return
            # 中间态：识别已出字、翻译还在跑 —— 卡面先显示原文，
            # 让用户立刻看到「听对了没有」（体感延迟的大头被盖掉）
            self.on_state(f"asr:{text}")
            t0 = time.perf_counter()
            translated = self.translator.translate(text, self.cfg.reverse_target_lang)
            log.info("PTT MT %.0fms 译文%d字（全程 %.0fms）",
                     (time.perf_counter() - t0) * 1000, len(translated or ""),
                     (time.perf_counter() - t_total) * 1000)
            if self.cfg.auto_copy and not self.cfg.streamer_mode:  # noqa: 已统一字段名
                import pyperclip
                pyperclip.copy(translated)
            self.on_result(translated, text)
            self.on_state("ready")
        except Exception as e:
            log.exception("PTT 处理失败")
            self.on_state(f"error:{e}")
