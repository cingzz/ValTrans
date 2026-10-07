# -*- coding: utf-8 -*-
# 作者: cing  ·  https://github.com/cingzz
# 许可: GPL-3.0 + 商业授权（闭源/商用需向作者申请授权），见 LICENSE 与 LICENSE-COMMERCIAL.md
#
"""七个功能页面：主页 / 实时翻译 / 我的额度 / 字幕样式 / 设置 / 帮助 / 关于。

v2 重构要点（对应用户实测反馈）：
- 自适应：内容区随窗口伸缩，滚动区一律禁用横向滚动条，表单列加 stretch
- 性能：状态刷新只在颜色/文本变化时才 setStyleSheet；样式全部走 QSS 类选择器
- 字幕样式页：新增「字幕显示」总开关 + 所见即所得预览 + 调节即时生效（防抖）
- 设置页：麦克风测试改为「回声测试」（录音 2.5s → 外放回听，用户能亲耳确认）
"""
from __future__ import annotations

import os
import time

from PySide6.QtCore import Qt, Signal, QTimer, QSize
from PySide6.QtGui import QPainter, QColor, QFont
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
                               QComboBox, QLineEdit, QSlider, QCheckBox, QScrollArea,
                               QFrame, QGridLayout, QAbstractButton, QProgressBar,
                               QSizePolicy)

from . import theme
from .overlay import STYLES, STYLE_NAMES, ANIMS, ANIM_NAMES, _STYLE_DEF
from ..core.config import ASR_PRESETS, MT_PRESETS, LANGUAGE_NAMES


def card(parent=None) -> QFrame:
    c = QFrame(parent)
    c.setObjectName("Card")
    return c


class StatusDot(QLabel):
    """状态灯：颜色不变时不重设样式（高频刷新防抖）。"""

    def __init__(self):
        super().__init__()
        self.setFixedSize(14, 14)
        self._color = None

    def set_state(self, color: str):
        if color != self._color:
            self._color = color
            self.setStyleSheet(theme.status_qss(color))


class ToggleSwitch(QAbstractButton):
    """开关（状态语义：青绿=开启）。自绘锐角滑块，无动画保性能。"""

    def __init__(self, checked: bool = False):
        super().__init__()
        self.setCheckable(True)
        self.setChecked(checked)
        self.setCursor(Qt.PointingHandCursor)

    def sizeHint(self) -> QSize:
        return QSize(42, 22)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = 40, 20
        y = (self.height() - h) // 2
        on = self.isChecked()
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(theme.ACCENT2 if on else theme.BG3))
        p.drawRoundedRect(0, y, w, h, 10, 10)
        p.setBrush(QColor(theme.BG0) if on else QColor(theme.MUTED))
        x = w - 17 if on else 2
        p.drawEllipse(x, y + 2, 16, 16)


class HomePage(QWidget):
    start_stop_clicked = Signal()
    toggle_changed = Signal(str, bool)

    def __init__(self, cfg):
        super().__init__()
        self.cfg = cfg
        v = QVBoxLayout(self)
        v.setContentsMargins(28, 24, 28, 24)
        v.setSpacing(14)

        # 问候卡
        g = card()
        gv = QVBoxLayout(g)
        gv.setContentsMargins(24, 20, 24, 20)
        gv.setSpacing(6)
        self.hello = QLabel("欢迎回来，玩家！")
        self.hello.setObjectName("H1")
        self.sub = QLabel("队友外语 → 中文字幕浮窗 · 按住 PTT 说中文 → 译文自动复制")
        self.sub.setObjectName("Muted")
        gv.addWidget(self.hello)
        gv.addWidget(self.sub)
        v.addWidget(g)

        # 快捷面板
        q = card()
        ql = QVBoxLayout(q)
        ql.setContentsMargins(24, 20, 24, 20)
        ql.setSpacing(14)

        self.big_btn = QPushButton("▷  开始翻译")
        self.big_btn.setObjectName("Primary")
        self.big_btn.setMinimumHeight(54)
        self.big_btn.setCursor(Qt.PointingHandCursor)
        self.big_btn.clicked.connect(self.start_stop_clicked.emit)
        ql.addWidget(self.big_btn)

        row1 = QHBoxLayout()
        self.dot = StatusDot()
        self.dot.set_state(theme.MUTED)
        self.status = QLabel("未启动 · 选择下方语言后开始")
        row1.addWidget(self.dot)
        row1.addWidget(self.status)
        row1.addStretch(1)
        ql.addLayout(row1)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("我说中文译成"))
        self.reverse_lang = QComboBox()
        for code in ("en", "ja", "ko"):
            self.reverse_lang.addItem(LANGUAGE_NAMES[code], code)
        self.reverse_lang.setCurrentText(LANGUAGE_NAMES.get(cfg.reverse_target_lang, "英语"))
        self.reverse_lang.currentIndexChanged.connect(
            lambda i: self._set_cfg("reverse_target_lang", self.reverse_lang.currentData()))
        row2.addWidget(self.reverse_lang)
        row2.addSpacing(20)
        self.chk_orig = QCheckBox("显示原文")
        self.chk_orig.setChecked(cfg.show_original)
        self.chk_orig.toggled.connect(lambda b: self._set_cfg("show_original", b))
        row2.addWidget(self.chk_orig)
        self.chk_tts = QCheckBox("译文朗读")
        self.chk_tts.setChecked(cfg.tts_enabled)
        self.chk_tts.toggled.connect(lambda b: self._set_cfg("tts_enabled", b))
        row2.addWidget(self.chk_tts)
        self.chk_stream = QCheckBox("主播模式")
        self.chk_stream.setChecked(cfg.streamer_mode)
        self.chk_stream.toggled.connect(self._on_streamer)
        row2.addWidget(self.chk_stream)
        row2.addStretch(1)
        ql.addLayout(row2)

        # 采集模式提示（loopback 会采集整机声音，必须让用户知道）
        self.mode_hint = QLabel()
        self.mode_hint.setWordWrap(True)
        self.mode_hint.setStyleSheet(f"color:{theme.WARN}; font-size:12px;")
        self.mode_hint.hide()
        ql.addWidget(self.mode_hint)
        self.update_mode_hint()
        v.addWidget(q)

        # 状态卡
        s = card()
        sl = QGridLayout(s)
        sl.setContentsMargins(24, 16, 24, 16)
        sl.setHorizontalSpacing(24)
        self.lbl_audio = QLabel("音频: —")
        self.lbl_asr = QLabel("识别: —")
        self.lbl_mt = QLabel("翻译: —")
        self.lbl_latency = QLabel("延迟: —")
        for i, w_ in enumerate([self.lbl_audio, self.lbl_asr, self.lbl_mt, self.lbl_latency]):
            w_.setObjectName("Muted")
            sl.addWidget(w_, 0, i)
            sl.setColumnStretch(i, 1)
        v.addWidget(s)
        v.addStretch(1)

    def update_mode_hint(self):
        if self.cfg.capture_mode == "loopback":
            self.mode_hint.setText(
                "⚠ 当前为「整机输出采集」模式：电脑里的所有声音（视频/音乐/语音软件）都会被识别。"
                "只翻译游戏队友请到 设置 → 采集模式 改为「虚拟声卡线路」。")
            self.mode_hint.show()
        else:
            self.mode_hint.hide()

    def _set_cfg(self, key, val):
        setattr(self.cfg, key, val)
        self.cfg.save()
        self.toggle_changed.emit(key, bool(val) if isinstance(val, bool) else False)

    def _on_streamer(self, on: bool):
        self.cfg.streamer_mode = on
        self.cfg.save()
        if on:
            self.chk_tts.setChecked(False)

    def set_running(self, running: bool, desc: str = ""):
        if running:
            self.big_btn.setText("■  停止翻译")
            self.dot.set_state(theme.OK)
            self.status.setText(f"监听中 · {desc}")
        else:
            self.big_btn.setText("▷  开始翻译")
            self.dot.set_state(theme.MUTED)
            self.status.setText("未启动")

    def set_pipeline_status(self, s: str):
        base = s.split(":")[0]
        color = {"recognizing": theme.WARN, "listening": theme.OK,
                 "stopped": theme.MUTED}.get(base, theme.MUTED)
        self.dot.set_state(color)
        text = {"listening": "监听队友语音中…", "recognizing": "识别+翻译中…",
                "stopped": "已停止"}.get(base, s)
        if text != self.status.text():
            self.status.setText(text)


    def set_latency(self, ms: int):
        self.lbl_latency.setText(f"延迟: {ms}ms")


class LivePage(QWidget):
    def __init__(self, cfg):
        super().__init__()
        self.cfg = cfg
        v = QVBoxLayout(self)
        v.setContentsMargins(28, 24, 28, 24)
        v.setSpacing(12)

        head = QHBoxLayout()
        t = QLabel("实时翻译")
        t.setObjectName("H1")
        head.addWidget(t)
        head.addStretch(1)
        self.stat_segments = QLabel("本局 0 条")
        self.stat_latency = QLabel("平均延迟 —")
        self.stat_fails = QLabel("失败 0")
        for w_ in (self.stat_segments, self.stat_latency, self.stat_fails):
            w_.setObjectName("Chip")
            head.addWidget(w_)
        v.addLayout(head)

        # 字幕滚动区（只纵向滚动）
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        inner = QWidget()
        self.feed = QVBoxLayout(inner)
        self.feed.setContentsMargins(4, 4, 4, 4)
        self.feed.setSpacing(10)
        self.feed.addStretch(1)
        self.scroll.setWidget(inner)
        v.addWidget(self.scroll, 1)

        # 电平表 + PTT
        bottom = QHBoxLayout()
        self.level_label = QLabel("队友语音电平")
        self.level_label.setObjectName("Muted")
        self.level = QProgressBar()
        self.level.setRange(0, 100)
        self.level.setTextVisible(False)
        self.level.setFixedHeight(10)
        self.ptt_state = QLabel("PTT: 就绪")
        self.ptt_state.setObjectName("Muted")
        bottom.addWidget(self.level_label)
        bottom.addWidget(self.level, 1)
        bottom.addSpacing(20)
        bottom.addWidget(self.ptt_state)
        v.addLayout(bottom)

        self._count = 0
        self._fails = 0
        self._lat_sum = 0

    def add_subtitle(self, original, translated, latency_ms, fallback, error=""):
        self._count += 1
        if fallback:
            self._fails += 1
        self._lat_sum += latency_ms
        self.stat_segments.setText(f"本局 {self._count} 条")
        self.stat_latency.setText(f"平均延迟 {self._lat_sum // max(1, self._count)}ms")
        self.stat_fails.setText(f"失败 {self._fails}")

        c = card()
        cv = QVBoxLayout(c)
        cv.setContentsMargins(16, 10, 16, 12)
        cv.setSpacing(3)
        o = QLabel(original)
        o.setObjectName("Muted")
        o.setWordWrap(True)
        cv.addWidget(o)
        t = QLabel(translated if translated else (error or "翻译失败"))
        t.setStyleSheet("font-size:15px; font-weight:600; color:%s;"
                        % (theme.TEXT if translated else theme.DANGER))
        t.setWordWrap(True)
        cv.addWidget(t)
        meta = QLabel(f"{time.strftime('%H:%M:%S')} · {latency_ms}ms" + (" · 降级" if fallback else ""))
        meta.setObjectName("Muted")
        cv.addWidget(meta)
        self.feed.insertWidget(self.feed.count() - 1, c)
        if self.feed.count() > 51:
            it = self.feed.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        self.scroll.verticalScrollBar().setValue(self.scroll.verticalScrollBar().maximum())

    def set_level(self, rms: float):
        val = int(min(100, rms * 400))
        if val != self.level.value():
            self.level.setValue(val)

    def set_ptt(self, state: str):
        text = {"recording": "PTT: 录音中…", "translating": "PTT: 翻译中…",
                "ready": "PTT: 就绪"}.get(state, f"PTT: {state}")
        if text != self.ptt_state.text():
            self.ptt_state.setText(text)


class QuotaPage(QWidget):
    refresh_clicked = Signal()

    def __init__(self, cfg):
        super().__init__()
        self.cfg = cfg
        v = QVBoxLayout(self)
        v.setContentsMargins(28, 24, 28, 24)
        v.setSpacing(14)
        head = QHBoxLayout()
        t = QLabel("我的额度")
        t.setObjectName("H1")
        head.addWidget(t)
        head.addStretch(1)
        btn = QPushButton("查询云端余额")
        btn.clicked.connect(self.refresh_clicked.emit)
        head.addWidget(btn)
        v.addLayout(head)

        self.cards_layout = QGridLayout()
        self.cards_layout.setHorizontalSpacing(14)
        self.cards_layout.setVerticalSpacing(14)
        self.cards_layout.setColumnStretch(0, 1)
        self.cards_layout.setColumnStretch(1, 1)
        v.addLayout(self.cards_layout)
        self.note = QLabel("说明：本软件不内置账号体系，云端额度即各服务商 API 免费额度，以服务商官网为准。")
        self.note.setObjectName("Muted")
        self.note.setWordWrap(True)
        v.addWidget(self.note)
        v.addStretch(1)
        self._cards: dict[str, QLabel] = {}

    def set_quota(self, preset: str, text: str, ok: bool = True):
        if preset not in self._cards:
            c = card()
            cv = QVBoxLayout(c)
            cv.setContentsMargins(18, 14, 18, 14)
            name = QLabel(preset)
            name.setObjectName("H2")
            cv.addWidget(name)
            val = QLabel("—")
            val.setWordWrap(True)
            cv.addWidget(val)
            self._cards[preset] = val
            n = self.cards_layout.count()
            self.cards_layout.addWidget(c, n // 2, n % 2)
        self._cards[preset].setText(text)
        self._cards[preset].setStyleSheet("color:%s;" % (theme.TEXT if ok else theme.DANGER))


class StylesPage(QWidget):
    applied = Signal()

    def __init__(self, cfg, overlay_preview=None):
        super().__init__()
        self.cfg = cfg
        v = QVBoxLayout(self)
        v.setContentsMargins(28, 24, 28, 24)
        v.setSpacing(14)

        head = QHBoxLayout()
        t = QLabel("字幕样式")
        t.setObjectName("H1")
        head.addWidget(t)
        head.addStretch(1)
        # 总开关：字幕显示（用户反馈：不知道字幕开没开）
        head.addWidget(QLabel("字幕显示"))
        self.sw_overlay = ToggleSwitch(bool(getattr(cfg, "overlay_enabled", True)))
        self.sw_overlay.toggled.connect(self._toggle_overlay)
        head.addWidget(self.sw_overlay)
        self.lbl_state = QLabel("开启" if getattr(cfg, "overlay_enabled", True) else "关闭")
        self.lbl_state.setObjectName("H2")
        self.lbl_state.setStyleSheet("color:%s;" % (theme.OK if getattr(cfg, "overlay_enabled", True) else theme.MUTED))
        head.addWidget(self.lbl_state)
        v.addLayout(head)

        # 样式选择
        srow = QHBoxLayout()
        srow.addWidget(QLabel("样式"))
        self.style_btns = []
        for s in STYLES:
            b = QPushButton(STYLE_NAMES[s])
            b.setObjectName("Seg")
            b.setCheckable(True)
            b.setChecked(cfg.overlay_style == s)
            b.clicked.connect(lambda _=False, k=s: self._pick_style(k))
            self.style_btns.append(b)
            srow.addWidget(b)
        srow.addStretch(1)
        v.addLayout(srow)

        # 动画选择
        arow = QHBoxLayout()
        arow.addWidget(QLabel("动画"))
        self.anim_btns = []
        for a in ANIMS:
            b = QPushButton(ANIM_NAMES[a])
            b.setObjectName("Seg")
            b.setCheckable(True)
            b.setChecked(cfg.overlay_anim == a)
            b.clicked.connect(lambda _=False, k=a: self._pick_anim(k))
            self.anim_btns.append(b)
            arow.addWidget(b)
        arow.addStretch(1)
        v.addLayout(arow)

        # 调节（即时生效，防抖 350ms）
        grid = QGridLayout()
        grid.addWidget(QLabel("字号"), 0, 0)
        self.font_sl = QSlider(Qt.Horizontal)
        self.font_sl.setRange(14, 34)
        self.font_sl.setValue(cfg.overlay_font_size)
        self.font_lbl = QLabel(str(cfg.overlay_font_size))
        self.font_lbl.setMinimumWidth(28)
        grid.addWidget(self.font_sl, 0, 1)
        grid.addWidget(self.font_lbl, 0, 2)
        grid.addWidget(QLabel("透明度"), 1, 0)
        self.op_sl = QSlider(Qt.Horizontal)
        self.op_sl.setRange(30, 100)
        self.op_sl.setValue(int(cfg.overlay_opacity * 100))
        self.op_lbl = QLabel(str(self.op_sl.value()))
        self.op_lbl.setMinimumWidth(28)
        grid.addWidget(self.op_sl, 1, 1)
        grid.addWidget(self.op_lbl, 1, 2)
        grid.addWidget(QLabel("宽度"), 2, 0)
        self.w_sl = QSlider(Qt.Horizontal)
        self.w_sl.setRange(360, 900)
        self.w_sl.setValue(cfg.overlay_width)
        self.w_lbl = QLabel(str(cfg.overlay_width))
        self.w_lbl.setMinimumWidth(34)
        grid.addWidget(self.w_sl, 2, 1)
        grid.addWidget(self.w_lbl, 2, 2)
        grid.setColumnStretch(1, 1)
        v.addLayout(grid)

        # 所见即所得预览（样式/字号/透明度即时反映）
        self.preview_outer = QFrame()
        self.preview_outer.setObjectName("PreviewBox")
        pv = QVBoxLayout(self.preview_outer)
        pv.setContentsMargins(20, 16, 20, 16)
        self.prev_box = QFrame()
        self.prev_orig = QLabel("Enemy rotating to B, careful!")
        self.prev_trans = QLabel("敌人在转点 B，小心！")
        self.prev_badge = QLabel("预览")
        pv.addWidget(self.prev_box)
        self._rebuild_preview()
        v.addWidget(self.preview_outer)

        row = QHBoxLayout()
        self.apply_state = QLabel("")
        self.apply_state.setObjectName("Muted")
        row.addWidget(self.apply_state)
        row.addStretch(1)
        apply_btn = QPushButton("立即应用到浮窗")
        apply_btn.clicked.connect(self._apply_now)
        row.addWidget(apply_btn)
        v.addLayout(row)
        v.addStretch(1)

        # 防抖：滑杆拖动 350ms 后自动应用
        self._apply_timer = QTimer(self)
        self._apply_timer.setSingleShot(True)
        self._apply_timer.timeout.connect(self._apply_now)
        for sl in (self.font_sl, self.op_sl, self.w_sl):
            sl.valueChanged.connect(self._schedule_apply)
        self.font_sl.valueChanged.connect(lambda v_: self.font_lbl.setText(str(v_)))
        self.op_sl.valueChanged.connect(lambda v_: self.op_lbl.setText(str(v_)))
        self.w_sl.valueChanged.connect(lambda v_: self.w_lbl.setText(str(v_)))

    # ---- 预览 ----
    def _rebuild_preview(self):
        c = self.cfg
        style = c.overlay_style if c.overlay_style in _STYLE_DEF else "tactical"
        box_qss, o_qss, t_qss, b_qss = _STYLE_DEF[style]
        self.prev_box.setStyleSheet(box_qss)
        bv = self.prev_box.layout()
        if bv is None:
            bv = QVBoxLayout(self.prev_box)
            bv.setContentsMargins(16, 10, 16, 12)
            bv.setSpacing(2)
            self.prev_badge = QLabel("预览")
            self.prev_orig = QLabel("")
            self.prev_trans = QLabel("")
            bv.addWidget(self.prev_badge)
            bv.addWidget(self.prev_orig)
            bv.addWidget(self.prev_trans)
        self.prev_box.setStyleSheet(box_qss)
        self.prev_orig.setStyleSheet(o_qss)
        self.prev_orig.setText("Enemy rotating to B, careful!")
        self.prev_orig.setVisible(bool(getattr(c, "show_original", True)))
        self.prev_trans.setStyleSheet(t_qss.format(fs=c.overlay_font_size))
        self.prev_trans.setText("敌人在转点 B，小心！")
        self.prev_badge.setStyleSheet(b_qss)
        self.prev_box.setWindowOpacity(1.0)
        self.preview_outer.setGraphicsEffect(None)
        from PySide6.QtWidgets import QGraphicsOpacityEffect
        eff = QGraphicsOpacityEffect(self.preview_outer)
        eff.setOpacity(c.overlay_opacity)
        self.preview_outer.setGraphicsEffect(eff)

    # ---- 行为 ----
    def _toggle_overlay(self, on: bool):
        self.cfg.overlay_enabled = on
        self.cfg.save()
        self.lbl_state.setText("开启" if on else "关闭")
        self.lbl_state.setStyleSheet("color:%s;" % (theme.OK if on else theme.MUTED))
        self.applied.emit()

    def _pick_style(self, key):
        self.cfg.overlay_style = key
        for i, s in enumerate(STYLES):
            self.style_btns[i].setChecked(s == key)
        self._rebuild_preview()
        self._schedule_apply()

    def _pick_anim(self, key):
        self.cfg.overlay_anim = key
        for i, a in enumerate(ANIMS):
            self.anim_btns[i].setChecked(a == key)
        self._schedule_apply()

    def _schedule_apply(self):
        self._apply_timer.start(350)

    def _apply_now(self):
        self.cfg.overlay_font_size = self.font_sl.value()
        self.cfg.overlay_opacity = self.op_sl.value() / 100.0
        self.cfg.overlay_width = self.w_sl.value()
        self.cfg.save()
        self.applied.emit()
        self.apply_state.setText(f"已应用 ✓  {time.strftime('%H:%M:%S')}")


class SettingsPage(QWidget):
    test_asr_clicked = Signal()
    test_mt_clicked = Signal()
    mic_test_clicked = Signal()
    tts_preview_clicked = Signal()
    selftest_clicked = Signal()
    settings_saved = Signal()

    def __init__(self, cfg):
        super().__init__()
        self.cfg = cfg
        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 24, 28, 24)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        body = QWidget()
        v = QVBoxLayout(body)
        v.setSpacing(14)

        t = QLabel("设置")
        t.setObjectName("H1")
        v.addWidget(t)

        # ---- 音频 ----
        c1 = card()
        g1 = QGridLayout(c1)
        g1.setContentsMargins(20, 16, 20, 16)
        g1.setVerticalSpacing(10)
        g1.setHorizontalSpacing(12)
        g1.setColumnStretch(1, 1)
        title = QLabel("音频")
        title.setObjectName("H2")
        g1.addWidget(title, 0, 0, 1, 3)
        g1.addWidget(QLabel("采集模式"), 1, 0)
        self.mode = QComboBox()
        self.mode.addItem("虚拟声卡线路（推荐·只采队友人声）", "cable")
        self.mode.addItem("整机输出 Loopback（免驱动·含电脑全部声音）", "loopback")
        self.mode.setCurrentIndex(0 if cfg.capture_mode == "cable" else 1)
        g1.addWidget(self.mode, 1, 1, 1, 2)
        g1.addWidget(QLabel("采集源设备"), 2, 0)
        self.dev = QComboBox()
        self._fill_devices()
        g1.addWidget(self.dev, 2, 1, 1, 2)
        g1.addWidget(QLabel("我的麦克风"), 3, 0)
        self.mic = QComboBox()
        self._fill_mics()
        g1.addWidget(self.mic, 3, 1)
        self.btn_mic_test = QPushButton("🎙 回声测试（录 2.5 秒并回放）")
        self.btn_mic_test.clicked.connect(self.mic_test_clicked.emit)
        g1.addWidget(self.btn_mic_test, 3, 2)
        g1.addWidget(QLabel("断句方式"), 4, 0)
        self.vad = QComboBox()
        self.vad.addItem("Silero 智能断句（推荐）", "silero")
        self.vad.addItem("纯音量阈值（零模型）", "rms")
        self.vad.setCurrentIndex(0 if cfg.vad_mode == "silero" else 1)
        g1.addWidget(self.vad, 4, 1, 1, 2)
        g1.addWidget(QLabel("音量阈值"), 5, 0)
        self.rms_sl = QSlider(Qt.Horizontal)
        self.rms_sl.setRange(1, 100)
        self.rms_sl.setValue(int(cfg.rms_threshold * 1000))
        g1.addWidget(self.rms_sl, 5, 1, 1, 2)
        self.mic_hint = QLabel("回声测试：点按钮后对着麦克风说句话，2.5 秒后电脑会把你的声音放出来——"
                               "能听到自己 = 麦克风正常。")
        self.mic_hint.setObjectName("Muted")
        self.mic_hint.setWordWrap(True)
        g1.addWidget(self.mic_hint, 6, 0, 1, 3)
        v.addWidget(c1)

        # ---- 云服务 ----
        c2 = card()
        g2 = QGridLayout(c2)
        g2.setContentsMargins(20, 16, 20, 16)
        g2.setVerticalSpacing(10)
        g2.setHorizontalSpacing(12)
        g2.setColumnStretch(2, 1)
        title2 = QLabel("云服务（BYOK：填入你自己注册的 API Key）")
        title2.setObjectName("H2")
        g2.addWidget(title2, 0, 0, 1, 4)

        g2.addWidget(QLabel("语音识别"), 1, 0)
        self.asr_preset = QComboBox()
        for k, p in ASR_PRESETS.items():
            self.asr_preset.addItem(p["label"], k)
        self.asr_preset.setCurrentIndex(list(ASR_PRESETS).index(cfg.asr_preset)
                                        if cfg.asr_preset in ASR_PRESETS else 0)
        g2.addWidget(self.asr_preset, 1, 1)
        self.asr_key = QLineEdit(cfg.asr_keys.get(cfg.asr_preset, ""))
        self.asr_key.setPlaceholderText("粘贴 API Key（保存在本机配置文件）")
        g2.addWidget(self.asr_key, 1, 2)
        asr_test = QPushButton("测试")
        asr_test.clicked.connect(self.test_asr_clicked.emit)
        g2.addWidget(asr_test, 1, 3)

        g2.addWidget(QLabel("翻译"), 2, 0)
        self.mt_preset = QComboBox()
        for k, p in MT_PRESETS.items():
            self.mt_preset.addItem(p["label"], k)
        self.mt_preset.setCurrentIndex(list(MT_PRESETS).index(cfg.mt_preset)
                                       if cfg.mt_preset in MT_PRESETS else 0)
        g2.addWidget(self.mt_preset, 2, 1)
        self.mt_key = QLineEdit(cfg.mt_keys.get(cfg.mt_preset, ""))
        self.mt_key.setPlaceholderText("粘贴 API Key")
        g2.addWidget(self.mt_key, 2, 2)
        mt_test = QPushButton("测试")
        mt_test.clicked.connect(self.test_mt_clicked.emit)
        g2.addWidget(mt_test, 2, 3)

        self.asr_hint = QLabel("提示：SenseVoice 支持中/英/日/韩/粤；巴西服等葡语需选 Groq/OpenAI 预设。")
        self.asr_hint.setObjectName("Muted")
        self.asr_hint.setWordWrap(True)
        g2.addWidget(self.asr_hint, 3, 0, 1, 4)
        v.addWidget(c2)

        # ---- 译文朗读音色 ----
        c4 = card()
        g4 = QGridLayout(c4)
        g4.setContentsMargins(20, 16, 20, 16)
        g4.setVerticalSpacing(10)
        g4.setHorizontalSpacing(12)
        g4.setColumnStretch(1, 1)
        title4 = QLabel("译文朗读音色（本地播放，队友听不到）")
        title4.setObjectName("H2")
        g4.addWidget(title4, 0, 0, 1, 3)
        g4.addWidget(QLabel("音色"), 1, 0)
        self.voice = QComboBox()
        from ..services.tts import VOICE_CATALOG
        self._voice_names = {}
        # ⚠ 与 src/uiweb/api.py:get_voices 同一道修复（v0.2.10 起）——
        #   这里原来也是 `for name, label, _langs, _multi in VOICE_CATALOG`，
        #   但 v0.2.9 把音色改成 6 元组（加 desc + prosody），于是**每次构建
        #   这一页都抛 ValueError: too many values to unpack**。
        #   v0.2.10 只修了 Web 界面那处，Qt 兜底界面漏了 —— 只有
        #   phase2_ui_test.py 走到它，而那脚本不在总闸里，
        #   于是「VALTRANS_UI=qt 启动即崩」一直没人发现（2026-10-05 抓到）。
        # 防御：按位置取 + 长度兜底，目录再加字段也不会再炸。
        for item in VOICE_CATALOG:
            name = item[0]
            label = item[1] if len(item) > 1 else name
            self.voice.addItem(label, name)
            self._voice_names[name] = label
        if cfg.tts_voice:
            idx = self.voice.findData(cfg.tts_voice)
            if idx >= 0:
                self.voice.setCurrentIndex(idx)
        g4.addWidget(self.voice, 1, 1)
        preview_btn = QPushButton("🔊 试听")
        preview_btn.clicked.connect(self.tts_preview_clicked.emit)
        g4.addWidget(preview_btn, 1, 2)
        g4.addWidget(QLabel(f"语速"), 2, 0)
        self.rate_sl = QSlider(Qt.Horizontal)
        self.rate_sl.setRange(-50, 50)
        self.rate_sl.setValue(cfg.tts_rate)
        self.rate_lbl = QLabel(f"{cfg.tts_rate:+d}%")
        self.rate_lbl.setMinimumWidth(44)
        self.rate_sl.valueChanged.connect(lambda v: self.rate_lbl.setText(f"{v:+d}%"))
        g4.addWidget(self.rate_sl, 2, 1)
        g4.addWidget(self.rate_lbl, 2, 2)
        g4.addWidget(QLabel(f"音调"), 3, 0)
        self.pitch_sl = QSlider(Qt.Horizontal)
        self.pitch_sl.setRange(-50, 50)
        self.pitch_sl.setValue(cfg.tts_pitch)
        self.pitch_lbl = QLabel(f"{cfg.tts_pitch:+d}Hz")
        self.pitch_lbl.setMinimumWidth(44)
        self.pitch_sl.valueChanged.connect(lambda v: self.pitch_lbl.setText(f"{v:+d}Hz"))
        g4.addWidget(self.pitch_sl, 3, 1)
        g4.addWidget(self.pitch_lbl, 3, 2)
        g4.addWidget(QLabel("提示：语速 +20% 更接近实战报点节奏；识别中会自动暂停朗读防回声。"), 4, 0, 1, 3)
        v.addWidget(c4)

        # ---- 一键自测 ----
        c5 = card()
        g5 = QGridLayout(c5)
        g5.setContentsMargins(20, 16, 20, 16)
        g5.setHorizontalSpacing(12)
        g5.setColumnStretch(1, 1)
        title5 = QLabel("一键自测（延迟与准确率）")
        title5.setObjectName("H2")
        g5.addWidget(title5, 0, 0, 1, 2)
        self.btn_selftest = QPushButton("▶ 运行自测（3 句，约 15 秒）")
        self.btn_selftest.setObjectName("Primary")
        self.btn_selftest.clicked.connect(self.selftest_clicked.emit)
        g5.addWidget(self.btn_selftest, 1, 0)
        self.selftest_state = QLabel("用当前填写的 Key，对内置日/英/葡语样本跑「识别→翻译」，"
                                     "输出逐句延迟与识别结果。")
        self.selftest_state.setObjectName("Muted")
        self.selftest_state.setWordWrap(True)
        g5.addWidget(self.selftest_state, 2, 0, 1, 2)
        v.addWidget(c5)

        # ---- 热键与模式 ----
        c3 = card()
        g3 = QGridLayout(c3)
        g3.setContentsMargins(20, 16, 20, 16)
        g3.setVerticalSpacing(10)
        g3.setHorizontalSpacing(12)
        g3.setColumnStretch(1, 1)
        title3 = QLabel("热键与模式")
        title3.setObjectName("H2")
        g3.addWidget(title3, 0, 0, 1, 2)
        g3.addWidget(QLabel("锁定浮窗"), 1, 0)
        self.hk_lock = QLineEdit(cfg.hotkey_lock)
        g3.addWidget(self.hk_lock, 1, 1)
        g3.addWidget(QLabel("回看字幕"), 2, 0)
        self.hk_review = QLineEdit(cfg.hotkey_review)
        g3.addWidget(self.hk_review, 2, 1)
        g3.addWidget(QLabel("按住说中文(PTT)"), 3, 0)
        self.hk_ptt = QLineEdit(cfg.hotkey_ptt)
        g3.addWidget(self.hk_ptt, 3, 1)
        self.chk_copy = QCheckBox("PTT 译文自动复制进剪贴板")
        self.chk_copy.setChecked(cfg.auto_copy)
        g3.addWidget(self.chk_copy, 4, 0, 1, 2)
        g3.addWidget(QLabel("翻译模式"), 5, 0)
        self.mode_asr = QComboBox()
        self.mode_asr.addItem("快速模式", "fast")
        self.mode_asr.addItem("精准模式（更高质量·稍慢）", "precision")
        self.mode_asr.setCurrentIndex(0 if cfg.asr_mode == "fast" else 1)
        g3.addWidget(self.mode_asr, 5, 1)
        v.addWidget(c3)

        save = QPushButton("保存全部设置")
        save.setObjectName("Primary")
        save.clicked.connect(self._save)
        v.addWidget(save)
        v.addStretch(1)

        scroll.setWidget(body)
        outer.addWidget(scroll)

    def _fill_devices(self):
        import sounddevice as sd
        self.dev.clear()
        for i, d in enumerate(sd.query_devices()):
            if d["max_input_channels"] > 0 and "WASAPI" in sd.query_hostapis(d["hostapi"])["name"]:
                self.dev.addItem(d["name"], d["name"])
        names = [self.dev.itemText(i) for i in range(self.dev.count())]
        want = self.cfg.cable_output_device or "CABLE Output"
        for n in names:
            if want.lower() in n.lower():
                self.dev.setCurrentText(n)
                break

    def _fill_mics(self):
        import sounddevice as sd
        self.mic.clear()
        self.mic.addItem("系统默认", "")
        for i, d in enumerate(sd.query_devices()):
            if d["max_input_channels"] > 0 and "WASAPI" in sd.query_hostapis(d["hostapi"])["name"]:
                self.mic.addItem(d["name"], d["name"])
        if self.cfg.mic_device:
            for i in range(self.mic.count()):
                if self.cfg.mic_device.lower() in self.mic.itemText(i).lower():
                    self.mic.setCurrentIndex(i)
                    break

    def _save(self):
        cfg = self.cfg
        cfg.capture_mode = self.mode.currentData()
        cfg.cable_output_device = self.dev.currentText()
        cfg.mic_device = self.mic.currentData() or ""
        cfg.vad_mode = self.vad.currentData()
        cfg.rms_threshold = self.rms_sl.value() / 1000.0
        cfg.asr_preset = self.asr_preset.currentData()
        if self.asr_key.text().strip():
            cfg.asr_keys[cfg.asr_preset] = self.asr_key.text().strip()
        cfg.mt_preset = self.mt_preset.currentData()
        if self.mt_key.text().strip():
            cfg.mt_keys[cfg.mt_preset] = self.mt_key.text().strip()
        cfg.hotkey_lock = self.hk_lock.text().strip() or cfg.hotkey_lock
        cfg.hotkey_review = self.hk_review.text().strip() or cfg.hotkey_review
        cfg.hotkey_ptt = self.hk_ptt.text().strip() or cfg.hotkey_ptt
        cfg.auto_copy = self.chk_copy.isChecked()
        cfg.asr_mode = self.mode_asr.currentData()
        cfg.tts_voice = self.voice.currentData() or ""
        cfg.tts_rate = self.rate_sl.value()
        cfg.tts_pitch = self.pitch_sl.value()
        cfg.save()
        self.asr_hint.setText("已保存 ✓（重启翻译后生效）")
        self.settings_saved.emit()


class HelpPage(QWidget):
    def __init__(self, cfg):
        super().__init__()
        v = QVBoxLayout(self)
        v.setContentsMargins(28, 24, 28, 24)
        t = QLabel("帮助与排障")
        t.setObjectName("H1")
        v.addWidget(t)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        body = QWidget()
        bv = QVBoxLayout(body)
        items = [
            ("没有字幕？",
             "按顺序检查：① 字幕样式页右上角「字幕显示」开关是否为开启；"
             "② 主页已点「开始翻译」且实时翻译页电平表有跳动；"
             "③ cable 模式需在游戏内把「语音聊天输出设备」设为 CABLE Input。"),
            ("字幕一直自动触发个不停？",
             "「整机输出采集(loopback)」模式会连电脑里的视频、音乐、语音软件一起识别；"
             "软件朗读译文时也会自动暂停采集防止「自己触发自己」。只翻译队友请改用「虚拟声卡线路」模式。"),
            ("有字幕但听不到队友声音？",
             "软件已内置「软件级监听」（设置→音频）：采集到队友声音会自动回放到你的耳机，"
             "无需在 Windows 声音面板手动设置侦听。若仍无声，检查系统音量与输出设备选择。"),
            ("自己按 PTT 说话没反应？",
             "检查设置页「我的麦克风」是否选了真实麦克风（不要选 CABLE 设备），"
             "并点「回声测试」确认麦克风正常；Windows 设置→隐私→麦克风 已允许桌面应用。"),
            ("字幕挡住鼠标操作？",
             "双击浮窗或按锁定热键（默认 Ctrl+Alt+Q）锁定后即鼠标穿透；未锁定时可拖动位置。"),
            ("字幕不见了？",
             "① 字幕样式页「字幕显示」开关是否被关掉；② 游戏必须用「无边框窗口」显示模式——"
             "独占全屏会盖住所有置顶浮窗（设置→视频→显示模式→无边框窗口）。"),
            ("识别/翻译失败？",
             "检查设置页 API Key 是否有效（点「测试」）；免费额度是否用尽；网络是否可达。"
             "翻译失败时浮窗仍显示原文。"),
            ("朗读没有声音？",
             "「多语人声」音色偶尔在微软服务端不可用，软件会自动换普通音色朗读；"
             "若仍无声，在设置页换一个音色并点「试听」。"),
        ]
        for q_, a_ in items:
            c = card()
            cv = QVBoxLayout(c)
            cv.setContentsMargins(18, 14, 18, 14)
            cv.setSpacing(4)
            qt = QLabel(q_)
            qt.setObjectName("H2")
            at = QLabel(a_)
            at.setWordWrap(True)
            cv.addWidget(qt)
            cv.addWidget(at)
            bv.addWidget(c)
        # 免责声明
        c = card()
        cv = QVBoxLayout(c)
        cv.setContentsMargins(18, 14, 18, 14)
        dt = QLabel("免责声明")
        dt.setObjectName("H2")
        da = QLabel("本软件为第三方工具，与 Riot Games 及《无畏契约》官方无任何关联。软件仅读取系统音频，"
                    "不注入游戏进程、不读取游戏内存、不修改游戏文件。使用任何第三方软件均存在被游戏反作弊"
                    "系统处理的理论风险，请自行评估并承担。本软件按现状提供，不承诺任何账号安全。")
        da.setWordWrap(True)
        cv.addWidget(dt)
        cv.addWidget(da)
        bv.addWidget(c)
        bv.addStretch(1)
        scroll.setWidget(body)
        v.addWidget(scroll, 1)


class AboutPage(QWidget):
    def __init__(self, cfg, version):
        super().__init__()
        self.cfg = cfg
        self.version = version
        v = QVBoxLayout(self)
        v.setContentsMargins(28, 24, 28, 24)
        v.setSpacing(12)
        t = QLabel("关于")
        t.setObjectName("H1")
        v.addWidget(t)
        c = card()
        cv = QVBoxLayout(c)
        cv.setContentsMargins(20, 16, 20, 16)
        cv.setSpacing(6)
        ver = QLabel(f"ValTrans  v{version}")
        ver.setStyleSheet(f"font-family:'{theme.FONT_DISPLAY}'; font-size:18px; font-weight:700;")
        cv.addWidget(ver)
        d = QLabel("瓦罗兰特外服实时语音翻译 · 云端识别翻译 / 本地仅采集音频与断句\n"
                   "架构参考同类开源项目公开信息，代码全部自研。")
        d.setObjectName("Muted")
        d.setWordWrap(True)
        cv.addWidget(d)
        self.update_lbl = QLabel("点击右下角检查更新")
        self.update_lbl.setObjectName("Muted")
        cv.addWidget(self.update_lbl)
        v.addWidget(c)
        btn = QPushButton("检查更新")
        btn.clicked.connect(self._check)
        v.addWidget(btn)
        v.addStretch(1)

    def _check(self):
        from ..core.security import safe_client
        from ..core.config import CONFIG_DIR
        url_file = CONFIG_DIR / "update_url.txt"
        url = url_file.read_text(encoding="utf-8").strip() if url_file.exists() else ""
        if not url:
            self.update_lbl.setText("未配置更新源（可在 %s 写入更新清单 URL）" % url_file)
            return
        try:
            with safe_client(timeout=8) as cl:
                r = cl.get(url)
                latest = r.json().get("version", "")
            self.update_lbl.setText(f"最新版本: {latest}" + ("（已是最新）" if latest == self.version else ""))
        except Exception as e:
            self.update_lbl.setText(f"检查失败: {e}")
