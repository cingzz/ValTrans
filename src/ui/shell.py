# -*- coding: utf-8 -*-
# 作者: cing  ·  https://github.com/cingzz
# 许可: GPL-3.0 + 商业授权（闭源/商用需向作者申请授权），见 LICENSE 与 LICENSE-COMMERCIAL.md
#
"""主窗口外壳：无边框自绘标题栏 + 左侧导航 + 页面栈。

自适应：侧栏固定宽度保证导航稳定，内容区随窗口伸缩（Expanding），
页面内部禁用横向滚动条；窗口默认 1080×700，可自由缩放（最小 880×580）。
性能：导航/标题按钮样式全部走 theme.QSS 类选择器（objectName），
不再逐控件 setStyleSheet（那是滚动卡顿与按钮迟滞的元凶）。
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
                               QLabel, QPushButton, QStackedWidget)

from . import theme

NAV = [
    ("home", "主页"),
    ("live", "实时翻译"),
    ("quota", "我的额度"),
    ("styles", "字幕样式"),
    ("settings", "设置"),
    ("help", "帮助"),
    ("about", "关于"),
]


class TitleBar(QWidget):
    def __init__(self, parent):
        super().__init__(parent)
        self.setFixedHeight(42)
        self._drag = None
        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 0, 6, 0)
        lay.setSpacing(10)
        # 品牌标（红方块 + Bahnschrift 字标）
        mark = QLabel()
        mark.setFixedSize(6, 18)
        mark.setStyleSheet(f"background:{theme.ACCENT};")
        lay.addWidget(mark)
        self.title = QLabel("VALTRANS")
        self.title.setObjectName("Brand")
        lay.addWidget(self.title)
        sub = QLabel("无畏契约 实时语音翻译")
        sub.setObjectName("Muted")
        lay.addWidget(sub)
        lay.addStretch(1)
        for text, fn in [("—", self._min), ("□", self._max), ("✕", self._close)]:
            b = QPushButton(text)
            b.setObjectName("Ghost" if text != "✕" else "Danger")
            b.setFixedSize(38, 28)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(fn)
            lay.addWidget(b)

    def _min(self):
        self.window().showMinimized()

    def _max(self):
        w = self.window()
        w.showNormal() if w.isMaximized() else w.showMaximized()

    def _close(self):
        self.window().hide()  # 关闭=隐藏到托盘

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag = e.globalPosition().toPoint() - self.window().frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        if self._drag is not None and e.buttons() & Qt.LeftButton:
            self.window().move(e.globalPosition().toPoint() - self._drag)

    def mouseReleaseEvent(self, e):
        self._drag = None

    def mouseDoubleClickEvent(self, e):
        self._max()


class NavButton(QPushButton):
    """导航项：样式全部来自 theme.QSS 的 QPushButton#Nav（含选中态红标记条）。"""

    def __init__(self, key, text):
        super().__init__(text)
        self.key = key
        self.setObjectName("Nav")
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)


class MainWindow(QMainWindow):
    page_changed = Signal(str)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("ValTrans")
        self.resize(1080, 700)
        self.setMinimumSize(880, 580)
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
        self.setStyleSheet(theme.QSS)

        root = QWidget(objectName="Root")
        self.setCentralWidget(root)
        outer = QHBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ---- 左侧栏（固定宽：导航稳定） ----
        side = QWidget()
        side.setObjectName("Side")
        side.setFixedWidth(188)
        sl = QVBoxLayout(side)
        sl.setContentsMargins(10, 52, 10, 12)
        sl.setSpacing(2)
        self.brand = QLabel("VALTRANS")
        self.brand.setObjectName("Brand")
        self.brand.setStyleSheet(f"color:{theme.ACCENT}; padding:0 8px 10px;")
        sl.addWidget(self.brand)
        self.nav_buttons: dict[str, NavButton] = {}
        for key, text in NAV:
            b = NavButton(key, text)
            b.clicked.connect(lambda _=False, k=key: self.goto(k))
            self.nav_buttons[key] = b
            sl.addWidget(b)
        sl.addStretch(1)
        # 底部状态
        self.side_status = QLabel("● 未启动")
        self.side_status.setStyleSheet(f"color:{theme.MUTED}; font-size:12px; padding:8px;")
        self._status_color = theme.MUTED
        sl.addWidget(self.side_status)
        outer.addWidget(side)

        # ---- 右侧（标题栏 + 页面栈，随窗口伸缩） ----
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(0)
        self.titlebar = TitleBar(self)
        rl.addWidget(self.titlebar)
        self.stack = QStackedWidget()
        self.stack.setStyleSheet("background:%s;" % theme.BG0)
        rl.addWidget(self.stack, 1)
        outer.addWidget(right, 1)

        self.pages: dict[str, QWidget] = {}

    def register(self, key: str, page: QWidget) -> None:
        self.pages[key] = page
        self.stack.addWidget(page)

    def goto(self, key: str) -> None:
        for k, b in self.nav_buttons.items():
            b.setChecked(k == key)
        if key in self.pages:
            self.stack.setCurrentWidget(self.pages[key])
            self.page_changed.emit(key)

    def set_status_text(self, text: str, color: str) -> None:
        self.side_status.setText(f"● {text}")
        if color != self._status_color:  # 颜色没变就不重铺样式（高频状态更新防抖）
            self._status_color = color
            self.side_status.setStyleSheet(f"color:{color}; font-size:12px; padding:8px;")
