# -*- coding: utf-8 -*-
"""原生字幕浮窗：WinForms 分层窗 + GDI+ 绘制，跑在 ValTrans 主进程内。

为什么存在（2026-10-04 用户决策）
--------------------------------
WebView2 浮窗自带一组 msedgewebview2.exe 沙盒子进程（渲染/GPU/网络），
任务管理器里表现为「第二个进程」，用户明确要求合并。WebView2 的沙盒
进程无法合并，所以浮窗改用**进程内原生渲染**：
    · 主窗（设置界面）继续用 WebView2（复杂交互需要）
    · 浮窗 = 纯文字面板，GDI+ 足够，不再产生任何浮窗子进程

与 api.py 的对接（鸭子类型兼容 pywebview Window 接口）
------------------------------------------------
api.py 只对浮窗做这些动作：
    show / hide / resize / move / x / y / native.Handle / evaluate_js
evaluate_js 推送的调用共四种（生成处见 api.py，**必须全覆盖**，缺一种
那个功能就在原生浮窗上静默消失）：
    window.onSubtitle(orig, trans, speaker, mineFlag)  字幕（mineFlag 决定上/下卡）
    window.onStatus(kind, text)                        管线状态（stopped 清空双卡）
    window.onConfig(cfg)                               配置推送
    window.onPtt(kind, text)                           PTT 反馈（橙色「正在听」）
另有 `!!(window.onSubtitle && window.onConfig)` 就绪探测 —— 原生浮窗没有
页面可探测，api._ensure_overlay 靠本类的 IS_NATIVE 标记跳过探测。

视觉规格 = webui/src/overlay.jsx 的逐条翻译（CSS 颜色已对底色 104,108,114
做透明度合成，得到等效不透明色）：
    上卡=队友当前句（译文大字 + 原文小字），下卡=我的话（中文大字 + 外文小字）
    未固定时锁定提示高亮 #9BE7FF；PTT 按住时下卡橙色高亮 + 9 格电平条
    固定尺寸不随内容伸缩；空态显示占位；整窗半透明由 host 按 OVERLAY_TITLE
    设 LWA_ALPHA（本类只负责把标题设对 —— 标题错了后面整条链路全瞎）。

线程模型
--------
独立 STA 线程 + 无参 Application.Run()（消息循环 servicing 本线程所有窗口；
不能用 Application.Run(form)——那会立即 Show 窗口）。api 侧来自任意线程的
调用经 BeginInvoke 编组到 UI 线程；电平条用 WinForms Timer 在 UI 线程自轮询。
"""
from __future__ import annotations

import ctypes
import json
import logging
import re
import threading
# ★ v0.2.22：补上漏掉的 time。
#   它被用在两处，且**第一处就在 _paint 的绘制路径上**：
#     L384  `if _nt and time.time() < float(st.get("notice_until") or 0):`
#     L807  `self._state["notice_until"] = time.time() + ...`
#   缺失后果（pkg_smoke 实测，不是推算）：
#     NameError: name 'time' is not defined -> 浮窗绘制失败（本帧跳过）
#   因为绘制体被 try 包住（pythonnet 铁律：未处理的绘制异常
#   会弹 ThreadExceptionDialog 把 STA 线程挂在模态框上），所以**每帧都被
#   静默跳过** —— 表现为浮窗一片空白，而不是报错。
#   这种 bug 逃过了 py_compile / verify_src / audit_dead_code：
#   NameError 是**运行时**才发生的，只有真把窗画出来才会撞上
#   （import 成功 ≠ 函数能跑）。
import time

import clr
clr.AddReference("System.Windows.Forms")
clr.AddReference("System.Drawing")

import System.Drawing.Text                      # TextRenderingHint 的命名空间
from System.Drawing import (Color, Font, FontStyle, GraphicsUnit, Pen,
                            SolidBrush, RectangleF, StringAlignment,
                            StringFormat, PointF, Size, SizeF, Point,
                            Rectangle)
from System.Drawing.Drawing2D import GraphicsPath, SmoothingMode
from System.Windows.Forms import (Application, Form, FormBorderStyle,
                                  FormStartPosition, MethodInvoker, MouseButtons,
                                  Timer)
from System.Threading import ApartmentState, Thread, ThreadStart

log = logging.getLogger("valtrans.overlay")

# ---- 调色板（overlay.jsx CSS 折算到面板底色 rgba(104,108,114) 上的等效色）----
PANEL_BG = Color.FromArgb(104, 108, 114)
C_HEAD = Color.FromArgb(168, 171, 175)          # head 文字 white 62%
C_LOCK = Color.FromArgb(198, 200, 204)          # lockhint white 62%
C_LOCK_LIVE = Color.FromArgb(155, 231, 255)     # 未固定时的 #9BE7FF
C_T1 = Color.FromArgb(251, 252, 253)            # 译文主字 #FBFCFD
C_T2 = Color.FromArgb(214, 215, 218)            # 原文小字 white 75%
C_T2_FG = Color.FromArgb(155, 231, 255)         # 我的外文 #9BE7FF
C_WAIT = Color.FromArgb(205, 207, 210)          # 空态 white 66%
C_WM = Color.FromArgb(196, 202, 209)            # 水印 #C4CAD1


def _show_second_line(orig, trans, want=True) -> bool:
    """第二行（原文/外文小字）到底该不该画。

    ★ v0.2.21（2026-10-06 用户截图）
    --------------------------------
    用户贴的截图里浮窗**把同一句话显示了两遍**（粗体译文 + 下面小字原文，
    两行一模一样）。根因：`show_original` 一开就无条件画 `mate["orig"]`，
    而中文输入时 `translate_gate` **照抄**（语种闸门的规则：
    「别人说中文，你完全可以不用翻译照抄」）—— 于是 `orig == trans`，
    同一句话被画了两次。

    两种情况不该画第二行：
      ① `orig == trans` —— 画了就是同一句话重复
      ② 原文已是中文 —— 译文就是原文的复制，第二行纯属噪声

    ② 复用 `translate_gate.looks_chinese`，**不另写一份判定**：
    它的契约正是「输入是否已经是普通话（= 该照抄、不该进翻译链）」，
    而且已经把粤语排除在外（粤语全是汉字但要翻成普通话）。
    同一个判断只能有一份实现，重复写必然漂移。

    注意：不要用 `cross_check.is_cjk_text` —— 它判的是
    「要不要走 CJK 术语索引」（假名/谚文/粤语），**汉字不算**，
    实测「你们好吵啊」对它返回 False。名字容易骗人，必须实测。
    """
    if not want:
        return False
    o = (orig or "").strip()
    t = (trans or "").strip()
    if not o or not t:
        return False
    if o == t:
        return False
    try:
        from ..services.translate_gate import looks_chinese
        if looks_chinese(o):
            return False
    except Exception:
        # 拿不到判定就退回「画」：宁可多一行，不可丢信息
        return True
    return True
C_DIV = Color.FromArgb(156, 159, 163)           # 分隔线 white 22%
CHIP_B_BG = Color.FromArgb(120, 135, 145)       # chip.b 底 rgba(155,231,255,.22)
CHIP_B_TX = Color.FromArgb(155, 231, 255)
CHIP_G_BG = Color.FromArgb(150, 219, 241)       # chip.g 底 rgba(155,231,255,.9)
CHIP_G_TX = Color.FromArgb(11, 39, 64)
PTT_BG = Color.FromArgb(134, 114, 91)           # ptt-live 底 rgba(255,138,0,.20)
PTT_BD = Color.FromArgb(187, 142, 84)           # ptt-live 描边 rgba(255,170,60,.55)
PTT_TX = Color.FromArgb(255, 196, 107)          # pttstate #FFC46B
C_ERR = Color.FromArgb(255, 155, 163)           # 报错 #FF9BA3（.status.err）
C_DROP = Color.FromArgb(255, 178, 106)          # 丢段 #FFB26A（v0.2.19 P2）
MIC_ON = Color.FromArgb(255, 165, 61)           # micbar on #FFA53D
MIC_OFF = Color.FromArgb(173, 140, 96)          # micbar off rgba(255,196,107,.32)

FONT = "Microsoft YaHei UI"
_HWND_TOPMOST = -1
_SW_SHOWNOACTIVATE = 4
_GWL_EXSTYLE = -20
_WS_EX_NOACTIVATE = 0x08000000                  # Show() 不抢前台（游戏内必须）
_WS_EX_TOOLWINDOW = 0x00000080
_SWP_FLAGS = 0x0001 | 0x0002 | 0x0010 | 0x0020 | 0x0040
#        NOMOVE | NOSIZE | NOZORDER | FRAMECHANGED | NOACTIVATE

_HOTKEY_LABELS = {"ctrl": "Ctrl", "alt": "Alt", "shift": "Shift", "cmd": "Win"}


def _pretty_hotkey(raw: str) -> str:
    """overlay.jsx prettyHotkey 的等价实现（显示用，解析以 pynput 为准）。"""
    if not raw:
        return "未设置"
    parts = []
    for s in raw.split("+"):
        t = s.strip().strip("<>").lower()
        parts.append(_HOTKEY_LABELS.get(t) or (t.upper() if len(t) == 1 else t))
    return " + ".join(parts)


class _PanelForm(Form):
    """双卡面板：上卡=队友当前句，下卡=我的话；固定尺寸；空态占位。"""

    def __init__(self, owner):
        # ★ pythonnet 铁律：子类定义了 __init__ 就必须显式调 CLR 基类构造，
        #   否则 Control 内部状态（Properties 等）没初始化，**任何**属性读写
        #   都在 NRE 上炸（上两轮的 FormBorderStyle/BackColor NRE 全是它）。
        super().__init__()
        self._owner = owner
        try:
            self.Text = owner.title       # 句柄未建时先存着，_run 建完句柄再补
        except Exception:
            pass
        self.FormBorderStyle = getattr(FormBorderStyle, "None")
        self.StartPosition = FormStartPosition.Manual
        self.ShowInTaskbar = False
        self.TopMost = True
        try:
            self.DoubleBuffered = True
        except Exception:
            pass
        self.BackColor = PANEL_BG
        self.ClientSize = Size(owner.width, owner.height)
        self.Location = Point(owner.pos_x, owner.pos_y)
        self._fonts: dict = {}
        self._drag_pt = None
        self.MouseDown += self._on_down
        self.MouseMove += self._on_move
        self.MouseUp += self._on_up
        # ★ 用 Paint **事件**而不是重写 OnPaint：pythonnet 实测重写 OnPaint
        #   不会被绑定（探针计数=0，窗口一片底色），事件订阅则每次都触发。
        self.Paint += self._on_paint_evt

    # ---- 拖动（仅 overlay_pinned=False 时；固定态由 Win32 穿透根本收不到鼠标）----
    def _on_down(self, s, e):
        if e.Button == MouseButtons.Left and not self._owner.cfg.get(
                "overlay_pinned", True):
            self._drag_pt = e.Location

    def _on_move(self, s, e):
        if self._drag_pt is not None:
            self.Location = Point(
                self.Location.X + (e.Location.X - self._drag_pt.X),
                self.Location.Y + (e.Location.Y - self._drag_pt.Y))

    def _on_up(self, s, e):
        if self._drag_pt is not None:
            self._drag_pt = None
            self._owner.on_drag_end(self.Location.X, self.Location.Y)

    # ---- 绘制 ----
    def _on_paint_evt(self, sender, e):
        # ★ 绘制异常绝不能往外抛：WinForms 收到未处理绘制异常会弹
        #   ThreadExceptionDialog，把 STA 线程挂在模态框上（实测探针被挂死）。
        #   坏一帧只是画面旧了，弹窗是软件「死了」。
        try:
            self._paint(e.Graphics)
        except Exception:
            log.exception("浮窗绘制失败（本帧跳过）")

    def _paint(self, g):
        st = self._owner.state
        cfg = self._owner.cfg
        w = self.ClientSize.Width
        h = self.ClientSize.Height
        g.SmoothingMode = SmoothingMode.AntiAlias
        g.TextRenderingHint = System.Drawing.Text.TextRenderingHint.AntiAlias

        # flex 布局的等效换算：panel padding 10/14/6，gap 8，divider 1px，wm 14px
        pad, gap, div_h, wm_h = 10, 8, 1, 14
        inner = h - pad - 6
        card_h = (inner - div_h - 3 * gap - wm_h) / 2.0
        c1_y = pad
        div_y = c1_y + card_h + gap
        c2_y = div_y + div_h + gap
        wm_y = c2_y + card_h + gap

        listening = st.get("ptt_kind") == "listening"
        if listening:
            self._round(g, 14, c2_y, w - 28, card_h, 10, PTT_BG)
            self._round_outline(g, 14, c2_y, w - 28, card_h, 10, PTT_BD)

        # ── 上卡头部：chip「队友」+ 右侧固定提示 ──
        # ★ v0.2.17：窄窗自适应——完整提示太长，窄卡上会折行压住 chip
        self._chip(g, 14, c1_y, "队友", CHIP_B_BG, CHIP_B_TX)
        pinned = cfg.get("overlay_pinned", True)
        if w >= 380:
            move = _pretty_hotkey(cfg.get("hotkey_move", ""))
            hint = (f"已固定 · {move} 解锁拖动" if pinned
                    else f"可拖动 · {move} 固定")
        elif w >= 240:
            hint = "已固定" if pinned else "可拖动"
        else:
            # ★ v0.2.21：原来这里给空串 —— 而用户小窗正好落在这一档，
            #   于是「按了热键什么都看不到」，被判断成「没这个功能」。
            #   现在最窄档也给一个极短的标记（固定/可拖 两字），
            #   放得下就放，放不下由 _text 自己裁剪，不会溢出。
            hint = "已固定" if pinned else "可拖"
        if hint:
            self._text(g, c1_y + 3, hint,
                       C_LOCK if pinned else C_LOCK_LIVE, 11, not pinned,
                       x=w - 14, maxw=min(w - 100, 240), right=True)

        # ── 上卡内容（.txt 垂直居中）──
        # ★ v0.2.17 字号自适应：用户喜欢小窗——文字装不下就逐级缩小字号，
        #   不再折行挤压、不再与原文/分隔线叠字（裁剪兜底）。
        mate = st.get("mate")
        fs = int(cfg.get("overlay_font_size", 18) or 18)
        txt_top = c1_y + 20 + 6
        txt_h = card_h - 26
        g.SetClip(Rectangle(14, int(txt_top), w - 28, int(txt_h)))
        if mate:
            show_orig = _show_second_line(
                mate.get("orig"), mate.get("trans"),
                cfg.get("show_original", True))
            t2_h = 16 if show_orig else 0
            avail = max(22.0, txt_h - t2_h - 4)
            fs_fit = self._fit_size(g, mate["trans"], w - 28, avail,
                                    fs, True, minimum=12)
            th = self._measure(g, mate["trans"], fs_fit, True, w - 28)
            y = txt_top + max(0, (txt_h - (th + t2_h)) / 2.0)
            y = self._text(g, y, mate["trans"], C_T1, fs_fit, True,
                           x=14, maxw=w - 28, box_h=th)
            if show_orig:
                osz = min(12, max(10, fs_fit - 6))
                self._text(g, y + 2, mate["orig"], C_T2, osz, False,
                           x=14, maxw=w - 28)
        else:
            wait = ("识别+翻译中…" if st.get("status_kind") == "recognizing"
                    else "未识别到语音 · 等待队友说话")
            wsz = self._fit_size(g, wait, w - 28, txt_h,
                                 max(13, fs - 4), False, minimum=11)
            self._text(g, txt_top + max(0, (txt_h - wsz * 1.35) / 2.0), wait,
                       C_WAIT, wsz, False, x=14, maxw=w - 28)
        g.ResetClip()

        # ── 分隔线 ──
        g.DrawLine(Pen(C_DIV), 14, int(div_y), w - 14, int(div_y))

        # ── 下卡头部：chip「我」+ 右侧电平条 + PTT 状态 ──
        self._chip(g, 14, c2_y, "我", CHIP_G_BG, CHIP_G_TX)
        head2_right = w - 14
        ptt_text = st.get("ptt_text") or ""
        if listening:
            # 9 格电平条：高 11px，亮格 = mic > i*12（与 overlay.jsx 相同）
            lvl = int(st.get("mic") or 0)
            bar_right = head2_right
            if ptt_text:
                tw = int(len(ptt_text) * 11.5)
                self._text(g, c2_y + 4, ptt_text, PTT_TX, 11.5, True,
                           x=head2_right, maxw=tw + 12, right=True)
                bar_right = head2_right - tw - 10
            for i in range(9):
                bx = bar_right - (9 - i) * 4
                bh = 11 if lvl > i * 12 else 3
                by = c2_y + 20 - bh
                fill = SolidBrush(MIC_ON if lvl > i * 12 else MIC_OFF)
                try:
                    g.FillRectangle(fill, bx, by, 2, bh)
                finally:
                    fill.Dispose()

        # ── 下卡内容 ──
        # PTT 活动期正文必须跟着状态走（真机 实测反馈：
        # 「高亮了但字还是『未识别到语音』，应该显示正在识别」）——
        # 按住=正在听、松开=识别+翻译中、出错=原因；只有空闲时才显示
        # 结果/占位。活动期旧结果先让位，出新区结果再回来。
        # ★ v0.2.17：与上卡同款字号自适应 + 裁剪。
        mine = st.get("mine")
        txt_top2 = c2_y + 20 + 6
        txt_h2 = card_h - 26
        body_state = None
        if listening:
            body_state = ("正在听…（松开发送）", PTT_TX, True)
        elif st.get("ptt_kind") == "working":
            body_state = ("识别+翻译中…", C_WAIT, False)
        elif st.get("ptt_kind") == "warn":
            body_state = (st.get("ptt_text") or "再说一次", PTT_TX, False)
        elif st.get("ptt_kind") == "error":
            body_state = (st.get("ptt_text") or "识别出错", C_ERR, False)
        g.SetClip(Rectangle(14, int(txt_top2), w - 28, int(txt_h2)))
        if body_state is not None:
            text, color, bold = body_state
            ssz = self._fit_size(g, text, w - 28, txt_h2,
                                 max(14, fs - 4), bold, minimum=11)
            self._text(g, txt_top2 + max(0, (txt_h2 - ssz * 1.35) / 2.0),
                       text, color, ssz, bold, x=14, maxw=w - 28)
        elif mine:
            fs2_fit = self._fit_size(g, mine["orig"], w - 28,
                                     max(22.0, txt_h2 - 18 - 4),
                                     max(12, fs - 2), True, minimum=12)
            th2 = self._measure(g, mine["orig"], fs2_fit, True, w - 28)
            y = txt_top2 + max(0, (txt_h2 - (th2 + 16)) / 2.0)
            y = self._text(g, y, mine["orig"], C_T1, fs2_fit, True,
                           x=14, maxw=w - 28, box_h=th2)
            tsz = self._fit_size(g, mine["trans"], w - 28,
                                 max(14.0, txt_h2 - th2 - 6), 12, False,
                                 minimum=10)
            if _show_second_line(mine.get("orig"), mine.get("trans"), True):
                self._text(g, y + 2, mine["trans"], C_T2_FG, tsz, False,
                           x=14, maxw=w - 28)
        else:
            wait2 = "未识别到语音 · 按住 PTT 说中文"
            wsz2 = self._fit_size(g, wait2, w - 28, txt_h2,
                                  max(13, fs - 4), False, minimum=11)
            self._text(g, txt_top2 + max(0, (txt_h2 - wsz2 * 1.35) / 2.0),
                       wait2, C_WAIT, wsz2, False, x=14, maxw=w - 28)
        g.ResetClip()

        # ── 丢段 / 失败计数（v0.2.19 P2）──
        # 丢段是**静默**的：ASR/MT 队列积压时丢最旧的一段，字幕断一截，
        # 而用户不知道是队友没说话还是软件把那句丢了。浮窗是游戏里唯一
        # 看得到的东西，所以必须露出来。
        # 只在 >0 时画 —— 一切正常时面板要和以前逐像素一致，
        # 平白多一行字反而会被当成「坏了」（VoxGo 的教训）。
        _drop = int(st.get("dropped", 0) or 0)
        _fail = int(st.get("failed", 0) or 0)
        if _drop or _fail:
            bits = []
            if _drop:
                bits.append("丢段 %d" % _drop)
            if _fail:
                bits.append("失败 %d" % _fail)
            _tip = " · ".join(bits)
            self._text(g, wm_y, _tip, C_DROP, 10.5, False,
                       x=14, maxw=w - 110)

        # ── v0.2.21：临时提示（热键反馈）────────────────────────────
        # 用户反馈「没有固定弹窗的快捷键了」——热键一直有注册，
        # 但反馈只发到**主窗口**，而他在打游戏、主窗口收着。
        # 浮窗是游戏里唯一可见的东西，所以提示必须也画在这里。
        # 超过 notice_until 就自动不画（不留陈旧信息）。
        _nt = st.get("notice") or ""
        if _nt and time.time() < float(st.get("notice_until") or 0):
            self._text(g, wm_y, _nt, C_T2_FG, 10.5, False,
                       x=14, maxw=w - 110)
        elif _nt:
            with self._state_lock:
                self._state["notice"] = ""
            self._state["notice_until"] = 0.0

        # ── 水印 ──
        self._text(g, wm_y, "· ValTrans ·", C_WM, 10.5, False,
                   x=w - 14, maxw=90, right=True)

    # ---- 绘图小件 ----
    def _font(self, size, bold):
        key = (round(float(size), 1), bool(bold))
        f = self._fonts.get(key)
        if f is None:
            f = Font(FONT, key[0], FontStyle.Bold if bold else FontStyle.Regular,
                     GraphicsUnit.Pixel)
            self._fonts[key] = f
        return f

    def _chip(self, g, x, y, text, bg, tx):
        wch = 12 * len(text) + 18
        self._round(g, x, y, wch, 20, 10, bg)
        g.DrawString(text, self._font(12, True), SolidBrush(tx),
                     PointF(x + 9, y + 2))

    def _round(self, g, x, y, w, h, r, color):
        path = self._rpath(x, y, w, h, r)
        try:
            g.FillPath(SolidBrush(color), path)
        finally:
            path.Dispose()

    def _round_outline(self, g, x, y, w, h, r, color):
        path = self._rpath(x, y, w, h, r)
        try:
            g.DrawPath(Pen(color), path)
        finally:
            path.Dispose()

    @staticmethod
    def _rpath(x, y, w, h, r):
        path = GraphicsPath()
        d = r * 2
        path.AddArc(x, y, d, d, 180, 90)
        path.AddArc(x + w - d, y, d, d, 270, 90)
        path.AddArc(x + w - d, y + h - d, d, d, 0, 90)
        path.AddArc(x, y + h - d, d, d, 90, 90)
        path.CloseFigure()
        return path

    def _text(self, g, y, text, color, size, bold, x=14, maxw=300, right=False,
              box_h=None):
        f = self._font(size, bold)
        sf = StringFormat()
        try:
            h = float(box_h) if box_h else size * 2.4
            if right:
                sf.Alignment = StringAlignment.Far
                rect = RectangleF(x - maxw, y, maxw, h)
            else:
                rect = RectangleF(x, y, maxw, h)
            g.DrawString(text, f, SolidBrush(color), rect, sf)
        finally:
            sf.Dispose()
        return int(y + (float(box_h) if box_h else size * 1.35))

    def _measure(self, g, text, size, bold, maxw):
        """文本按 maxw 折行后的实际高度（MeasureString 失败退化为估算）。"""
        try:
            f = self._font(size, bold)
            return g.MeasureString(text, f, SizeF(maxw, 10000.0)).Height
        except Exception:
            cjk = sum(1 for ch in text if ord(ch) > 0x2E80)
            avg = size * (1.02 if cjk * 2 > len(text) else 0.58)
            cpl = max(1, int(maxw / max(1.0, avg)))
            lines = max(1, -(-len(text) // cpl))
            return lines * size * 1.4

    def _fit_size(self, g, text, maxw, maxh, start, bold, minimum=12):
        """从 start 逐级缩小字号直到装得下（小窗不挤的关键；尺寸是用户定的，
        文字 adapts to 窗，不是窗 adapts to 文字）。"""
        size = float(start)
        while size > minimum:
            if self._measure(g, text, size, bold, maxw) <= maxh:
                break
            size -= 1.0
        return max(minimum, size)


class NativeOverlay:
    """鸭子类型兼容 pywebview Window 的原生浮窗。

    IS_NATIVE 标记给 api._ensure_overlay：原生浮窗没有页面可探测，
    就绪探测循环对它只会空转 6 秒，必须跳过。
    """

    IS_NATIVE = True

    def __init__(self, api):
        self._api = api
        cfg = api._cfg
        self.title = "vt-overlay-window-v02"
        self.width = int(cfg.overlay_width)
        self.height = int(getattr(cfg, "overlay_height", 380) or 380)
        self.pos_x = int(cfg.overlay_x) if int(cfg.overlay_x) >= 0 else \
            max(0, ctypes.windll.user32.GetSystemMetrics(0) - self.width - 48)
        self.pos_y = int(cfg.overlay_y) if int(cfg.overlay_y) >= 0 else \
            max(0, ctypes.windll.user32.GetSystemMetrics(1) - self.height - 48)
        self._state_lock = threading.Lock()
        self._state = {"status_kind": "listening", "status_text": "等待队友说话…",
                       "mate": None, "mine": None,
                       "ptt_kind": "idle", "ptt_text": "", "mic": 0,
                       # v0.2.19（P2）：丢段/失败计数。
                       # 丢段是静默的 —— 字幕断一截而用户不知道为什么，
                       # 浮窗是游戏里唯一看得到的地方，所以必须露出来。
                       "dropped": 0, "failed": 0,
                       # ★ v0.2.21：临时提示（热键反馈）。
                       # 起因：用户报「没有固定这个弹窗的快捷键了」——
                       # 查下来 `toggle_pin` 一直有 `self.notify(...)`，
                       # 但 notify 只发到**主窗口**，而用户反馈时在打游戏、
                       # 主窗口是收起来的 —— **反馈存在于用户看不到的地方**。
                       # 浮窗是游戏里唯一可见的东西，所以提示必须也走这里。
                       "notice": "", "notice_until": 0.0}
        self._cfg_view = {"overlay_font_size": cfg.overlay_font_size,
                          "show_original": cfg.show_original,
                          "overlay_pinned": getattr(cfg, "overlay_pinned", True),
                          "hotkey_move": getattr(cfg, "hotkey_move", "")}
        self._form = None
        self._ready = threading.Event()
        self._closing = False
        self._thread = None
        t = Thread(ThreadStart(self._run))
        t.SetApartmentState(ApartmentState.STA)
        t.IsBackground = True
        self._thread = t
        t.Start()
        ok = self._ready.wait(timeout=8)
        if not ok or self._form is None:
            log.error("native overlay 线程 8 秒内未就绪（ready=%s form=%s）",
                      ok, self._form is not None)

    # ---------- 属性（_PanelForm 绘制时读取） ----------
    @property
    def state(self):
        with self._state_lock:
            return dict(self._state)

    @property
    def cfg(self):
        with self._state_lock:
            return dict(self._cfg_view)

    # ---------- UI 线程 ----------
    def _run(self):
        try:
            self._form = _PanelForm(self)
            # pythonnet：Handle 是 IntPtr，int() 直转在某些版本抛 TypeError，
            # 必须走 ToInt64()。这一步同时强制创建句柄。
            hwnd = int(self._form.Handle.ToInt64())
            self._form.Text = self.title      # ★ _apply_overlay_style 与隐藏
                                              #   兜底都按这个标题 FindWindowW
            # WS_EX_NOACTIVATE：Form.Show() 不抢前台。浮窗在游戏里弹出，
            # 抢焦点会把玩家切出对局 —— 这是 overlay 建窗时 focus=False 的原生等价物。
            # WS_EX_TOOLWINDOW：不进任务栏/Alt+Tab（host._apply_overlay_style 会再补一次）
            user32 = ctypes.windll.user32
            ex = user32.GetWindowLongPtrW(hwnd, _GWL_EXSTYLE)
            user32.SetWindowLongPtrW(hwnd, _GWL_EXSTYLE,
                                     ex | _WS_EX_NOACTIVATE | _WS_EX_TOOLWINDOW)
            user32.SetWindowPos(hwnd, _HWND_TOPMOST, 0, 0, 0, 0, _SWP_FLAGS)
            self._ready.set()
            # 电平条定时器：仅 PTT 按住时读电平并重绘，平时 tick 空转（零开销）。
            # 引用必须挂在 self 上 —— 局部变量被 GC 后定时器会静默停摆。
            # v0.2.19（P2）：丢段计数轮询。250ms 足够 —— 它只是给人看的
            # 指示器，不需要实时。读失败一律忽略（计数器不是关键路径）。
            self._stat_timer = Timer()
            self._stat_timer.Interval = 250
            self._stat_timer.Tick += self._on_stat_tick
            self._stat_timer.Start()
            self._timer = Timer()
            self._timer.Interval = 110
            self._timer.Tick += self._on_tick
            self._timer.Start()
            # 无参 Run：退出靠 close() 里的 Application.ExitThread()
            Application.Run()
        except Exception:
            log.exception("native overlay 线程异常")
            self._ready.set()

    def _on_stat_tick(self, s, e):
        """把管线的丢段/失败计数拉进浮窗状态（P2 错误可见性）。

        与 _on_tick 分开：电平表只在 PTT 按住时才跑，这个要一直跑。
        但两者都是「只改内存里的小整数 + 变了才重绘」，开销可忽略。
        """
        try:
            api = getattr(self, "_api", None)
            st = getattr(getattr(api, "_pipeline", None), "stats", None) or {}
            d, f = int(st.get("dropped", 0) or 0), int(st.get("fail", 0) or 0)
        except Exception:
            return
        with self._state_lock:
            if self._state.get("dropped") == d and self._state.get("failed") == f:
                return
            self._state["dropped"] = d
            self._state["failed"] = f
        self._repaint()

    def _on_tick(self, s, e):
        with self._state_lock:
            live = self._state.get("ptt_kind") == "listening"
            if not live:
                return
        try:
            lvl = int(self._api.get_ptt_level() or 0)
        except Exception:
            lvl = 0
        with self._state_lock:
            if self._state.get("ptt_kind") != "listening":
                return
            if self._state.get("mic") == lvl:
                return
            self._state["mic"] = lvl
        self._repaint()

    def _ui(self, fn):
        """编组到浮窗 UI 线程。"""
        if self._form is None:
            return
        try:
            if self._form.InvokeRequired:
                self._form.BeginInvoke(MethodInvoker(fn))
            else:
                fn()
        except Exception:
            pass

    # ---------- pywebview 兼容接口 ----------
    @property
    def native(self):
        outer = self
        class _H:
            @property
            def Handle(self):
                f = outer._form
                # 只在句柄已建时才取：Control.Handle 会**当场创建**句柄，
                # 从非 UI 线程触发就是跨线程句柄 —— 返回 0 让上层走兜底
                return int(f.Handle.ToInt64()) if (f is not None and f.IsHandleCreated) else 0
        return _H()

    @property
    def x(self):
        f = self._form
        return f.Location.X if f else self.pos_x

    @property
    def y(self):
        f = self._form
        return f.Location.Y if f else self.pos_y

    def show(self):
        self._ui(lambda: self._form.Show())

    def hide(self):
        self._ui(lambda: self._form.Hide())

    def resize(self, w, h):
        def fn():
            self.width, self.height = int(w), int(h)
            self._form.ClientSize = Size(self.width, self.height)
        self._ui(fn)

    def move(self, x, y):
        def fn():
            self._form.Location = Point(int(x), int(y))
        self._ui(fn)

    def is_visible(self):
        f = self._form
        return bool(f is not None and f.Visible)

    def close(self):
        self._closing = True
        done = threading.Event()

        def fn():
            try:
                self._form.Close()
            except Exception:
                pass
            try:
                Application.ExitThread()   # 无窗 Run() 只能显式退出
            except Exception:
                pass
            done.set()
        self._ui(fn)
        # 必须等消息循环真正退出：否则进程退出会和还活着的消息泵竞态，
        # 解释器偶发挂在 CLR 线程上（实测：测试进程 hang 死两次）
        done.wait(timeout=3)
        try:
            if self._thread is not None and self._thread.IsAlive:
                # ExitThread 返回 ≠ 线程已结束 —— 再等线程真正退出，
                # 解释器关闭时才不会跟它竞态
                self._thread.Join(3000)
        except Exception:
            pass

    # ---------- JS 桥兼容（api._overlay_js 的全部调用经这里进来） ----------
    def evaluate_js(self, code: str):
        if self._closing or not code:
            return None
        m = re.search(r"window\.(onSubtitle|onStatus|onConfig|onPtt)\((.*)\)\s*$",
                      code, re.S)
        if not m:
            return None                    # 就绪探测等非调用表达式 → None
        name, argstr = m.group(1), m.group(2).strip()
        vals = [self._val(a) for a in self._split_args(argstr)]
        if name == "onSubtitle" and len(vals) >= 2:
            card = {"orig": vals[0], "trans": vals[1]}
            with self._state_lock:
                # mineFlag 决定进哪张卡：PTT 的「我的话」进下卡（vals[3]），
                # 队友字幕进上卡 —— 混了会把我说的话当成队友的
                self._state["mine" if (len(vals) > 3 and vals[3]) else "mate"] = card
            self._repaint()
        elif name == "onStatus" and len(vals) >= 1:
            kind = vals[0]
            with self._state_lock:
                if kind == "stopped":
                    self._state["mate"] = None     # overlay.jsx 同款：停止清空双卡
                    self._state["mine"] = None
                self._state["status_kind"] = kind
                self._state["status_text"] = (
                    "等待队友说话…" if kind == "listening"
                    else (vals[1] if len(vals) > 1 and vals[1] else ""))
            self._repaint()
        elif name == "onConfig" and vals and isinstance(vals[0], dict):
            with self._state_lock:
                self._cfg_view.update(vals[0])
            self._repaint()
        elif name == "onPtt" and len(vals) >= 1:
            with self._state_lock:
                self._state["ptt_kind"] = vals[0]
                self._state["ptt_text"] = vals[1] if len(vals) > 1 else ""
                if vals[0] != "listening":
                    self._state["mic"] = 0
            self._repaint()
        return None

    @staticmethod
    def _split_args(s):
        args, depth, cur, q = [], 0, "", None
        for ch in s:
            if q:
                cur += ch
                if ch == q and cur[-2:] != '\\"':
                    q = None
            else:
                if ch in ('"', "'"):
                    q = ch; cur += ch
                elif ch in "{[(":
                    depth += 1; cur += ch
                elif ch in "}])":
                    depth -= 1; cur += ch
                elif ch == "," and depth == 0:
                    args.append(cur.strip()); cur = ""
                else:
                    cur += ch
        if cur.strip():
            args.append(cur.strip())
        return args

    @staticmethod
    def _val(a):
        a = a.strip()
        if not a:
            return ""
        try:
            return json.loads(a)
        except Exception:
            pass
        try:
            import ast
            return ast.literal_eval(a)
        except Exception:
            return a.strip("'\"")

    def _repaint(self):
        self._ui(lambda: self._form.Invalidate())

    # ---------- 回调（UI 线程 → api） ----------
    def on_drag_end(self, x, y):
        try:
            self._api.save_overlay_pos(x, y)
        except Exception:
            pass

    # ---------- 临时提示（v0.2.21）----------
    def show_notice(self, text: str, seconds: float = 2.2):
        """在浮窗上显示一条临时提示（游戏里唯一可见的地方）。

        为什么必须有（真机 实测）
        ----------------------------------
        「没有固定这个弹窗的快捷键了，或者没有这个功能」——
        查下来热键一直有注册（日志：全局热键已启动 … <ctrl>+<shift>+d），
        `toggle_pin` 也一直有 `self.notify(...)`。

        问题在于 **notify 只发到主窗口**（`_emit("notice", …)`）。
        而用户反馈这件事时**正在打游戏**，主窗口收着 ——
        所以「按了像没反应」，于是判断成「没这个功能」。

        叠加第二层：浮窗上原有的固定状态提示会按宽度降级，
        >=380px 才显示「已固定 · Ctrl+Shift+D 解锁拖动」，
        >=240px 只剩「已固定」，更窄什么都不画 ——
        而用户把小窗调到 260px，正好落在信息量为零的那一档。

        所以这次按热键必须**在浮窗上**留下一条看得见的痕迹。
        """
        if self._closing:
            return
        with self._state_lock:
            self._state["notice"] = str(text or "")[:120]
            self._state["notice_until"] = time.time() + max(0.5, float(seconds))
        self._repaint()
