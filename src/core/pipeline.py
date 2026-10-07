# -*- coding: utf-8 -*-
# 作者: cing  ·  https://github.com/cingzz
# 许可: GPL-3.0 + 商业授权（闭源/商用需向作者申请授权），见 LICENSE 与 LICENSE-COMMERCIAL.md
#
"""管线编排：采集 -> 断句 -> 云端识别 -> 翻译 -> 回调（UI/朗读/统计）。

线程模型（v0.2.16 重排：识别与翻译拆成两级流水线 + 同传草稿支路）
----------------------------------------------------------------
- 音频回调线程（sounddevice 内部）只做重采样、VAD 与入队；
- ASR worker：段 -> 文本；翻完**立刻**把文本交给 MT 队列（不等翻译）；
- MT worker：文本 -> 译文 -> on_subtitle。
  此前 ASR+MT 挤在同一个 worker 里串行，云端一卡（重试最坏 ~50s）
  后面所有句子全部排队——现在「翻译上一句」和「识别下一句」并行。
- 草稿 worker（同传增量）：说话期间 Segmenter 每 ~1s 送一版已积累音频，
  这里识别+翻译后经 on_partial 推给浮窗先出一版「草稿字幕」；
  说完后的最终段照常走 ASR->MT 全链，最终稿自动替换草稿。
- 每轮会话有 generation 号：stop() 后旧 worker 即使还阻塞在 HTTP 里
  （最坏 50s），也不会再消费新会话的队列——此前 stop 不 join + 复用
  _running，重启后新旧 worker 并发消费同一个队列（实测竞态）。
"""
from __future__ import annotations

import logging
import queue
import threading
import time
from dataclasses import dataclass, field

import numpy as np

from .audio_capture import AudioCapture, TARGET_SR, find_cable_devices
from .segmenter import Segmenter
from .config import AppConfig
from ..services.engine import CloudASR, Translator
from ..services.translation_clean import strip_decoration

log = logging.getLogger("valtrans.pipeline")


@dataclass
class SubtitleEvent:
    """一条完整字幕（识别+翻译完成）。"""
    original: str
    translated: str
    latency_ms: int          # 语音结束 -> 翻译完成
    asr_ms: int = 0
    mt_ms: int = 0
    fallback: bool = False    # 翻译是否走了降级
    partial: bool = False     # True = 同传草稿（浮窗先出，最终稿稍后替换）
    ts: float = field(default_factory=time.time)
    # ★ v0.2.21：这条字幕**该不该再单独显示一行原文**。
    #
    # 为什么要有这个字段（真机 截图）
    # ------------------------------------------
    # 队友说中文时，translate_gate 按规则**照抄****
    # （「别人说中文，你完全可以不用翻译照抄」），于是 original == translated。
    # 而 UI 原来无条件画两行 —— 同一句话被显示两遍。
    #
    # 为什么要放在**后端**算
    # --------------------
    # 「是不是中文」这个判断只有一份实现：`translate_gate.looks_chinese`。
    # 若让前端 JS 再判一次，就成了「产品一份、测试一份」，
    # 必然随时间漂移 —— 铁律：同一个判断只能有一份实现，否则两份实现必然漂移
    # （同一个判断只能有一份实现；`audit_gate_consistency` 就是为它存在的）。
    # 所以这里算好一个布尔送过去，前端只读不算。
    show_original: bool = True


def _want_original_line(original: str, translated: str) -> bool:
    """这条字幕要不要**再单独显示一行原文**。

    「是不是中文」只有一份实现：`translate_gate.looks_chinese`，
    这里调用它而不是自己写一遍 —— 已有实现就复用，不重写
    「同一个判断只能有一份实现」，重复写必然漂移。

    两种情况返回 False：
      ① 原文已经是中文（照抄场景，译文就是原文的复制）
      ② 原文与译文完全相同（外语也可能在某个词上撞车）
    """
    o = (original or "").strip()
    t = (translated or "").strip()
    if not o or not t or o == t:
        return False
    try:
        from ..services.translate_gate import looks_chinese
        if looks_chinese(o):
            return False
    except Exception:
        return True          # 判定拿不到就照旧显示：宁可多一行，不可丢信息
    return True


class Pipeline:
    def __init__(self, cfg: AppConfig,
                 on_subtitle,           # Callable[[SubtitleEvent], None] 后台线程回调
                 on_status=None,        # Callable[[str], None] 状态变化
                 on_partial=None):      # Callable[[原文, 译文], None] 同传草稿
        self.cfg = cfg
        self.on_subtitle = on_subtitle
        self.on_status = on_status or (lambda s: None)
        self.on_partial = on_partial
        self.asr = CloudASR(cfg)
        self.mt = Translator(cfg)
        self._seg_q: queue.Queue = queue.Queue(maxsize=200)
        self._mt_q: queue.Queue = queue.Queue(maxsize=200)
        self._draft_q: queue.Queue = queue.Queue(maxsize=1)   # 草稿只留最新
        self._capture: AudioCapture | None = None
        self._segmenter: Segmenter | None = None
        self._asr_thread: threading.Thread | None = None
        self._mt_thread: threading.Thread | None = None
        self._draft_thread: threading.Thread | None = None
        self._running = threading.Event()
        self._gen = 0                    # 会话代号：旧 worker 一看不等就退
        self._last_final_ts = 0.0        # 最近一次最终段入队时间（草稿作废线）
        self._block_buf: list[np.ndarray] = []
        self._buf_lock = threading.Lock()
        # 外部门（如 TTS 播放标志）：置位时丢弃音频块，防止 loopback 模式朗读回声自触发
        self.external_gate: threading.Event | None = None
        # ★ v0.2.19：丢段回调（错误可见性）——丢段必须让用户看得见，
        #   否则是"软件活着但没字幕"的静默体验灾难（竞品共同教训）
        self.on_drop = None                  # Callable[[int], None]，参数=累计丢弃数
        self.stats = {"segments": 0, "ok": 0, "fail": 0, "dropped": 0}
        self.last_rms = 0.0   # 最近音频块电平（UI 电平表用）

    # ---------- 状态 ----------
    def _status(self, s: str) -> None:
        try:
            self.on_status(s)
        except Exception:
            pass

    # ---------- 启停 ----------
    def start(self) -> None:
        if self._running.is_set():
            return
        self._gen += 1
        gen = self._gen
        # 每轮会话**新队列**：上一轮遗留的段不会串台进新会话
        self._seg_q = queue.Queue(maxsize=200)
        self._mt_q = queue.Queue(maxsize=200)
        self._draft_q = queue.Queue(maxsize=1)
        try:
            self._segmenter = Segmenter(
                on_segment=lambda seg: self._enqueue(seg),
                on_draft=(self._enqueue_draft
                          if (self.on_partial
                              and getattr(self.cfg, "partial_enabled", True))
                          else None),
                draft_interval_s=max(0.5, float(getattr(
                    self.cfg, "draft_interval_ms", 1000)) / 1000.0),
                vad_mode=self.cfg.vad_mode,
                rms_threshold=self.cfg.rms_threshold,
                prebuffer_seconds=self.cfg.prebuffer_seconds,
                min_speech_ms=self.cfg.min_speech_ms,
                silence_ms=self.cfg.silence_ms,
                max_segment_s=self.cfg.max_segment_s,
            )
            self._capture = AudioCapture(
                on_block=self._on_block,
                mode=self.cfg.capture_mode,
                cable_name=self.cfg.cable_output_device,
                loopback_name=self.cfg.loopback_device,
                monitor_relay=self.cfg.monitor_relay,
            )
        except Exception:
            self._segmenter = None
            self._capture = None
            raise
        self._running.set()
        self._asr_thread = threading.Thread(target=self._asr_loop, args=(gen,),
                                            daemon=True, name="asr-thread")
        self._mt_thread = threading.Thread(target=self._mt_loop, args=(gen,),
                                           daemon=True, name="mt-thread")
        self._asr_thread.start()
        self._mt_thread.start()
        if self.on_partial and getattr(self.cfg, "partial_enabled", True):
            self._draft_thread = threading.Thread(
                target=self._draft_loop, args=(gen,), daemon=True,
                name="draft-thread")
            self._draft_thread.start()
        try:
            self._capture.start()
        except Exception:
            # ★ v0.2.16：启动失败必须回滚——此前 _running 保持置位，
            #   用户再点「开始」在 start() 第一行静默 return（UI 却亮绿灯）
            self._running.clear()
            self._gen += 1
            self._join_workers()
            try:
                self._capture.stop()
            except Exception:
                pass
            self._capture = None
            self._segmenter = None
            raise
        self._status("listening:" + self._capture.device_desc)
        log.info("pipeline started: %s mode=%s vad=%s partial=%s",
                 self._capture.device_desc, self.cfg.capture_mode,
                 self.cfg.vad_mode,
                 bool(self.on_partial and getattr(self.cfg, "partial_enabled", True)))

    def stop(self) -> None:
        if not self._running.is_set():
            return
        self._running.clear()
        self._gen += 1          # 还阻塞在 HTTP 里的旧 worker 醒来后直接退
        if self._capture:
            self._capture.stop()
            self._capture = None
        self._join_workers()
        for q in (self._seg_q, self._mt_q, self._draft_q):
            try:
                while True:
                    q.get_nowait()
            except queue.Empty:
                pass
        self._status("stopped")
        log.info("pipeline stopped, stats=%s", self.stats)

    def _join_workers(self) -> None:
        for t in (self._asr_thread, self._mt_thread, self._draft_thread):
            if t is not None and t.is_alive():
                t.join(timeout=1.5)
        self._asr_thread = self._mt_thread = self._draft_thread = None

    # ---------- 音频路径 ----------
    def _on_block(self, block: np.ndarray) -> None:
        """音频线程回调：直接喂给 segmenter.push（silero 单块 0.13ms，可安全内联）。"""
        if self._segmenter is None:
            return
        if self.external_gate is not None and self.external_gate.is_set():
            return  # TTS 播放中：丢弃采集块，防止自己朗读的声音再被识别（回声死循环）
        try:
            self.last_rms = float(np.sqrt(np.mean(block ** 2)))
            self._segmenter.push(block)
        except Exception:
            log.exception("segmenter push failed")

    def _enqueue(self, seg: np.ndarray) -> None:
        self._last_final_ts = time.time()   # 草稿作废线：最终稿已在路上
        try:
            self._seg_q.put_nowait((time.time(), seg))
        except queue.Full:
            try:
                self._seg_q.get_nowait()   # 丢最旧
                self._seg_q.put_nowait((time.time(), seg))
            except Exception:
                pass
            # ★ v0.2.16：丢段必须留痕——用户视角「说了没字幕」此前无线索
            self.stats["dropped"] += 1
            log.warning("识别队列满，丢最旧（累计丢 %d 段）", self.stats["dropped"])
            if self.on_drop:
                try:
                    self.on_drop(self.stats["dropped"])
                except Exception:
                    pass
        self.stats["segments"] += 1

    def _enqueue_draft(self, seg: np.ndarray) -> None:
        """音频回调线程：草稿尽力而为，worker 忙就丢本次（队列容量=1 留最新）。"""
        try:
            self._draft_q.put_nowait((time.time(), seg))
        except queue.Full:
            pass

    # ---------- ASR worker ----------
    def _asr_loop(self, gen: int) -> None:
        while self._running.is_set() and gen == self._gen:
            try:
                t_end, seg = self._seg_q.get(timeout=0.5)
            except queue.Empty:
                continue
            if gen != self._gen:
                break
            try:
                self._status("recognizing")
                text, _hint = self.asr.transcribe(seg, TARGET_SR)
                asr_ms = int(self.asr.last_latency * 1000)
                if not text:
                    self._status("listening")
                    continue
                # v0.2.11（真机 实测）：
                # 云端 ASR 会自作聪明地给识别结果加括号注释、emoji、句号，
                # 在进翻译之前剥掉，不让脏数据流下去。
                text = strip_decoration(text)
                if not text:
                    self._status("listening")
                    continue
                try:
                    self._mt_q.put_nowait((t_end, text, asr_ms))
                except queue.Full:
                    try:
                        self._mt_q.get_nowait()
                        self._mt_q.put_nowait((t_end, text, asr_ms))
                    except Exception:
                        pass
                    self.stats["dropped"] += 1
                    log.warning("翻译队列满，丢最旧（累计丢 %d 段）", self.stats["dropped"])
                    if self.on_drop:
                        try:
                            self.on_drop(self.stats["dropped"])
                        except Exception:
                            pass
                self._status("listening")
            except Exception as e:
                self.stats["fail"] += 1
                self._status(f"asr_error:{e}")
                log.warning("ASR failed: %s", e)

    # ---------- MT worker ----------
    def _mt_loop(self, gen: int) -> None:
        while self._running.is_set() and gen == self._gen:
            try:
                t_end, text, asr_ms = self._mt_q.get(timeout=0.5)
            except queue.Empty:
                continue
            if gen != self._gen:
                break
            try:
                translated = self.mt.translate(text, self.cfg.target_lang)
                mt_ms = int(self.mt.last_latency * 1000)
                self.stats["ok"] += 1
                ev = SubtitleEvent(original=text, translated=translated,
                                   latency_ms=int((time.time() - t_end) * 1000),
                                   asr_ms=asr_ms, mt_ms=mt_ms,
                                   fallback=self.mt.used_fallback)
                # v0.2.21：中文照抄时原文==译文，别让 UI 显示两遍一样的话
                ev.show_original = _want_original_line(text, translated)
            except Exception as me:
                self.stats["fail"] += 1
                ev = SubtitleEvent(original=text, translated="",
                                   latency_ms=int((time.time() - t_end) * 1000),
                                   asr_ms=asr_ms, fallback=True)
                ev.error = f"翻译失败: {me}"  # type: ignore[attr-defined]
            try:
                self.on_subtitle(ev)
            except Exception:
                log.exception("on_subtitle callback failed")

    # ---------- 草稿 worker（同传增量） ----------
    def _draft_loop(self, gen: int) -> None:
        while self._running.is_set() and gen == self._gen:
            try:
                t_created, seg = self._draft_q.get(timeout=0.5)
            except queue.Empty:
                continue
            if gen != self._gen:
                break
            # 这句话已经说完（最终段已入队）-> 所有滞留草稿作废
            if t_created <= self._last_final_ts:
                continue
            try:
                text, _ = self.asr.transcribe(seg, TARGET_SR)
                if not text:
                    continue
                text = strip_decoration(text)
                if not text or t_created <= self._last_final_ts:
                    continue
                trans = self.mt.translate(text, self.cfg.target_lang)
                if t_created <= self._last_final_ts:
                    continue      # 翻译期间说完了 -> 让位给最终稿
                self.on_partial(text, trans)
            except Exception:
                log.debug("同传草稿失败（忽略）", exc_info=True)
