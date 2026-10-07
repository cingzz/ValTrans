# -*- coding: utf-8 -*-
# 作者: cing  ·  https://github.com/cingzz
# 许可: GPL-3.0 + 商业授权（闭源/商用需向作者申请授权），见 LICENSE 与 LICENSE-COMMERCIAL.md
#
"""Web UI 桥接层：pywebview Api 对象。

核心原则：core/services 零改动复用，本层只做"调用 + 事件推送"。
事件统一走 window.__vt.emit(name, payload)（见 webui/src/api.js）。

注意：pywebview 会把 Api 的**所有公开属性**递归暴露给 JS（并沿属性树深爬
第三方对象图），因此内部状态一律用下划线前缀（_win/_pipeline/…），
公开方法即 JS 可调用的 API。
"""
from __future__ import annotations

import ctypes
import json
import logging
import os
import sys
import threading
import time
import webbrowser
from dataclasses import asdict

from ..core.config import AppConfig, ASR_PRESETS, MT_PRESETS, CONFIG_DIR, LOG_DIR
from ..core.pipeline import Pipeline
from ..core.audio_capture import find_cable_devices
from ..services.engine import CloudASR, Translator
from ..services.tts import TTSPlayer, VOICE_CATALOG
from ..core.security import close_pool as _close_pool
from ..services.reverse_ptt import ReversePTT
from ..services import error_reports
from ..services import update
from ..services import tm


def _legacy_stats() -> dict:
    """旧自学习模块（learning.py）的计数 —— 只为如实展示历史量，不再新增。"""
    try:
        from ..services import learning
        return learning.stats()
    except Exception:
        return {}
from ..version import VERSION  # 版本唯一来源

OVERLAY_TITLE = "vt-overlay-window-v02"   # 唯一标题：FindWindowW 定位句柄用
OVERLAY_FIXED_H = 380                     # 浮窗固定高度（上下两区固定槽位，不随内容伸缩）
_SW_SHOWNOACTIVATE = 4                    # ctypes ShowWindow：pywebview show() 失效时的兜底


def _asset(rel: str) -> str | None:
    """定位资源文件：开发态=项目根，打包态=sys._MEIPASS（onedir 的 _internal）。"""
    roots = []
    if getattr(sys, "frozen", False):
        roots.append(sys._MEIPASS)
    base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    roots += [base, os.path.join(base, "_internal")]
    for root in roots:
        p = os.path.join(root, rel)
        if os.path.exists(p):
            return p
    return None


def _hwnd_by_title() -> int:
    """按唯一标题定位浮窗句柄（0 = 尚未创建）。"""
    return int(ctypes.windll.user32.FindWindowW(None, OVERLAY_TITLE) or 0)


def _is_visible(hwnd: int) -> bool:
    return bool(hwnd) and bool(ctypes.windll.user32.IsWindowVisible(hwnd))


def _overlay_cfg_payload(cfg: AppConfig) -> dict:
    """浮窗页面需要的配置子集（JS 侧 onConfig / get_overlay_state 共用同一份）。"""
    return {
        "overlay_font_size": cfg.overlay_font_size,
        "show_original": cfg.show_original,
        "show_speaker": cfg.show_speaker,
        "overlay_locked": cfg.overlay_locked,
        "overlay_enabled": cfg.overlay_enabled,
        "overlay_opacity": cfg.overlay_opacity,
        "overlay_pinned": getattr(cfg, "overlay_pinned", False),
        "overlay_width": cfg.overlay_width,
        "overlay_height": int(getattr(cfg, "overlay_height", 380) or 380),
        "hotkey_lock": cfg.hotkey_lock,
        "hotkey_move": getattr(cfg, "hotkey_move", ""),
        "version": VERSION,
    }


def _uiwin_patch(patch: dict) -> dict:
    """仅放行允许写入配置的字段（白名单）。

    注意：overlay_style / overlay_anim / fade_seconds 属于旧 PySide6 界面的
    5 样式×4 动画体系，Web 浮窗只有一套视觉，这里不再放行（Qt 回退路径
    直接写 AppConfig，不经过本白名单，不受影响）。
    """
    allowed = {
        "capture_mode", "cable_output_device", "loopback_device", "mic_device",
        "vad_mode", "rms_threshold", "partial_enabled", "draft_interval_ms",
        "asr_preset", "asr_key", "mt_preset", "mt_key", "custom_asr_url", "custom_asr_model",
        "custom_mt_url", "custom_mt_model", "target_lang", "reverse_target_lang", "lock_source_lang",
        "overlay_x", "overlay_y", "overlay_opacity", "overlay_font_size", "overlay_width",
        "overlay_locked", "overlay_enabled", "overlay_pinned", "overlay_height",
        "show_original", "show_speaker", "tts_enabled", "tts_voice", "tts_rate", "tts_pitch",
        "streamer_mode", "asr_mode", "auto_copy",
        "hotkey_lock", "hotkey_review", "hotkey_ptt", "hotkey_move",
        "first_run_done", "disclaimer_accepted",
    }
    return {k: v for k, v in patch.items() if k in allowed}


# ---------------------------------------------------------------------------
# v0.2.16 安全：Key 脱敏回显
# ---------------------------------------------------------------------------
# get_state / save_cfg 此前把 asr_keys/mt_keys **明文全量**返回给渲染进程
# （WebView2 多进程模型，前端任何 XSS/被篡改都等于 Key 泄漏）。
# 现在回显 "••••"+尾4位；前端原样传回时按掩码识别、不当作新 Key 落盘。
def _mask_secret(v: str) -> str:
    v = (v or "").strip()
    if not v:
        return ""
    return "••••" + v[-4:] if len(v) > 4 else "••••"


def _is_masked_secret(v: str) -> bool:
    return bool(v) and "••••" in v


def _masked_cfg(cfg) -> dict:
    d = asdict(cfg)
    d["asr_keys"] = {k: _mask_secret(v) for k, v in (cfg.asr_keys or {}).items()}
    d["mt_keys"] = {k: _mask_secret(v) for k, v in (cfg.mt_keys or {}).items()}
    return d


class Api:
    """暴露给 JS 的 window.pywebview.api（公开方法 = JS 可调用项）。"""

    def __init__(self):
        self._cfg = AppConfig.load()
        LOG_DIR.mkdir(parents=True, exist_ok=True)

        self._asr = CloudASR(self._cfg)
        self._mt = Translator(self._cfg)
        self._tts = TTSPlayer(voice=self._cfg.tts_voice,
                              enabled=self._cfg.tts_enabled and not self._cfg.streamer_mode,
                              rate=self._cfg.tts_rate, pitch=self._cfg.tts_pitch,
                              sf_key=self._cfg.mt_key())
        self._pipeline = Pipeline(self._cfg, on_subtitle=self._on_subtitle,
                                  on_status=self._on_status,
                                  on_partial=self._on_partial)
        # TTS 播放期间暂停采集识别（防 loopback 回声死循环）
        self._pipeline.external_gate = self._tts.playing
        # ★ v0.2.19 错误可见性：丢段让用户看得见（竞品共同的体验灾难是
        #   "坏了但用户不知道"）
        self._pipeline.on_drop = self._on_pipeline_drop
        self._ptt = ReversePTT(self._cfg, self._asr, self._mt,
                               on_result=self._on_ptt_result, on_state=self._on_ptt_state)

        self._win = None          # 主窗
        # v0.2.10 自绘标题栏：主窗置顶状态。
        # 必须是 _ 前缀 —— pywebview 会把 Api 的公开属性递归深爬，
        # 公开属性挂到 Window/句柄会无限递归（血泪教训）
        self._main_top = False
        self._overlay = None      # 字幕浮窗（懒创建）
        self._overlay_lock = threading.Lock()   # ★ v0.2.16：懒创建必须持锁
        self._overlay_shown = False   # 浮窗当前是否处于可见态
        self._apply_overlay_style = None   # host 注入（锁定切换后刷新 WS_EX_TRANSPARENT）
        self._hotkeys = None
        self._tray_icon = None
        self._echo_stream = None   # 回声测试实时流
        self._echo_timer = None
        self._preview_player = None  # 试听用一次性播放器
        self._preview_gen = 0      # 试听代次：防止旧播放器抢跑
        self._notice: str | None = None
        # v0.2.19：热键串行队列必须在 _start_hotkeys() **之前**就绪 ——
        # 后者结尾会 _ensure_action_thread()，那时队列必须已存在。
        # 放错顺序 = 第一次按热键就 AttributeError，而它发生在 pynput
        # 线程里，只有日志能看到（老教训：「报错路径自己先崩」）。
        self._init_action_queue()
        self._start_hotkeys()

    # ---------- 事件推送 ----------
    def _emit(self, name: str, payload: dict) -> None:
        if self._win is None:
            return
        js = json.dumps(payload, ensure_ascii=False)
        try:
            self._win.evaluate_js(f"window.__vt && window.__vt.emit('{name}', {js})")
        except Exception:
            pass

    def _overlay_js(self, code: str) -> None:
        if self._overlay is None:
            return
        try:
            self._overlay.evaluate_js(code)
        except Exception:
            pass

    def _push_overlay_config(self) -> None:
        """把配置推给浮窗页面。

        推送只是「更新」通道；页面挂载时的初始配置由 JS 主动拉 get_overlay_state()
        完成，因此这里的调用时机不再影响首屏渲染。
        """
        js = json.dumps(_overlay_cfg_payload(self._cfg), ensure_ascii=False)
        self._overlay_js(f"window.onConfig && window.onConfig({js})")
        if self._overlay is not None:
            try:
                # v0.2.1 回归修复：此处曾写死 170，把浮窗从定稿高度 380 压回 170
                self._overlay.resize(
                    self._cfg.overlay_width,
                    int(getattr(self._cfg, "overlay_height",
                               OVERLAY_FIXED_H) or OVERLAY_FIXED_H))
            except Exception:
                pass

    # ---------- 管线回调 ----------
    def _on_status(self, s: str) -> None:
        base, _, rest = s.partition(":")
        m = {"listening": ("listening", "监听中 · 等待队友说话…"),
             "recognizing": ("recognizing", "识别+翻译中…"),
             "stopped": ("idle", "未启动")}
        if base in m:
            kind, text = m[base]
            self._emit("status", {"kind": kind, "text": text, "desc": rest})
            if base == "listening":
                self._overlay_status("listening", f"监听中 · {rest}" if rest else "等待队友说话…")
            elif base == "recognizing":
                self._overlay_status("recognizing", "识别+翻译中…")
            elif base == "stopped":
                self._overlay_status("stopped", "")
        elif base == "asr_error":
            self._emit("status", {"kind": "error", "text": rest or "云端错误", "desc": ""})
            self._overlay_status("error", rest or "云端错误")

    def _on_pipeline_drop(self, total: int) -> None:
        """丢段可见性（v0.2.19）：节流通知——用户至少知道
        「系统在努力，是网络不行」，而不是以为软件坏了。"""
        if total in (1, 5, 20, 50) or (total >= 100 and total % 100 == 0):
            try:
                self.notify(f"网络不稳：本次会话已丢弃 {total} 段语音"
                            f"（云端拥堵，翻译仍在继续）")
            except Exception:
                pass

    def _on_subtitle(self, ev) -> None:
        payload = {"original": ev.original, "translated": ev.translated,
                   "latency_ms": ev.latency_ms, "fallback": ev.fallback,
                   "error": getattr(ev, "error", ""), "time": time.strftime("%H:%M:%S"),
                   "mine": False,
                   # v0.2.21：队友说中文时 translate_gate 照抄，
                   # original===translated，前端无条件画两行就是同一句话显示两遍
                   #（用户截图）。判定在 pipeline._want_original_line 算好了送过来，
                   # 前端只读不算 —— 「是不是中文」只有一份实现。
                   "show_original": getattr(ev, "show_original", True)}
        self._emit("subtitle", payload)
        self._overlay_show(ev.original, ev.translated, "队友")
        # 【v0.2.4 修复】队友字幕不再朗读。
        # 原来这里会 self._tts.say(ev.translated, "zh")，导致队友每说一句
        # 译文就被 TTS 念一遍——在游戏里等于双重噪声，还污染音频采集链路
        # （external_gate 会把 TTS 声音当成队友语音再识别一遍）。
        # TTS 只服务 PTT：我说中文 -> 让我听见自己该说的是外语。
        # 想听队友译文可开「主播模式」(streamer_mode)，由它单独控制。

    def _on_partial(self, orig: str, trans: str) -> None:
        """同传草稿（v0.2.16）：说话过程中的增量识别+翻译。

        只推浮窗、不广播主窗——与 PTT `asr:` 中间态同一策略：草稿每秒
        刷新一次，推进 Live 历史列表会刷屏。说完后的最终稿走 _on_subtitle
        正常路径，自动替换浮窗上的草稿。
        """
        if not self._cfg.overlay_enabled:
            return
        try:
            self._overlay_show(orig, trans, "队友")
        except Exception:
            logging.getLogger("valtrans.webui").debug(
                "同传草稿推送失败", exc_info=True)

    def _on_ptt_result(self, translated: str, original: str) -> None:
        from ..core.pipeline import _want_original_line
        self._emit("subtitle", {"original": original + "（我）", "translated": translated,
                                "latency_ms": 0, "fallback": False, "error": "",
                                "time": time.strftime("%H:%M:%S"), "mine": True,
                                 # v0.2.21：PTT 中文进/外语出，两行本就有意义；
                                 # 但反译失败时 trans==orig，别把同一句画两遍。
                                 # 复用后端同一份判定，不在前端/此处另写一套。
                                 "show_original": _want_original_line(
                                     original, translated)})
        self._overlay_show(original, translated, "我", True)
        # ★ 兜底复位：ReversePTT 正常会发 "ready"，但万一那次推送丢了，
        #   浮窗的橙色「正在听/识别中」会永远赖着（真机 实测的
        #   「卡黄色」）。结果都出来了，状态必须归位。
        self._overlay_ptt("ready")
        # PTT 译文朗读：原先漏调，导致「我说中文→翻译出英语但没有声音」。
        # 用目标语言发音（reverse_target_lang），比固定 zh 更自然。
        if translated and self._tts.enabled:
            self._tts.say(translated, self._cfg.reverse_target_lang or "en")

    def _overlay_ptt(self, s: str) -> None:
        """把 PTT 状态推给游戏内浮窗（橙色「正在听」提示）。

        状态来自 ReversePTT.on_state：
            recording     按住中 -> 浮窗橙色高亮 + 电平律动
            translating   松手识别翻译中 -> 转圈
            ready         完成 -> 恢复常态
            too_short     按太短 -> 短提示
            empty_result  没听清
            mic_error / error:xxx -> 报错
        """
        if self._overlay is None:
            # 用户可能在 PTT 之前浮窗还没建；按下说话本身就是显示意图
            if not self._cfg.overlay_enabled:
                return
            if not self._ensure_overlay():
                return
            self._show_overlay()
        self._ptt_recording = s.startswith("recording")
        if not self._ptt_recording:
            self._ptt_level = 0.0
        kind, text = "idle", ""
        if s.startswith("recording"):
            kind, text = "listening", "正在听…（松开发送）"
        elif s.startswith("translating"):
            kind, text = "working", "识别翻译中…"
        elif s.startswith("too_short"):
            kind, text = "warn", "按太短了"
        elif s.startswith("empty_result"):
            kind, text = "warn", "没听清，再说一次"
        elif s.startswith("mic_error") or s.startswith("error"):
            kind, text = "error", "麦克风/网络出错：" + s.split(":", 1)[-1][:40]
        else:
            kind, text = "idle", ""
        try:
            self._overlay_js(
                f"window.onPtt && window.onPtt({json.dumps(kind)}, {json.dumps(text)})")
        except Exception:
            logging.getLogger("valtrans.webui").debug("浮窗 PTT 推送失败", exc_info=True)

    def warmup_pool(self) -> None:
        """启动时预热 HTTP 连接池（冷连接 5-12s，会落在第一句字幕上）。

        ★ v0.2.16：预热逻辑挪到 Translator.warmup()——旧实现调的
        self._chat 是**不存在的方法**（Api 类没有），AttributeError 被
        except 吞掉，预热从未生效过；且引擎里的 with 把池化客户端逐请求
        close，预热了也白搭。两处都修了，这里只负责起后台线程。
        """
        try:
            import threading as _th
            _th.Thread(target=self._mt.warmup, daemon=True).start()
        except Exception:
            logging.getLogger("valtrans.webui").debug("连接池预热失败", exc_info=True)

    def get_ptt_level(self) -> int:
        """PTT 录音期间的麦克风电平（0-100），供浮窗画律动条。

        ReversePTT 的采集流把每块 RMS 累积到 _ptt_level；
        没在录音时返回 0，浮窗据此停止轮询（零开销）。
        """
        if not getattr(self, "_ptt_recording", False):
            return 0
        return int(min(100, float(getattr(self._ptt, "_level", 0.0)) * 400))

    def _on_ptt_state(self, s: str) -> None:
        """PTT 状态：同时推主窗与游戏内浮窗。

        浮窗必须在按下说话的瞬间就亮出「正在听」，否则用户在游戏里
        按住热键却看不到任何反馈，会以为软件没反应。

        `asr:` 前缀是**中间态**（识别已出字、翻译还在跑）：只推浮窗
        （卡面先显示原文），不广播给主窗 —— Live.jsx 对未知状态串会
        原样显示，"asr:xxx" 会直接糊在界面上。
        """
        if s.startswith("asr:"):
            try:
                self._overlay_show(s[4:], "翻译中…", "我", True)
            except Exception:
                logging.getLogger("valtrans.webui").debug(
                    "PTT 中间态推送失败", exc_info=True)
            return
        self._emit("ptt", s)
        self._overlay_ptt(s)

    # ---------- 浮窗（双卡状态面板；懒创建：开始翻译后才建窗） ----------
    def _ensure_overlay(self) -> bool:
        """确保浮窗已创建且页面 JS 已挂载。返回是否可用。"""
        if self._overlay is not None:
            return True
        # ★ v0.2.16：懒创建必须持锁——调用方有 ASR 线程/热键线程/托盘线程/
        #   js_api 线程，check-then-act 竞态会双建浮窗、泄漏 STA 线程
        with self._overlay_lock:
            if self._overlay is not None:
                return True
            return self._create_overlay()

    def _create_overlay(self) -> bool:
        factory = getattr(self, "_overlay_factory", None)
        if factory is None:
            return False
        log = logging.getLogger("valtrans.webui")
        try:
            ov = factory()
        except Exception:
            log.exception("浮窗创建失败")
            self.notify("字幕浮窗创建失败，请查看日志")
            return False
        if ov is None:      # webview.create_window 在非主线程初始化失败时会返回 None
            log.error("create_window returned None（初始化被中止）")
            self.notify("字幕浮窗初始化失败，请重启软件")
            return False
        self._overlay = ov
        log.info("overlay created")
        # 等页面 JS 挂载完成（onSubtitle / onConfig 可用）。
        # 注意：探测期间 evaluate_js 抛异常是「页面还没起来」的正常现象，必须继续重试；
        # 旧代码在这里直接 break，导致配置推送早于 React 挂载 → 面板全空白。
        #
        # 原生浮窗（v0.2.11 NativeOverlay）没有页面可探测：evaluate_js 的
        # 就绪探测对它只会永远返回 None，循环白等 6 秒才亮窗 —— 靠
        # IS_NATIVE 标记跳过（它的就绪已在构造函数里等 Form 建好）。
        ready = False
        if getattr(self._overlay, "IS_NATIVE", False):
            ready = True
        else:
            for _ in range(60):
                try:
                    if self._overlay.evaluate_js(
                            "!!(window.onSubtitle && window.onConfig)"):
                        ready = True
                        break
                except Exception:
                    pass
                time.sleep(0.1)
        log.info("overlay js ready=%s", ready)
        # ★ v0.2.22：建窗之后**必须**重刷窗口样式，否则首次创建出来的浮窗
        #   不带 WS_EX_TRANSPARENT —— 哪怕配置里 pinned=True 也照样能拖。
        #   这是「先固定住了、过一会又能拖」的第二个来源：
        #   _show_overlay 会刷样式，但浮窗是**懒创建**的，第一条字幕走的是
        #   _create_overlay 这条路，原来这里只推了页面配置、没刷样式。
        #   （项目铁律：凡是需要 show 之后重刷的地方，一处都不能漏。）
        if getattr(self, "_apply_overlay_style", None):
            try:
                self._apply_overlay_style()
            except Exception:
                logging.getLogger("valtrans.webui").debug(
                    "建窗后重刷浮窗样式失败", exc_info=True)
        # 兜底：无论探测是否成功都再推一次配置（页面若已挂载则会被覆盖更新）
        self._push_overlay_config()
        return True

    def _show_overlay(self) -> bool:
        """统一的「把浮窗显示出来」链路：show → resize → 重刷窗口样式 → 可见性校验。

        浮窗必须走这里，禁止在别处裸调 `_overlay.show()`：
        WinForms 平台下 show() 会重建 HWND，导致此前施加的 WS_EX_LAYERED /
        半透明 / DWM 圆角 / 鼠标穿透全部丢失，所以样式要在 show 之后重刷。
        """
        if self._overlay is None:
            return False
        log = logging.getLogger("valtrans.webui")
        # 位置：已显示过则记住用户拖动的新位置，否则用配置里的位置
        # ★ v0.2.16：删掉 `sy - 240` 默认位置分支——那是 170 高时代的遗留，
        #   380 高的面板底部 140px 出屏，且坏位置随后被写回配置永久生效。
        #   overlay_x<0 哨兵 = 用浮窗构造函数里的正确默认定位（右下角）。
        try:
            if not self._overlay_shown and self._cfg.overlay_x >= 0:
                self._overlay.move(self._cfg.overlay_x, self._cfg.overlay_y)
        except Exception:
            pass
        try:
            self._overlay.show()
        except Exception:
            log.exception("show() 调用失败")
        # resize 必须在 show 之后（show 前的 resize 会被 WinForms 吞掉并回落旧高度）
        try:
            self._overlay.resize(
                    self._cfg.overlay_width,
                    int(getattr(self._cfg, "overlay_height",
                               OVERLAY_FIXED_H) or OVERLAY_FIXED_H))
        except Exception:
            pass
        # show 之后重刷窗口样式（HWND 可能已被重建）
        if getattr(self, "_apply_overlay_style", None):
            try:
                self._apply_overlay_style()
            except Exception:
                log.exception("重刷浮窗样式失败")
        # 可见性校验：pywebview show() 偶发不生效时，直接用 Win32 ShowWindow 兜底
        hwnd = _hwnd_by_title()
        if not _is_visible(hwnd):
            log.warning("show() 后窗口仍不可见 (hwnd=%s)，改用 ShowWindow 兜底", hwnd)
            if hwnd:
                try:
                    ctypes.windll.user32.ShowWindow(hwnd, _SW_SHOWNOACTIVATE)
                    ctypes.windll.user32.SetWindowPos(
                        hwnd, -1, 0, 0, 0, 0, 0x0001 | 0x0002)  # HWND_TOPMOST, NOMOVE|NOSIZE
                except Exception:
                    log.exception("ShowWindow 兜底失败")
        if not _is_visible(hwnd):
            self.notify("字幕浮窗无法显示，请查看 %APPDATA%/ValTrans/logs/webui.log")
            return False
        self._overlay_shown = True
        try:
            # ★ v0.2.16：只位置真变了才落盘——此前**每条字幕**都全量重写一次
            #   config.json（含 Key），非原子+四线程并发写，有写坏配置把
            #   Key 清零的风险（v0.2.3 同款敞口）
            nx, ny = self._overlay.x, self._overlay.y
            if (nx, ny) != (self._cfg.overlay_x, self._cfg.overlay_y):
                self._cfg.overlay_x, self._cfg.overlay_y = nx, ny
                self._cfg.save()
        except Exception:
            pass
        log.info("overlay shown: %sx%s hwnd=%s",
                 self._cfg.overlay_width, OVERLAY_FIXED_H, hwnd)
        return True

    def _overlay_show(self, orig: str, trans: str, speaker: str, mine: bool = False) -> None:
        """把最新一句推进对应卡片（上卡=队友 / 下卡=我）；面板常驻、无历史。"""
        if not self._cfg.overlay_enabled:
            return   # 先查开关：禁用时不得创建/显示任何浮窗窗口
        if self._overlay is None and not self._ensure_overlay():
            return
        if not self._show_overlay():
            return
        o = json.dumps(orig, ensure_ascii=False)
        t = json.dumps(trans, ensure_ascii=False)
        sp = json.dumps(speaker, ensure_ascii=False)
        self._overlay_js(f"window.onSubtitle({o}, {t}, {sp}, {json.dumps(mine)})")

    def _overlay_status(self, kind: str, text: str) -> None:
        """管线状态 → 面板头部与等待行；停止时隐藏面板。

        注意：非 stopped 分支必须在浮窗不存在时就地创建。
        旧代码开头一律 `if self._overlay is None: return`，导致
        「点开始翻译 → 管线发 listening → 在这里被拦下 → 浮窗永不创建」，
        必须等第一条真实字幕（_on_subtitle）才建窗；队友不说话就永远看不到面板。
        「开始翻译」本身就是明确的显示意图，此时就该亮窗。
        """
        if kind == "stopped":
            if self._overlay is not None:
                try:
                    self._overlay.hide()
                except Exception:
                    pass
            self._overlay_shown = False
            self._overlay_js("window.onStatus('stopped', '')")
            return
        if not self._cfg.overlay_enabled:
            return
        try:
            if self._overlay is None and not self._ensure_overlay():
                return
            if not self._overlay_shown:
                self._show_overlay()
            t = json.dumps(text, ensure_ascii=False)
            self._overlay_js(f"window.onStatus({json.dumps(kind)}, {t})")
        except Exception:
            logging.getLogger("valtrans.webui").exception("浮窗状态更新失败")


    def review_overlay(self) -> dict:
        """回看：重新显示面板（最近字幕已在面板行内）。返回结果供 UI 提示。"""
        if not self._cfg.overlay_enabled:
            self.notify("字幕显示当前是关闭的，请在主页「字幕开关」里打开")
            return {"ok": False, "reason": "disabled"}
        if not self._ensure_overlay():
            return {"ok": False, "reason": "create_failed"}
        ok = self._show_overlay()
        if ok:
            self._overlay_js("window.onStatus('listening', '等待队友说话…')")
        return {"ok": ok}

    # ---------- 误报上报（v0.2.11）----------
    # 需求「当用户遇到翻译报错时，可以让用户自己去提交误报。
    # 提交方式有两种：1. 手动添加。2. 找到历史消息里的某一条，
    # 直接点进去，选择『提交误报』。」
    #
    # 两个入口**共用 error_reports.report() 这一个出口**，
    # 不做两份实现 —— 分级规则、隐私边界、立即生效都在那一个函数里。
    def report_error(self, src: str, shown: str, correct: str,
                     lang: str = "en", from_history: bool = False) -> dict:
        """提交一条误报。`from_history` 只作记录，用于日后看两个入口的用量。"""
        try:
            r = error_reports.report(src, shown, correct, lang, from_history)
        except Exception:
            logging.getLogger("valtrans.webui").exception("误报上报失败")
            return {"ok": False, "msg": "上报失败，请重试"}
        if r.get("ok") and r.get("msg"):
            self.notify(r["msg"])
        return r



    def check_update(self) -> dict:
        """检查更新（拉 GitHub Releases）。

        **不自动下载、不自动替换 exe** —— 静默下载 60MB 并替换正在运行的
        程序是所有软件最招人烦的行为，而且安装包没签名的话静默替换
        等于绕过 Windows 的安全提示。这里只报「有新版 + 多大 + 改了什么」，
        点不点、什么时候点由用户决定。
        """
        try:
            return update.check(local_version=VERSION)
        except Exception:
            logging.getLogger("valtrans.webui").exception("检查更新失败")
            return {"ok": False, "has_update": False, "msg": "检查更新失败"}

    # ---------- 上报反馈（v0.2.22）----------
    def get_feedback_draft(self) -> dict:
        """收集「上报反馈」要用的诊断信息 + 日志尾巴，供前端拼 GitHub issue。

        为什么是「预填」而不是「一键上传」
        ----------------------------------
        GitHub 的 issue 创建接口**必须带密钥**，而密钥不能随安装包分发给
        每一个用户（那等于把仓库的写权限公开）。所以这里只做**准备**：
        把诊断信息与日志填进 issue 正文，用户点「打开 GitHub」提交。

        为什么只给日志「尾巴」而不是整份
        --------------------------------
        GitHub 单条 issue 正文上限约 64KB，而实测 webui.log 有 282KB。
        整份塞进去用户还得自己删；取尾部是因为出问题的时间点一定在最后，
        前面 99% 是无关的历史。要细节可以按返回的路径自己把文件拖进 issue。

        为什么敢把日志放进去（这是隐私决策，不是随手为之）
        --------------------------------------------------
        实测扫描本机 webui.log 的 26 万字符：无 API Key、无 Authorization 头、
        无 Windows 用户名/路径、无邮箱、无内网地址。
        日志只记「程序做了什么」，不记「用户说了什么」——
        v0.2.16 起翻译原文/译文一律不落盘。
        即便如此，UI 上仍会明示「日志可能含本机路径，发前请看一眼」，
        发送与否由用户决定。
        """
        try:
            from src.services.feedback import build_draft
            return build_draft(local_version=VERSION)
        except Exception:
            logging.getLogger("valtrans.webui").exception("生成反馈草稿失败")
            return {"ok": False, "msg": "读取诊断信息失败"}

    def open_log_folder(self) -> dict:
        """打开日志所在文件夹 —— 用户要把完整日志拖进 issue 时用。"""
        import os as _os
        try:
            from src.core.config import LOG_DIR
            _os.startfile(_os.path.dirname(str(LOG_DIR)))   # noqa: S606
            return {"ok": True}
        except Exception:
            return {"ok": False, "msg": "打不开日志文件夹，路径见反馈面板"}

    def selflearn_stats(self) -> dict:
        """新自学习系统的状态（翻译记忆 + 误报上报）。

        **替换**旧的 `learning.py` 统计（v0.2.11）：
        旧模块学的是「云端自己翻出来的译文出现 8 次」，等于把云端的错误
        一起学了 —— 它的候选池里可能有「他们正在设立」这种胡话。
        新系统的学习源是**用户确认过的**译文，所以状态字段完全不同。

        为什么必须替换而不是并存：
        两套学习机制同时存在，用户看到两个「自学习」、不知道哪个生效，
        而旧的那套正在往词库里塞错误译文（同一个判断只能
        有一份实现）。
        """
        try:
            tm_st = tm.stats()
        except Exception:
            tm_st = {"total": 0, "by_kind": {}}
        try:
            reps = error_reports.list_reports(200)
        except Exception:
            reps = []
        by_level = {"local": 0, "consensus": 0, "conflict": 0}
        for r in reps:
            strong = [p for p in r.get("proposals", [])
                      if p.get("reporters", 0) >= 3]
            if len(strong) > 1:
                by_level["conflict"] += 1
            elif strong:
                by_level["consensus"] += 1
            else:
                by_level["local"] += 1
        return {
            "total_entries": tm_st.get("total", 0),
            "by_kind": tm_st.get("by_kind", {}),
            "user_taught": tm_st.get("by_kind", {}).get("user", 0),
            "public": tm_st.get("by_kind", {}).get("public", 0),
            "seed": tm_st.get("by_kind", {}).get("seed", 0),
            "reports": len(reps),
            "local_only": by_level["local"],
            "consensus": by_level["consensus"],
            "conflict": by_level["conflict"],
            "threshold": error_reports.ADOPT_MIN_DISTINCT_REPORTS,
            # 旧机制的计数仍然如实报出来，让人知道历史上被学过多少条
            "legacy_candidates": _legacy_stats(),
        }

    # ---------- 通知横幅（JS bus.on('notice') 的真正生产者） ----------
    def notify(self, text: str) -> None:
        self._notice = text
        self._emit("notice", {"text": text})
        # ★ v0.2.21：**也**推到浮窗。
        # 起因：用户报「没有固定这个弹窗的快捷键了」—— 热键一直有注册
        # （日志：全局热键已启动 … <ctrl>+<shift>+d），toggle_pin 也一直
        # 有 notify。但 notify 只发到主窗口，而用户反馈时**正在打游戏**、
        # 主窗口收着 —— 反馈存在于用户看不到的地方，于是被判断成「没这个功能」。
        # 浮窗是游戏里唯一可见的东西，所以提示必须也走那里。
        #
        # 只在浮窗**已经存在**时推：不能因为一条提示就把空闲时的浮窗
        # 凭空创建出来（浮窗懒创建是有意设计的，见下方说明。
        try:
            ov = self._overlay
            if ov is not None and hasattr(ov, "show_notice"):
                ov.show_notice(text)
        except Exception:
            pass          # 推提示失败无所谓：主窗口已经收到 notice，
            # 且**绝不能**因为一条提示把浮窗创建出来或抛出中断调用方

    def dismiss_notice(self) -> None:
        self._notice = None

    def _prune_dead_overlay(self) -> bool:
        """浮窗被用户关掉（X / 任务管理器杀）时清理状态，返回是否清理过。

        v0.2.11（真机 实测）：
        「我可以直接把弹窗进程关掉，但是我那个软件里面还是显示我正在开启」

        根因：`self._overlay` 是一个**已经死掉的 pywebview Window 对象**，
        它的 `native.Handle` 指向已销毁的 HWND。
          · 再调 `_show_overlay()` -> `show()` 抛异常 / 或者 show 了个死窗口，
            于是「怎么都出不来」
          · UI 那边只看到 `overlay_visible` 从 true 变 false，
            但没人告诉它「你关掉的那个已经废了」，于是状态卡在中间

        所以这里要做的**不只是报告状态，还要把死引用清掉**，
        让下一次显示能重新创建一个真正的窗口。
        """
        w = self._overlay
        if w is None:
            return False
        # ★ 保守判定：**拿不到句柄就当作活着**。
        #   v0.2.11 踩过：`w.native.Handle` 在某些时刻拿不到有效 HWND
        #   （窗口刚创建、WinForms 还没把句柄交出来、或它抛异常），
        #   我原来把它当成「已死」，结果浮窗被反复重建：
        #       overlay shown -> 判定已死 -> overlay created -> 又判定已死 -> …
        #   渲染永远稳定不下来，面板一片空白（日志里能直接看到这个循环）。
        #
        #   **误杀活窗口比漏判死窗口严重得多**：
        #   漏判 -> 用户看到浮窗没了，重开一下就好；
        #   误杀 -> 浮窗疯狂重建，软件看起来像坏了。
        hwnd = 0
        try:
            hwnd = int(w.native.Handle or 0)
        except Exception:
            hwnd = 0
        if not hwnd:
            return False                      # 读不到 -> 不动它
        try:
            by_title = int(ctypes.windll.user32.FindWindowW(
                None, OVERLAY_TITLE) or 0)
        except Exception:
            by_title = 0
        # 只要**任何一种方式**还能找到这个窗口，就认为它活着。
        # `native.Handle` 与 `FindWindowW` 是两条独立证据，
        # 必须「两条都失败」才判死 —— 单条证据的误判率太高。
        if ctypes.windll.user32.IsWindow(hwnd):
            return False
        if by_title and ctypes.windll.user32.IsWindow(by_title):
            return False
        # ⚠ v0.2.11：**这里不再清引用**（曾导致 stop() 隐藏不了浮窗）。
        #   实测两次：清引用之后 `stop()` 里的 `if self._overlay is not None`
        #   会跳过 hide()，那个窗口就被**孤立留在屏幕上** ——
        #   「停止后浮窗还在」正是这么来的。
        #   误清引用的代价（窗口孤立、无法隐藏）远大于收益（下次重建得干净点），
        #   所以这一版**只上报状态，不改状态**。
        #   原则：修复引入回归时先回退，不要在更深处打补丁。
        # ★ v0.2.16：下方「清引用」的死代码已删——`return False` 之后
        #   永远不可达，留着只会让人以为清理逻辑存在（实际上没有）。
        return False

    def get_overlay_state(self) -> dict:
        """浮窗页面挂载时主动拉取配置（竞态免疫的初始状态通道）。

        v0.2.11 追加 `overlay_visible`：真机 反馈
        「打开软件时字幕没显示，状态框却是绿的『已显示』，要关了再开才对」。

        根因是**两个概念被混为一谈**：
          · `overlay_enabled` = 「允许显示字幕」（一个开关值）
          · 浮窗**实际在不在屏幕上** = 另一件事 —— 它是**懒创建**的
            （设计取舍：队友不说话就不建窗，避免空窗闪屏）
        UI 拿 `overlay_enabled` 当「已显示」显示，所以配置为开、屏幕上
        没窗时就说谎。必须把**实际状态**单独报出来。
        """
        d = _overlay_cfg_payload(self._cfg)
        # 先清死引用再看状态，否则会拿着已销毁的句柄报「可见」
        self._prune_dead_overlay()
        d["overlay_visible"] = self._overlay_is_visible()
        return d

    def _overlay_is_visible(self) -> bool:
        """浮窗此刻是否真的在屏幕上（不是「允许显示」）。"""
        w = self._overlay
        if w is None:
            return False
        try:
            hwnd = w.native.Handle
            if not hwnd:
                return False
            return bool(ctypes.windll.user32.IsWindowVisible(hwnd))
        except Exception:
            # 拿不到就保守说「不可见」：宁可让 UI 显示等待态，
            # 也不能在没窗的时候说「已显示」
            return False

    def toggle_lock(self) -> None:
        """锁定/解锁浮窗。两条触发路径（主页按钮 / 全局热键）都必须走到这里，
        并立即刷新 WS_EX_TRANSPARENT——否则解锁后鼠标依然穿透，表现为"永远锁定"。"""
        self._cfg.overlay_locked = not self._cfg.overlay_locked
        self._cfg.save()
        self._push_overlay_config()
        if self._apply_overlay_style:
            self._apply_overlay_style()
        # ★ v0.2.21：锁定状态变化**肉眼完全看不见**（改的是鼠标穿透），
        #   原来这里一声不吭，用户按了热键只以为没生效 —— 和 toggle_pin
        #   同一个病根。所以补上提示（notify 现在也会推到浮窗）。
        self.notify("字幕面板已" + ("锁定穿透（鼠标穿过面板）"
                                if self._cfg.overlay_locked
                                else "解锁（可点按/拖动面板）"))

    # ---------- JS 调用的同步接口 ----------
    def get_state(self) -> dict:
        # v0.2.11：加 `running` 供前端**状态对账**用。
        # 用户实测「多按几次按钮就卡在高亮态」——根因之一是前端
        # `running` 只靠 status 事件更新，事件一丢就永远对不上。
        # 有了这个字段，前端每 3 秒回读一次真值，UI 跑偏也能拉回来。
        _run = bool(getattr(self._pipeline, "_running", None)
                    and self._pipeline._running.is_set())
        # ★ v0.2.16：Key 脱敏回显（此前明文全量返回给渲染进程）
        # ★ v0.2.19：带上管线统计（丢段/失败可见性）
        return {"cfg": _masked_cfg(self._cfg), "version": VERSION,
                "notice": self._notice, "running": _run,
                "stats": dict(getattr(self._pipeline, "stats", {}))}

    def get_voices(self) -> list:
        """音色列表给 JS 下拉框用。

        ⚠ v0.2.10 修真 bug
        ----------------
        这里原来按 4 元组解包 VOICE_CATALOG：
            for name, label, _langs, _multi in VOICE_CATALOG
        但 v0.2.9 把音色改成 6 元组（加了 desc + prosody，性格内嵌进音色），
        于是**每次调用都抛 ValueError: too many values to unpack**，
        打包版日志里能看到（pkg_smoke 才抓到）。
        音色下拉框整个挂掉 —— 而且这种错误只在真跑起来才暴露，
        静态检查和 L3 断言都测不到。

        防御：按位置解包 + 长度兜底，将来目录再加字段也不会再炸。
        """
        out = []
        for item in VOICE_CATALOG:
            vid = item[0]
            label = item[1] if len(item) > 1 else vid
            out.append([vid, label])
        return out

    def get_presets(self) -> dict:
        """预设列表。v0.2.6 起附带价格与实测说明，供 UI 直接标注。

        价格来自官方实时价目（2026-10-02 核对 siliconflow.cn/pricing）：
            Hunyuan-MT-7B   输入免费 / 输出免费
            SenseVoiceSmall 免费（语音）
            Qwen2.5-14B     约 ¥1.26 / M tokens
        写死在 preset 的 price 字段里，避免 UI 端再维护一份。
        """
        return {
            "asr": {k: {"label": p["label"], "price": p.get("price", ""),
                        "note": p.get("note", "")}
                    for k, p in ASR_PRESETS.items()},
            "mt": {k: {"label": p["label"], "price": p.get("price", ""),
                       "note": p.get("note", "")}
                   for k, p in MT_PRESETS.items()},
        }

    # ------------------------------------------------------------------
    # v0.2.6：用量统计 / 自学习 / 更新信息
    # ------------------------------------------------------------------

    def get_usage_stats(self) -> dict:
        """本地 vs 云端占比 + 成本折算（设置页顶部卡片）。

        本地命中 = 0 token。本地占比越高越省钱，所以这个数字
        直接等于「省下了多少」。
        """
        st = self._mt.usage_stats() if self._mt else {}
        if not st:
            return {"local_hits": 0, "cloud_hits": 0, "total": 0,
                    "local_ratio": 0.0, "learning": {}}
        # 按 Qwen ¥1.26/M 的保守价折算云端成本（估算，非账单）
        loc, clo = st["local_hits"], st["cloud_hits"]
        # 实测 Qwen：输入 298 tok + 输出 6.4 tok/句
        est_in = clo * 298
        est_out = clo * 6
        st["cloud_tokens_in"] = est_in
        st["cloud_tokens_out"] = est_out
        st["est_cost_cny"] = round((est_in + est_out) / 1e6 * 1.26, 5)
        st["preset"] = self._cfg.mt_preset
        return st

    def reset_usage_stats(self) -> dict:
        return (self._mt.reset_usage_stats()
                if self._mt else {})










        # ------------------------------------------------------------------
    # v0.2.7：自学习弹窗（用户要求「不要一个一个的框，直接弹窗问」）
    # ------------------------------------------------------------------

    def get_learn_prompt(self) -> dict:
        """自学习弹窗数据：一次性给全，用户点一次搞定。

        返回 {show, items, prefs, auto_adopted}
        """
        from ..services import learning
        prefs = learning.get_prefs()
        items = []
        if not prefs.get("auto_add"):
            for c in learning.list_candidates():
                items.append({
                    "src": c["src"], "dst": c["dst"],
                    "count": c["count"],
                    "span_min": round(c["span_sec"] / 60),
                })
        eaten = learning.auto_adopt_ready()
        if eaten and self._mt:
            self._mt.cache.clear()
        return {"show": bool(items), "items": items, "prefs": prefs,
                "auto_adopted": len(eaten)}

    def learn_confirm(self, items: list, auto_add: bool = False) -> dict:
        """用户点「加入全部」。auto_add=True =「下次不用询问」。"""
        from ..services import learning
        n = 0
        for it in (items or []):
            if learning.adopt(it.get("src", ""), it.get("dst", ""),
                              it.get("target", "zh")):
                n += 1
        learning.set_pref("auto_add", bool(auto_add))
        if self._mt:
            self._mt.cache.clear()
        return {"adopted": n, "auto_add": auto_add,
                "lexicon": len(learning.load_lexicon())}

    def learn_dismiss(self) -> dict:
        """用户点「暂不」。清掉当前候选，等下一轮重新攒。"""
        from ..services import learning
        for c in learning.list_candidates():
            learning.ignore(c["src"], c["target"])
        return {"ok": True}



        # ------------------------------------------------------------------
    # v0.2.7：音色目录 + 人设
    # ------------------------------------------------------------------



    def get_devices(self) -> dict:
        import sounddevice as sd
        capture, mics = [], []
        try:
            for i, d in enumerate(sd.query_devices()):
                if d["max_input_channels"] <= 0:
                    continue
                if "WASAPI" not in sd.query_hostapis(d["hostapi"])["name"]:
                    continue
                mics.append(d["name"])
                if "CABLE" in d["name"].upper() or "Loopback" in d["name"] or "扬声器" in d["name"]:
                    capture.append(d["name"])
        except Exception:
            pass
        return {"capture": capture, "mics": mics}

    def get_level(self) -> int:
        """电平表（JS 侧轮询）。"""
        return int(min(100, getattr(self._pipeline, "last_rms", 0.0) * 400))

    def _rebuild_capture(self, running: bool = False) -> dict:
        """采集来源变了 -> **重建管线**，让新设置立刻生效。

        v0.2.11（真机 实测）：
        「前面选了本机输出语言，开始翻译之后，在设置里又改成虚拟语音，
          但它本质上还是用的本机的输出语言，没有实时进行更换。
          必须要我重新关掉翻译，再重新开启实时翻译才能生效」

        为什么必须重建整个 Pipeline 而不是只 `setattr` 配置：
        采集源（虚拟声卡 / 系统回环）、设备名、断句阈值都是
        `Pipeline.__init__` 里**一次性**读进采集器与 VAD 的，
        管线跑起来之后不会再回看 cfg。所以配置改了它就是不知道。

        注意 `on_subtitle` / `on_status` 必须原样传回去 ——
        重建时漏掉回调，前端就再也收不到字幕与状态了。
        """
        log = logging.getLogger("valtrans.webui")
        if running:
            try:
                self.stop()
            except Exception:
                log.exception("重建前停止管线失败")
        try:
            self._pipeline = Pipeline(self._cfg, on_subtitle=self._on_subtitle,
                                      on_status=self._on_status)
            self._pipeline.external_gate = self._tts.playing
        except Exception:
            log.exception("重建采集管线失败")
            self.notify("切换采集来源失败，详情见 %APPDATA%/ValTrans/logs/webui.log")
            return {"ok": False, "desc": "重建采集管线失败"}
        if running:
            try:
                self.start()
            except Exception:
                log.exception("重建后重启管线失败")
                return {"ok": False, "desc": "重建后重启失败"}
        return {"ok": True, "desc": "采集来源已切换并生效",
                "restarted": running}

    def save_cfg(self, patch: dict) -> dict:
        was_enabled = self._cfg.overlay_enabled      # 改动前开关值，用于判断是否需要主动亮窗
        # v0.2.11（真机 实测）：
        # 「前面选了本机输出语言，开始翻译之后，在设置里又改成虚拟语音，
        #   但它本质上还是用的本机的输出语言，没有实时进行更换。
        #   必须要我重新关掉翻译，再重新开启实时翻译才能生效」
        #
        # 根因：这些值是**管线构造时读的**（`Pipeline(self._cfg, ...)` 只在
        # __init__ 跑一次），改配置只是 `setattr` 到 cfg 上，管线手里那份
        # 采集参数**根本不会重读**。热键那条路有 `_start_hotkeys()` 重启监听，
        # 管线这条路**完全没有** —— 所以要手动重启才生效。
        # ★ v0.2.16：此前这里读的字段名是 audio_mode/audio_device——
        #   AppConfig 里根本没有这两个字段，getattr 恒 None、比较恒相等，
        #   「改采集源自动重建管线」从未生效过（真名见 _audio_sig）。
        def _audio_sig(c):
            return (c.capture_mode, c.cable_output_device,
                    c.loopback_device, c.mic_device)

        audio_before = _audio_sig(self._cfg)
        hotkeys_before = (self._cfg.hotkey_lock, self._cfg.hotkey_review,
                          getattr(self._cfg, "hotkey_move", ""), self._cfg.hotkey_ptt)
        pinned_before = getattr(self._cfg, "overlay_pinned", False)
        clean = _uiwin_patch(patch if isinstance(patch, dict) else {})
        asr_key = clean.pop("asr_key", None)
        mt_key = clean.pop("mt_key", None)
        for k, v in clean.items():
            setattr(self._cfg, k, v)
        # ★ v0.2.16：前端拿到的是掩码回显 "••••abcd"，原样传回时**不能**
        #   当成新 Key 落盘（否则真 Key 被掩码覆盖）
        if asr_key and not _is_masked_secret(asr_key):
            self._cfg.asr_keys[self._cfg.asr_preset] = asr_key.strip()
        if mt_key and not _is_masked_secret(mt_key):
            self._cfg.mt_keys[self._cfg.mt_preset] = mt_key.strip()
        self._cfg.save()
        # 联动
        self._tts.voice_override = self._cfg.tts_voice
        self._tts.rate = self._cfg.tts_rate
        self._tts.pitch = self._cfg.tts_pitch
        self._tts.sf_key = self._cfg.mt_key()   # ★ v0.2.18：CosyVoice 用同一把硅基 Key
        self._tts.enabled = self._cfg.tts_enabled and not self._cfg.streamer_mode
        self._push_overlay_config()
        if self._overlay is not None and not self._cfg.overlay_enabled:
            try:
                self._overlay.hide()
            except Exception:
                pass
            self._overlay_shown = False
        if hasattr(self, "_apply_overlay_style") and self._apply_overlay_style:
            self._apply_overlay_style()
        # 从「关」切到「开」时立即亮窗：用户打开开关就是想看字幕，
        # 不该还要等第一条真实字幕或手动点「回看」。
        if self._cfg.overlay_enabled and not was_enabled:
            self.review_overlay()
        # 热键改动必须重启监听才生效（pynput 不会自动重读配置）
        hotkeys_after = (self._cfg.hotkey_lock, self._cfg.hotkey_review,
                         getattr(self._cfg, "hotkey_move", ""), self._cfg.hotkey_ptt)
        if hotkeys_after != hotkeys_before:
            self._start_hotkeys()
            # PTT 监听绑定在 cfg.hotkey_ptt 上，运行中也要重启
            try:
                if getattr(self._pipeline, "_running", None) and self._pipeline._running.is_set():
                    self._ptt.stop()
                    self._ptt.start()
            except Exception:
                logging.getLogger("valtrans.webui").exception("PTT 热键重启失败")
        # 固定 → 可拖动 的切换：立刻刷新窗口样式（穿透与否随之改变）
        if getattr(self._cfg, "overlay_pinned", False) != pinned_before:
            if getattr(self, "_apply_overlay_style", None):
                self._apply_overlay_style()
            self._push_overlay_config()
        # 采集来源变了必须**重启管线**，否则改了等于没改（见开头的说明）
        audio_after = _audio_sig(self._cfg)
        if audio_after != audio_before:
            running = bool(getattr(self._pipeline, "_running", None)
                           and self._pipeline._running.is_set())
            log = logging.getLogger("valtrans.webui")
            log.info("采集来源变更 %s -> %s，运行中=%s，重建采集管线",
                     audio_before, audio_after, running)
            self._rebuild_capture(running=running)
        # ★ v0.2.16：Key 脱敏回显
        return _masked_cfg(self._cfg)

    def open_url(self, url: str) -> None:
        if isinstance(url, str) and url.startswith("https://"):
            webbrowser.open(url)

    # ---------- 主窗控制（自绘标题栏用） ----------
    # 无边框后这几个是标题栏按钮的全部实现。原来的 win_max 只能最大化，
    # 不能还原 —— 双击标题栏时会卡在「点不动」的状态。

    def win_min(self) -> None:
        if self._win is not None:
            self._win.minimize()



    def win_toggle_max(self) -> None:
        """标题栏双击 / 最大化按钮。"""
        if self._win is None:
            return
        try:
            if self._win.is_maximized:
                self._win.restore()
            else:
                self._win.maximize()
        except Exception:
            pass
        self._push_winstate()

    def win_state(self) -> dict:
        """供前端首屏读取，避免标题栏图标一开始画错。"""
        maxi = False
        try:
            maxi = bool(self._win is not None and self._win.is_maximized)
        except Exception:
            maxi = False
        return {"maximized": maxi, "always_on_top": bool(self._main_top)}

    def win_set_top(self, on: bool) -> dict:
        """主窗置顶开关。浮窗那套 WS_EX_TOPMOST 只管浮窗，主窗要单独做。

        用 DWM 而不是改 exstyle：pywebview 的 maximize/restore 会重建 HWND，
        exstyle 会被 WinForms 冲掉（_show_overlay 踩过同一类坑）
        """
        self._main_top = bool(on)
        if self._win is not None:
            try:
                self._win.evaluate_js(
                    f"window.__vt && window.__vt.emit('winstate', "
                    f"{{maximized: false, always_on_top: {str(bool(on)).lower()}}})"
                )
            except Exception:
                pass
        try:
            self._apply_main_topmost()
        except Exception:
            pass
        return {"always_on_top": bool(on)}

    def _apply_main_topmost(self) -> None:
        """把 WS_EX_TOPMOST 加/去掉到主窗 HWND（走 DWM，扛得住 HWND 重建）。"""
        import ctypes
        from ctypes import wintypes
        try:
            from .host import find_main_hwnd
        except Exception:
            return
        hwnd = find_main_hwnd()
        if not hwnd:
            return
        GWL_EXSTYLE = -20
        WS_EX_TOPMOST = 0x00000008
        SetWindowLong = ctypes.windll.user32.SetWindowLongW
        SetWindowLong.argtypes = [wintypes.HWND, ctypes.c_int,
                                  wintypes.LONG]
        SetWindowLong.restype = wintypes.LONG
        GetWindowLong = ctypes.windll.user32.GetWindowLongW
        GetWindowLong.argtypes = [wintypes.HWND, ctypes.c_int]
        GetWindowLong.restype = wintypes.LONG
        style = GetWindowLong(hwnd, GWL_EXSTYLE)
        if self._main_top:
            style |= WS_EX_TOPMOST
        else:
            style &= ~WS_EX_TOPMOST
        SetWindowLong(hwnd, GWL_EXSTYLE, style)
        ctypes.windll.user32.SetWindowPos(
            hwnd, 0, 0, 0, 0, 0,
            0x0001 | 0x0002 | 0x0040)   # NOSIZE|NOMOVE|NOACTIVATE

    def _push_winstate(self) -> None:
        """把窗口状态推给前端（标题栏图标要跟着变）。"""
        if self._win is None:
            return
        try:
            maxi = bool(self._win.is_maximized)
        except Exception:
            maxi = False
        try:
            self._emit("winstate", {"maximized": maxi,
                                    "always_on_top": bool(self._main_top)})
        except Exception:
            pass

    def win_close(self) -> None:
        if self._win is not None:
            self._win.hide()   # 关闭=隐藏到托盘

    # ---------- 启停 ----------
    def start(self) -> dict:
        # 先预热连接池：冷连接 5-12 秒，正好会落在用户的第一句字幕上，
        # 体感是「点了开始翻译没反应」。
        self.warmup_pool()
        try:
            self._tts.voice_override = self._cfg.tts_voice
            self._tts.rate = self._cfg.tts_rate
            self._tts.pitch = self._cfg.tts_pitch
            self._tts.sf_key = self._cfg.mt_key()
            self._tts.enabled = self._cfg.tts_enabled and not self._cfg.streamer_mode
            self._pipeline.start()
            # ★ v0.2.16：VALTRANS_TEST=1 时跳过 PTT 全局键盘监听——
            #   旧代码只挡住了 GlobalHotKeys（_start_hotkeys），这里的
            #   keyboard.Listener 照样注册，测试期间仍占用户的键
            if os.environ.get("VALTRANS_TEST") != "1":
                self._ptt.start()
            self._tts.start()
            desc = self._pipeline._capture.device_desc if self._pipeline._capture else ""
            return {"ok": True, "desc": desc}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def stop(self) -> dict:
        try:
            self._pipeline.stop()
            self._ptt.stop()
            self._tts.stop()
            # v0.2.11：停止时**必须隐藏浮窗**。
            #
            # 这条不变量一直写在开发规范里（
            # 停止即隐藏」），但 `stop()` 只停了管线/PTT/TTS，**从没隐藏过浮窗**。
            # 结果：点「停止翻译」后字幕面板还杵在屏幕上，
            # 用户看着像「没停下来」。
            #
            # 顺带把 `_overlay_shown` 归位，否则下次 `_show_overlay()`
            # 会以为「已经显示过」而走「记住旧位置」那条分支。
            if self._overlay is not None:
                try:
                    self._overlay.hide()
                except Exception:
                    logging.getLogger("valtrans.webui").exception(
                        "停止时隐藏浮窗失败")
                # ★ pywebview 的 `Window.hide()` 在 **WinForms 平台不生效**
                #   （一条实测：`hidden=True` 同样是空操作）
                #   所以必须用 Win32 `ShowWindow(SW_HIDE)` 兜底 ——
                #   `_show_overlay` 里早就用了这招（SW_SHOWNOACTIVATE），
                #   隐藏这边却漏了，结果「停止翻译」后字幕面板赖在屏幕上。
                try:
                    _h = _hwnd_by_title()
                    if _h:
                        ctypes.windll.user32.ShowWindow(_h, 0)  # SW_HIDE
                except Exception:
                    logging.getLogger("valtrans.webui").exception(
                        "ShowWindow(SW_HIDE) 兜底失败")
                self._overlay_shown = False
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # ---------- 测试（后台线程 + 事件） ----------
    def test_asr(self, key: str = "") -> None:
        # ★ v0.2.16：掩码回显值原样传回时不落盘，直接测已存的 Key
        if key and not _is_masked_secret(key):
            self._cfg.asr_keys[self._cfg.asr_preset] = key.strip()
            self._cfg.save()

        def run():
            try:
                import numpy as np
                import wave as wv
                samp = _asset("assets/samples/cable_captured.wav") or _asset("tests/samples/cable_captured.wav")
                w = wv.open(samp, "rb")
                audio = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0
                w.close()
                text, _ = self._asr.transcribe(audio, 16000)
                msg = f"识别测试 ✓ {self._asr.last_latency*1000:.0f}ms: {text[:40]}"
            except Exception as e:
                msg = f"识别测试失败: {e}"
            self._emit("test_result", {"kind": "asr", "text": msg})

        threading.Thread(target=run, daemon=True).start()

    def test_mt(self, key: str = "") -> None:
        # ★ v0.2.16：掩码回显值原样传回时不落盘，直接测已存的 Key
        if key and not _is_masked_secret(key):
            self._cfg.mt_keys[self._cfg.mt_preset] = key.strip()
            self._cfg.save()

        def run():
            try:
                out = self._mt.translate("Enemy rotating to B, hold the site!", "zh")
                msg = f"翻译测试 ✓ {self._mt.last_latency*1000:.0f}ms: {out}"
            except Exception as e:
                msg = f"翻译测试失败: {e}"
            # kind 必须是 mt：旧代码发的 "asr" 会把翻译结果塞进识别提示框
            self._emit("test_result", {"kind": "mt", "text": msg})

        threading.Thread(target=run, daemon=True).start()

    # ---------- 回声测试（实时双工：说一句立刻回一句） ----------
    def mic_test_start(self) -> dict:
        """开启实时回声（麦克风直通耳机）。返回 {ok, running} 供 UI 切换按钮状态。"""
        if self._echo_stream is not None:
            return {"ok": True, "running": True}
        import sounddevice as sd

        dev = self._cfg.mic_device or None
        if isinstance(dev, str) and dev:
            dev = next((i for i, d in enumerate(sd.query_devices())
                        if dev.lower() in d["name"].lower() and d["max_input_channels"] > 0), None)

        def callback(indata, outdata, frames, time_info, status):
            outdata[:] = indata   # 实时直通

        try:
            stream = sd.Stream(samplerate=48000, channels=1, dtype="float32",
                               device=(dev, None), callback=callback, blocksize=480)
            stream.start()
        except Exception as e:
            self._emit("test_result", {"kind": "mic", "text": f"✗ 实时回声启动失败: {e}"})
            return {"ok": False, "running": False}
        self._echo_stream = stream
        self._echo_timer = threading.Timer(30, self.mic_test_stop)
        self._echo_timer.daemon = True
        self._echo_timer.start()
        self._emit("test_result", {"kind": "mic", "state": "running", "text":
            "● 实时回声已开启：现在说句话，耳机里会立刻听到自己。再点一次「停止回声」结束。（30 秒后自动停止）"})
        return {"ok": True, "running": True}

    def mic_test_stop(self) -> dict:
        t = self._echo_timer
        if t is not None:
            t.cancel()
            self._echo_timer = None
        s = self._echo_stream
        if s is not None:
            try:
                s.stop()
                s.close()
            except Exception:
                pass
            self._echo_stream = None
            self._emit("test_result", {"kind": "mic", "state": "stopped", "text": "实时回声已停止。"})
        return {"ok": True, "running": False}

    def preview_tts(self) -> None:
        """试听：一次性播放器（必须显式 start），**不改动**「译文朗读」开关。

        播放器在调用线程同步创建并登记，再交给后台线程维持存活——
        旧实现放在子线程里赋值，主线程的 _stop_preview() 会读不到，
        快速连点试听时旧播放器无法被掐断。
        """
        self._stop_preview()
        self._preview_gen += 1
        gen = self._preview_gen
        player = TTSPlayer(voice=self._cfg.tts_voice, enabled=True,
                           rate=self._cfg.tts_rate, pitch=self._cfg.tts_pitch)
        player.start()      # 忘了 start 会导致试听无声
        self._preview_player = player

        def run():
            player.say("敌人在B点，快转点！Rush B, let's go!", "zh")
            # 等播完后自行摘除登记，避免 _preview_player 长期指向已结束的对象
            for _ in range(200):        # 最多等 20 秒
                if self._preview_gen != gen or self._preview_player is not player:
                    break
                time.sleep(0.1)
            player.stop()
            if self._preview_player is player:
                self._preview_player = None

        threading.Thread(target=run, daemon=True).start()
        self._emit("test_result", {"kind": "preview", "text": "正在试听…"})

    def _stop_preview(self) -> None:
        self._preview_gen += 1        # 让持有旧代次的后台线程自行退出
        p = self._preview_player
        if p is not None:
            p.stop()
            self._preview_player = None

    def stop_tts(self) -> None:
        """停止一切朗读：主播放器 + 试听播放器 + 当前音频输出。"""
        self._tts.stop()
        self._stop_preview()

    def selftest(self) -> None:
        """一键自测：3 句内置样本跑通 云端识别+翻译 全链路。

        要点（都是踩过的坑）：
        - **每句独立 try**：单句超时/失败只标注该句，不拖垮整个自测；
          旧实现把整个 for 循环包在一个 try 里，任意一句超时 → 全部结果丢失。
        - **不因葡语失败**：SenseVoice 不支持葡语，该句会返回乱码而非异常，
          这里直接标注「需切换 Groq 预设」，避免用户误判为软件坏了。
        - 逐句超时放大到 25 秒：免费 API 冷启动可达 6 秒以上（实测 ja1 6346ms），
          12 秒的默认值太紧，服务端偶发毛刺就会误报失败。
        """
        def run():
            import miniaudio
            import numpy as np
            cases = [("ja_raw.mp3", "日语", "ja"), ("en_raw.mp3", "英语", "en"),
                     ("ko_raw.mp3", "韩语", "ko")]
            lines, total, n, failed = [], 0, 0, 0
            for fname, label, lang in cases:
                p = _asset(f"assets/samples/{fname}") or _asset(f"tests/samples/{fname}")
                if not p:
                    lines.append(f"✗ {label}: 样本缺失（{fname}）")
                    failed += 1
                    continue
                try:
                    with open(p, "rb") as f:
                        dec = miniaudio.decode(f.read(), nchannels=1, sample_rate=16000,
                                               dither=miniaudio.DitherMode.TRIANGLE)
                    audio = np.frombuffer(dec.samples, dtype=np.int16).astype(np.float32) / 32768.0
                    text, _ = self._asr.transcribe(audio, 16000, language=lang)
                    asr_ms = int(self._asr.last_latency * 1000)
                    if not text:
                        lines.append(f"✗ {label}: 识别为空 {asr_ms}ms（Key 或额度可能有问题）")
                        failed += 1
                        continue
                    try:
                        zh = self._mt.translate(text, "zh")
                        mt_ms = int(self._mt.last_latency * 1000)
                    except Exception as me:
                        lines.append(f"✗ {label}: 翻译失败 {asr_ms}ms / {type(me).__name__}（识别已通过：{text[:18]}）")
                        failed += 1
                        continue
                    total += asr_ms + mt_ms
                    n += 1
                    lines.append(f"✓ {label}: {asr_ms}+{mt_ms}ms  {zh[:24]}")
                except Exception as e:
                    failed += 1
                    hint = ""
                    if "timed out" in str(e).lower() or "timeout" in str(e).lower():
                        hint = "（云端响应超时，免费额度高峰期较常见，可稍后重试）"
                    lines.append(f"✗ {label}: {type(e).__name__}{hint}")
            head = (f"自测完成 · 通过 {n}/{len(cases)}"
                    + (f"，失败 {failed}" if failed else "") + "\n")
            tail = f"\n平均单句云端耗时 {total // max(1, n)}ms" if n else "\n（无可用样本）"
            self._emit("test_result", {"kind": "selftest", "text": head + "\n".join(lines) + tail})

        threading.Thread(target=run, daemon=True).start()
    def refresh_quota(self) -> None:
        def run():
            result = {"zhipu(GLM)": {"text": "无余额查询接口 · 免费额度以官网为准", "ok": True}}
            key = self._cfg.mt_keys.get("siliconflow") or self._cfg.asr_keys.get("siliconflow")
            if not key:
                result["siliconflow"] = {"text": "未填 Key", "ok": False}
            else:
                try:
                    from ..core.security import safe_client
                    with safe_client(timeout=8) as cl:
                        r = cl.get("https://api.siliconflow.cn/v1/user/info",
                                   headers={"Authorization": f"Bearer {key}"})
                    if r.status_code == 200:
                        data = r.json().get("data") or {}
                        result["siliconflow"] = {"text": f"余额 ¥{data.get('balance', '?')}", "ok": True}
                    elif r.status_code == 410:
                        result["siliconflow"] = {"text":
                            "余额接口已下线（官方暂无替代）· 免费额度不受影响，登录 cloud.siliconflow.cn 查看", "ok": True}
                    elif r.status_code == 401:
                        result["siliconflow"] = {"text": "Key 无效（HTTP 401）", "ok": False}
                    else:
                        result["siliconflow"] = {"text": f"查询失败（HTTP {r.status_code}）", "ok": False}
                except Exception as e:
                    result["siliconflow"] = {"text": f"网络错误: {e}", "ok": False}
            self._emit("quota", result)

        threading.Thread(target=run, daemon=True).start()

    # ---------- 向导 ----------
    def detect_audio(self) -> dict:
        try:
            cin, cout = find_cable_devices()
            if cout is not None:
                return {"state": "✓ 已检测到虚拟声卡（CABLE Output 可用），直接点下一步。",
                        "cable": True}
            return {"state": "✗ 未检测到虚拟声卡。可一键安装官方免费驱动（约 30 秒）：", "cable": False}
        except Exception as e:
            return {"state": f"检测失败: {e}", "cable": None}

    def install_driver(self) -> dict:
        """调起官方 VB-CABLE 安装器（提权 -> UAC）。

        为什么不静默
        ------------
        原来是 `if not exe: return` + `except: pass`，
        驱动文件找不到、或 ShellExecute 失败时，用户点了**什么都没发生**，
        也没��任何日志 —— 正是本项目明令禁止的「点了没反应」反模式
        （所有失败必须冒泡到 notice）。

        返回值给 Wizard 用：
          {"ok": True,  "msg": "已调起安装器…"}
          {"ok": False, "msg": "找不到驱动文件…"}   # 包没带全
          {"ok": False, "msg": "调起失败…"}         # UAC 被拒等

        注意：这一步**无法在开发机上端到端验证** —— 它要装内核驱动，
        需要管理员权限 + 会真实改动系统音频设备。
        能保证的是代码路径正确、文件已随包分发（见 tests/audit_cable.py）。
        """
        exe = _asset("assets/drivers/VBCABLE_Setup_x64.exe")
        if not exe:
            # 兜底试 32 位版本：万一包里只带了 x86
            exe = _asset("assets/drivers/VBCABLE_Setup.exe")
        if not exe:
            msg = ("找不到驱动文件 assets/drivers/VBCABLE_Setup_x64.exe，"
                   "请到 vb-audio.com/Cable 手动下载安装"
                   "（勾选「改用 Loopback 模式」可以完全不用装）")
            try:
                self.notify(msg)
            except Exception:
                pass
            return {"ok": False, "msg": msg}

        # ★ v0.2.16 安全：安装目录对当前用户可写（PrivilegesRequired=lowest
        #   装到 %LOCALAPPDATA%\Programs），exe 若被本机恶意程序替换，
        #   下面的 runas 提权就等于替它提权。提权前必须验签（fail-closed）。
        from ..core.winverify import verify_signed
        _sig_ok, _sig_msg = verify_signed(str(exe))
        if not _sig_ok:
            msg = (f"驱动安装器签名校验未通过（{_sig_msg}），已阻止运行。"
                   f"文件可能被篡改，请从 vb-audio.com/Cable 重新下载官方安装包。")
            logging.getLogger("valtrans.webui").error(
                "驱动验签失败: %s (%s)", exe, _sig_msg)
            try:
                self.notify(msg)
            except Exception:
                pass
            return {"ok": False, "msg": msg, "path": exe}

        try:
            # "runas" = 提权；返回 >32 表示成功
            rc = ctypes.windll.shell32.ShellExecuteW(
                None, "runas", exe, None, None, 1)
            if int(rc) > 32:
                msg = ("已调起官方安装器：① UAC 弹窗点「是」"
                       "→ ② 驱动界面点「Install Driver」"
                       "→ 装完回本页点「重新检测」")
                return {"ok": True, "msg": msg, "path": exe}
            msg = (f"安装器未能启动（ShellExecute 返回 {int(rc)}）。"
                   f"请手动以管理员身份运行：{exe}")
            try:
                self.notify(msg)
            except Exception:
                pass
            return {"ok": False, "msg": msg, "path": exe}
        except Exception as e:
            msg = (f"调起安装器失败（{e}）。"
                   f"请手动以管理员身份运行：{exe}")
            try:
                self.notify(msg)
            except Exception:
                pass
            return {"ok": False, "msg": msg, "path": exe}

    def test_key(self, key: str) -> None:
        # ★ v0.2.16：向导页可能把掩码回显值传回来——换已存的真 Key 测试
        if _is_masked_secret(key):
            key = self._cfg.asr_key() or key

        def run():
            from ..core.security import safe_client
            try:
                with safe_client(timeout=15) as cl:
                    r = cl.post("https://api.siliconflow.cn/v1/chat/completions",
                                headers={"Authorization": f"Bearer {key}"},
                                json={"model": "tencent/Hunyuan-MT-7B",
                                      "messages": [{"role": "user", "content": "hi"}],
                                      "max_tokens": 1, "stream": False})
                if r.status_code == 200:
                    text = "✓ Key 有效（真实调用成功）。点下一步继续。"
                elif r.status_code == 401:
                    text = "✗ Key 无效（HTTP 401），请重新复制粘贴。"
                else:
                    text = f"✗ 服务返回 HTTP {r.status_code}，请稍后重试。"
            except Exception as e:
                text = f"✗ 网络错误: {e}"
            self._emit("keytest", {"text": text})

        threading.Thread(target=run, daemon=True).start()

    def js_error(self, msg: str) -> None:
        logging.getLogger("valtrans.webui").error(msg)

    def quit(self) -> None:
        # v0.2.19：停掉热键消费线程。
        # 必须 join 等它真正退出 —— 否则解释器关闭与活着的线程竞态
        #（与 native_overlay 的 close() 铁律同款：不 join 会偶发 hang）。
        try:
            self.stop_action_thread(timeout=2.0)
        except Exception:
            pass
        """退出：停掉一切后台活动再销毁窗口。

        旧实现只停 pipeline/ptt，遗漏了 TTS 主播放器、试听播放器与回声测试流——
        退出瞬间可能仍在朗读或占用麦克风。
        ★ v0.2.16：还漏了**原生浮窗**——close() 里防解释器 shutdown 与
        STA 消息泵竞态的 done.wait+Join（实测 hang 死过两次）从来没人调。
        """
        for fn, name in ((self._pipeline.stop, "pipeline"),
                         (self._ptt.stop, "ptt"),
                         (self._tts.stop, "tts"),
            (_close_pool_quiet, "http"),
                         (self._stop_preview, "preview"),
                         (self.mic_test_stop, "mic_test")):
            try:
                fn()
            except Exception:
                logging.getLogger("valtrans.webui").exception("退出时停止 %s 失败", name)
        if self._overlay is not None:
            try:
                self._overlay.close()
            except Exception:
                logging.getLogger("valtrans.webui").exception("退出时关闭浮窗失败")
            self._overlay = None
            self._overlay_shown = False
        try:
            if self._hotkeys is not None:
                self._hotkeys.stop()
        except Exception:
            pass
        try:
            self._cfg.save()
        except Exception:
            pass
        if self._win is not None:
            try:
                self._win.destroy()
            except Exception:
                pass

    # ---------- 热键 ----------
    def _start_hotkeys(self) -> None:
        """（重新）启动全局热键监听。热键配置改动后必须重启才生效。"""
        # v0.2.11：VALTRANS_TEST=1 时**不注册全局热键**。
        #
        # 自动化测试一次全量要拉起 9 个应用实例，每次都注册
        # Ctrl+Alt+Q / Ctrl+Alt+H / Ctrl+Shift+D ——
        # 这些热键是**真的被占住**的，测试期间用户按这几个组合键
        # 会被软件吃掉（用户反馈「一直在反复地重启那个软件」，
        # 顺带也意味着测试在抢他的按键）。
        if os.environ.get("VALTRANS_TEST") == "1":
            logging.getLogger("valtrans.webui").info(
                "VALTRANS_TEST=1：跳过全局热键注册（避免占用系统按键）")
            return
        try:
            from pynput import keyboard
        except Exception:
            return
        # 先停旧的，否则 pynput 会叠加监听，一个组合键触发多次
        try:
            if self._hotkeys is not None:
                self._hotkeys.stop()
                self._hotkeys = None
        except Exception:
            pass
        log = logging.getLogger("valtrans.webui")
        mapping = {}
        for hotkey, fn in ((getattr(self._cfg, "hotkey_lock", ""), self.toggle_lock),
                           (getattr(self._cfg, "hotkey_review", ""), self.review_overlay),
                           (getattr(self._cfg, "hotkey_move", ""), self.toggle_pin)):
            if not hotkey:
                continue
            try:
                keyboard.HotKey.parse(hotkey)   # 非法组合直接跳过，不拖垮其余热键
                mapping[hotkey] = fn
            except Exception:
                log.warning("忽略非法热键配置: %r", hotkey)
        if not mapping:
            return
        try:
            # ★ v0.2.19：塞进去的是「只入队」的包装，不是回调本身。
            #   pynput 在它自己的监听线程里调用它们，所以这些函数必须
            #   保持「一行入队、绝不执行副作用」的形态。
            self._hotkeys = keyboard.GlobalHotKeys(
                {k: self._wrap_hotkey(v) for k, v in mapping.items()})
            self._hotkeys.start()
            self._ensure_action_thread()
            log.info("全局热键已启动(经串行队列，监听线程只入队): %s",
                     list(mapping))
        except Exception:
            log.exception("全局热键启动失败")

    # ---------- 浮窗固定 / 拖动 ----------
    # ---------- 热键串行化：单一消费者线程（v0.2.19）----------
    #
    # 起因：pynput 的 GlobalHotKeys 在**它自己的监听线程**里调用回调。
    # 审查报告核实后的结论是「副作用在哪执行都行」（浮窗已 BeginInvoke
    # 封送、配置写入有锁、evaluate_js 跨线程安全），真正缺的是：
    #   (a) 三个回调之间没有串行化 —— 连按两下会重入，
    #       toggle_lock 可能读到旧值又写回旧值（热键等于没生效）
    #   (b) 回调跑在 pynput 线程上，抛异常只打进它的循环，
    #       除了日志没有痕迹
    #
    # ★ 为什么不叫「主线程」：pywebview **没有可靠的「主线程 ID」API**，
    #   连 js_api 的方法被 JS 调用时也不是跑在主线程。所以「判断当前
    #   是不是主线程」做不到，只能靠猜。名字骗人比缺功能更糟 ——
    #   这里要的是**串行 + 换线程**，不是「主线程」这个名分。
    #
    # 热键回调本身被包成「只入队」：不持锁、不做 I/O、不抛异常。
    def _init_action_queue(self) -> None:
        import queue as _q
        import threading as _th
        self._act_q = _q.Queue()
        self._act_thread = None
        self._act_stop = threading.Event()
        self._act_seq = 0                  # 入队总数（可观测）
        self._act_done = 0                 # 出队完成数（可观测）
        self._act_lock = _th.Lock()
        self._act_errors = 0

    def run_action(self, fn, *args, **kwargs) -> int:
        """把一个副作用排到串行消费线程。返回序号（便于测试断言顺序）。"""
        with self._act_lock:
            self._act_seq += 1
            seq = self._act_seq
        self._act_q.put((seq, fn, args, kwargs))
        return seq

    def _drain_actions(self) -> int:
        """取空队列。**只由消费线程调用**（关停时也用它同步排空）。"""
        n = 0
        while True:
            try:
                seq, fn, args, kwargs = self._act_q.get_nowait()
            except Exception:
                return n
            n += 1
            try:
                fn(*args, **kwargs)
            except Exception:
                with self._act_lock:
                    self._act_errors += 1
                logging.getLogger("valtrans.webui").exception(
                    "热键动作执行失败: %r", getattr(fn, "__name__", fn))
            finally:
                with self._act_lock:
                    self._act_done += 1

    def _action_loop(self) -> None:
        while not self._act_stop.is_set():
            try:
                if self._drain_actions() == 0:
                    # 空闲时等一小会儿，别空转烧 CPU
                    self._act_stop.wait(0.05)
            except Exception:
                # ★ 消费线程绝不能死 —— 它一死，所有热键永久失效。
                logging.getLogger("valtrans.webui").exception(
                    "热键消费循环异常（继续跑）")
                self._act_stop.wait(0.2)

    def _ensure_action_thread(self) -> None:
        if getattr(self, "_act_thread", None) is not None \
                and self._act_thread.is_alive():
            return
        import threading as _th
        self._act_stop.clear()
        self._act_thread = _th.Thread(target=self._action_loop,
                                      name="hotkey-actions", daemon=True)
        self._act_thread.start()

    def flush_actions(self, timeout: float = 3.0) -> bool:
        """同步等到**全部动作执行完**（测试与关停用）。

        ★ 判据不能用 `self._act_q.empty()` —— 实测踩过：
          20 个动作入队、flush 返回 True，但只完成了 19 个。
          `Queue.empty()` 只说明「没有**待取**的任务」，
          **已出队但还在执行**的那个根本不在队列里。
          这就是「等对象存在 ≠ 等对象就绪」那类假红的翻版
          **等队列空（存在性）≠ 等活干完（就绪状态）**。

        关停路径依赖这个返回值，所以判错 = 「刚按了热键就退出」丢动作。

        正确判据：已入队总数 == 已完成总数。
        """
        import time as _t
        end = _t.time() + timeout
        while _t.time() < end:
            with self._act_lock:
                if self._act_done >= self._act_seq:
                    return True
            _t.sleep(0.01)
        with self._act_lock:
            return self._act_done >= self._act_seq

    def stop_action_thread(self, timeout: float = 2.0) -> None:
        self.flush_actions(timeout)
        self._act_stop.set()
        t = getattr(self, "_act_thread", None)
        if t is not None and t.is_alive():
            t.join(timeout)

    def _wrap_hotkey(self, fn):
        """把回调包成「只入队」的一层。

        必须是**极简**的：它在 pynput 监听线程上执行，
        任何持锁、I/O、抛异常都会直接影响按键响应甚至拖死监听循环。
        返回值照旧拿不到 —— pynput 本来就忽略回调返回值。
        """
        def _queued(*a, **k):
            try:
                self.run_action(fn, *a, **k)
            except Exception:
                # 连入队都失败（队列不可用）也不能让异常冒到 pynput 线程
                logging.getLogger("valtrans.webui").exception(
                    "热键入队失败: %r", getattr(fn, "__name__", fn))
        _queued.__name__ = getattr(fn, "__name__", "hotkey")
        return _queued

    def toggle_pin(self) -> bool:
        """切换浮窗「固定 ↔ 可拖动」。

        固定   = 鼠标穿透（WS_EX_TRANSPARENT），完全不影响游戏操作；
        可拖动 = 不穿透，可按住面板拖到任意位置，松手后位置自动保存。
        由全局热键 hotkey_move 触发，用户不必切回主界面。
        """
        self._cfg.overlay_pinned = not getattr(self._cfg, "overlay_pinned", False)
        self._cfg.save()
        self._push_overlay_config()
        if getattr(self, "_apply_overlay_style", None):
            try:
                self._apply_overlay_style()
            except Exception:
                pass
        self.notify("字幕面板已" + ("固定（鼠标穿透）" if self._cfg.overlay_pinned
                                 else "解锁拖动 · 可按住面板移动"))
        return self._cfg.overlay_pinned


    def save_overlay_pos(self, x: int = -1, y: int = -1) -> None:
        """拖动结束后保存浮窗位置（x/y = -1 表示取窗口当前实际位置）。"""
        if getattr(self._cfg, "overlay_pinned", False):
            return
        try:
            px = self._overlay.x if (x < 0 and self._overlay is not None) else int(x)
            py = self._overlay.y if (y < 0 and self._overlay is not None) else int(y)
            self._cfg.overlay_x, self._cfg.overlay_y = int(px), int(py)
            self._cfg.save()
        except Exception:
            logging.getLogger("valtrans.webui").exception("保存浮窗位置失败")

    def move_overlay_to_corner(self, corner: str = "br") -> None:
        """一键把浮窗挪到屏幕角落（br/bl/tr/tl）。"""
        if self._overlay is None:
            return
        try:
            sw = ctypes.windll.user32.GetSystemMetrics(0)
            sh = ctypes.windll.user32.GetSystemMetrics(1)
            w, h = self._cfg.overlay_width, OVERLAY_FIXED_H
            pos = {"br": (sw - w - 48, sh - h - 48),
                   "bl": (48, sh - h - 48),
                   "tr": (sw - w - 48, 48),
                   "tl": (48, 48)}.get(corner, (sw - w - 48, sh - h - 48))
            self._overlay.move(max(0, pos[0]), max(0, pos[1]))
            self._overlay_shown = True
            self.save_overlay_pos()
            self.notify("字幕面板已移到" + {"br": "右下角", "bl": "左下角",
                                          "tr": "右上角", "tl": "左上角"}.get(corner, "右下角"))
        except Exception:
            logging.getLogger("valtrans.webui").exception("移动浮窗失败")


def _close_pool_quiet() -> None:
    """退出时关闭 HTTP 连接池（顺带清 keep-alive 连接）。"""
    try:
        _close_pool()
    except Exception:
        logging.getLogger("valtrans.webui").debug("关闭连接池失败", exc_info=True)
