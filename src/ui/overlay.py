# -*- coding: utf-8 -*-
# 作者: cing  ·  https://github.com/cingzz
# 许可: GPL-3.0 + 商业授权（闭源/商用需向作者申请授权），见 LICENSE 与 LICENSE-COMMERCIAL.md
#
"""字幕浮窗：5 款样式 × 4 种出现动画，锁定点击穿透，8 秒淡出，最近 5 条回看。

样式（双卡状态面板，视觉自研）：
  tactical 战术双行 / cream 奶油软糖 / walkie 对讲机 / card 潮流字卡 / radar 雷达
动画：fade 淡入 / typewriter 打字机 / line 逐行 / pop 弹出
"""
from __future__ import annotations

import ctypes
import time

from PySide6.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve, QPoint, Signal
from PySide6.QtGui import QFont, QColor
from PySide6.QtWidgets import (QWidget, QLabel, QVBoxLayout, QHBoxLayout,
                               QGraphicsOpacityEffect)

STYLES = ["tactical", "cream", "walkie", "card", "radar"]
STYLE_NAMES = {"tactical": "战术双行", "cream": "奶油软糖", "walkie": "软糖对讲机",
               "card": "潮流字卡", "radar": "雷达扫描"}
ANIMS = ["fade", "typewriter", "line", "pop"]
ANIM_NAMES = {"fade": "淡入", "typewriter": "打字机", "line": "逐行", "pop": "弹出"}

# 每款样式: (容器QSS, 原文样式, 译文样式, 角标)
_STYLE_DEF = {
    "tactical": (
        "background:rgba(13,17,23,208); border:1px solid #30363d; border-radius:12px;",
        "color:#9aa4b2; font-size:12px; background:transparent;",
        "color:#ffffff; font-size:{fs}px; font-weight:700; background:transparent;",
        "color:#3fb950; font-size:11px; background:transparent;",
    ),
    "cream": (
        "background:rgba(255,248,235,235); border:1px solid #f0dcc0; border-radius:16px;",
        "color:#8a7a66; font-size:12px; background:transparent;",
        "color:#4a3b2a; font-size:{fs}px; font-weight:700; background:transparent;",
        "color:#e88ca0; font-size:11px; background:transparent;",
    ),
    "walkie": (
        "background:rgba(18,26,22,215); border:1px solid #2f5e46; border-radius:8px;",
        "color:#7fae95; font-size:12px; background:transparent;",
        "color:#d8ffe9; font-size:{fs}px; font-weight:600; background:transparent;",
        "color:#ff5555; font-size:11px; background:transparent;",
    ),
    "card": (
        "background:qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 rgba(88,45,160,225), stop:1 rgba(28,90,190,225));"
        " border:none; border-radius:14px;",
        "color:rgba(255,255,255,190); font-size:12px; background:transparent;",
        "color:#ffffff; font-size:{fs}px; font-weight:800; background:transparent;",
        "color:rgba(255,255,255,220); font-size:11px; background:transparent;",
    ),
    "radar": (
        "background:rgba(6,20,14,200); border:1px solid #1f7a4d; border-radius:6px;",
        "color:#3fae78; font-size:11px; background:transparent;",
        "color:#c8ffdf; font-size:{fs}px; font-weight:500; background:transparent;",
        "color:#1f7a4d; font-size:10px; background:transparent;",
    ),
}


class SubtitleOverlay(QWidget):
    """游戏内字幕浮窗。锁定后鼠标穿透；未锁定可拖动。"""

    locked_changed = Signal(bool)

    def __init__(self, cfg):
        super().__init__()
        self.cfg = cfg
        self.history: list[dict] = []       # 最近 5 条 {orig, trans, ts}
        self._drag = None
        self._fade_timer = QTimer(self)
        self._fade_timer.setSingleShot(True)
        self._fade_timer.timeout.connect(self._fade_out)
        self._type_timer = QTimer(self)
        self._typing = ""
        self._type_pos = 0

        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)

        self.box = QWidget(self)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self.box)
        self.v = QVBoxLayout(self.box)
        self.v.setContentsMargins(16, 10, 16, 12)
        self.v.setSpacing(2)
        self.badge = QLabel("已锁定")
        self.orig = QLabel("")
        self.orig.setWordWrap(True)
        self.trans = QLabel("")
        self.trans.setWordWrap(True)
        self.v.addWidget(self.badge, 0, Qt.AlignLeft)
        self.v.addWidget(self.orig)
        self.v.addWidget(self.trans)
        self._opacity = QGraphicsOpacityEffect(self.box)
        self.box.setGraphicsEffect(self._opacity)
        self.apply_config()
        self._clear_timer = QTimer(self)
        self._clear_timer.setSingleShot(True)
        self._clear_timer.timeout.connect(lambda: self._opacity.setOpacity(0.0))

    # ---------- 配置 ----------
    def apply_config(self) -> None:
        c = self.cfg
        style = c.overlay_style if c.overlay_style in _STYLE_DEF else "tactical"
        box_qss, o_qss, t_qss, b_qss = _STYLE_DEF[style]
        self.box.setStyleSheet(box_qss)
        self.orig.setStyleSheet(o_qss)
        self.trans.setStyleSheet(t_qss.format(fs=c.overlay_font_size))
        self.badge.setStyleSheet(b_qss)
        self.badge.setVisible(not c.overlay_locked or True)  # 角标常显，锁定态换文案
        self.badge.setText("已锁定" if c.overlay_locked else "未锁定(可拖动)")
        self.setFixedWidth(c.overlay_width)
        self.setWindowOpacity(c.overlay_opacity)
        self.adjustSize()
        if c.overlay_x >= 0:
            self.move(c.overlay_x, c.overlay_y)
        else:
            scr = self.screen().availableGeometry()
            self.move((scr.width() - self.width()) // 2, scr.height() - self.height() - 160)
        self.set_locked(c.overlay_locked)

    # ---------- 锁定 / 穿透 ----------
    def set_locked(self, locked: bool) -> None:
        self.cfg.overlay_locked = locked
        hwnd = int(self.winId())
        GWL_EXSTYLE = -20
        cur = ctypes.windll.user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
        if locked:
            ctypes.windll.user32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE,
                                                   cur | 0x80000 | 0x20)  # LAYERED|TRANSPARENT
        else:
            ctypes.windll.user32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, cur & ~0x20)
        self.badge.setText("已锁定" if locked else "未锁定(可拖动)")
        self.locked_changed.emit(locked)

    # ---------- 显示一条字幕 ----------
    def show_subtitle(self, original: str, translated: str, speaker: str = "队友") -> None:
        self.history.append({"orig": original, "trans": translated, "ts": time.time()})
        if len(self.history) > 5:
            self.history.pop(0)
        c = self.cfg
        self.orig.setVisible(c.show_original)
        self.orig.setText(f"{speaker}·{original}" if c.show_speaker else original)
        self.trans.setText(translated)
        self._opacity.setOpacity(1.0)
        self.adjustSize()
        self._run_anim()
        self._fade_timer.start(int(c.fade_seconds * 1000))

    def review_history(self) -> None:
        """热键回看最近 5 条。"""
        if not self.history:
            return
        lines_t = []
        for h in self.history[-5:]:
            lines_t.append(h["trans"])
        self.show_subtitle(" | ".join(h["orig"] for h in self.history[-5:]),
                           " / ".join(lines_t), speaker="回看")

    # ---------- 动画 ----------
    def _run_anim(self) -> None:
        a = self.cfg.overlay_anim
        if a == "fade":
            self._opacity.setOpacity(0.0)
            anim = QPropertyAnimation(self._opacity, b"opacity", self)
            anim.setDuration(220)
            anim.setStartValue(0.0); anim.setEndValue(1.0)
            anim.setEasingCurve(QEasingCurve.OutCubic)
            anim.start(QPropertyAnimation.DeleteWhenStopped)
        elif a == "pop":
            self._opacity.setOpacity(1.0)
            end = self.pos()
            start = QPoint(end.x(), end.y() + 14)
            self.move(start)
            anim = QPropertyAnimation(self, b"pos", self)
            anim.setDuration(180)
            anim.setStartValue(start); anim.setEndValue(end)
            anim.setEasingCurve(QEasingCurve.OutBack)
            anim.start(QPropertyAnimation.DeleteWhenStopped)
        elif a == "line":
            self._opacity.setOpacity(0.0)
            anim = QPropertyAnimation(self._opacity, b"opacity", self)
            anim.setDuration(320)
            anim.setStartValue(0.0); anim.setEndValue(1.0)
            anim.start(QPropertyAnimation.DeleteWhenStopped)
            end = self.pos()
            self.move(QPoint(end.x(), end.y() - 8))
            anim2 = QPropertyAnimation(self, b"pos", self)
            anim2.setDuration(320)
            anim2.setStartValue(QPoint(end.x(), end.y() - 8)); anim2.setEndValue(end)
            anim2.start(QPropertyAnimation.DeleteWhenStopped)
        elif a == "typewriter":
            self._opacity.setOpacity(1.0)
            self._typing = self.trans.text()
            self._type_pos = 0
            self.trans.setText("")
            self._type_timer.stop()
            self._type_timer.timeout.connect(self._tick_type)
            self._type_timer.start(28)

    def _tick_type(self) -> None:
        self._type_pos += 1
        self.trans.setText(self._typing[:self._type_pos])
        if self._type_pos >= len(self._typing):
            self._type_timer.stop()

    def _fade_out(self) -> None:
        anim = QPropertyAnimation(self._opacity, b"opacity", self)
        anim.setDuration(600)
        anim.setStartValue(self._opacity.opacity()); anim.setEndValue(0.0)
        anim.start(QPropertyAnimation.DeleteWhenStopped)

    # ---------- 拖动（未锁定时） ----------
    def mousePressEvent(self, e) -> None:
        if not self.cfg.overlay_locked:
            self._drag = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e) -> None:
        if self._drag is not None and not self.cfg.overlay_locked:
            self.move(e.globalPosition().toPoint() - self._drag)

    def mouseReleaseEvent(self, e) -> None:
        if self._drag is not None:
            self.cfg.overlay_x, self.cfg.overlay_y = self.x(), self.y()
            self._drag = None

    def mouseDoubleClickEvent(self, e) -> None:
        self.set_locked(not self.cfg.overlay_locked)
