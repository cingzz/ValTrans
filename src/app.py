# -*- coding: utf-8 -*-
# 作者: cing  ·  https://github.com/cingzz
# 许可: GPL-3.0 + 商业授权（闭源/商用需向作者申请授权），见 LICENSE 与 LICENSE-COMMERCIAL.md
#
"""应用装配：主窗口 + 浮窗 + 托盘 + 热键 + 管线 + PTT 全部接线。"""
from __future__ import annotations

import logging
import sys
import threading
import traceback

from PySide6.QtCore import Qt, QTimer, Signal, QObject
from PySide6.QtGui import QIcon, QAction, QPainter, QColor, QPixmap, QFont
from PySide6.QtWidgets import QApplication, QSystemTrayIcon, QMenu

from .core.config import AppConfig, LOG_DIR
from .core.pipeline import Pipeline, SubtitleEvent
from .services.engine import CloudASR, Translator
from .services.tts import TTSPlayer
from .services.reverse_ptt import ReversePTT
from .ui import theme
from .ui.shell import MainWindow
from .ui.pages import HomePage, LivePage, QuotaPage, StylesPage, SettingsPage, HelpPage, AboutPage
from .ui.overlay import SubtitleOverlay
from .ui.wizard import Wizard
from .version import VERSION  # 版本唯一来源：src/version.py


class QtBridge(QObject):
    """后台线程 -> Qt 主线程信号桥。"""
    subtitle = Signal(object)
    status = Signal(str)
    ptt = Signal(str)
    ptt_result = Signal(str, str)
    call = Signal(object)      # 任意闭包投递到主线程执行（工作线程更新 UI 的唯一通道）


def make_icon() -> QIcon:
    """程序图标。

    v0.2.21：不再自己画。原实现是「绿底白 V」的手绘 QPainter 版本，
    与 assets/icon.ico、托盘图标三份各画各的，用户看到的图标对不上。
    现在统一走 ``src/uiweb/app_icon.py`` 这一份绘制实现 ——
    Qt 兜底界面、Web 界面托盘、EXE 资源三处必然一致。

    注意：``app_icon`` 在 ``src/uiweb/`` 下，但**不 import 任何 WebView2
    相关的东西**，所以 Qt 兜底路径引它是安全的（不会把 WebView2 拖进来）。
    """
    import io as _io

    from PySide6.QtGui import QImage

    from .uiweb.app_icon import render

    data = _io.BytesIO()
    render(256).save(data, format="PNG")
    data.seek(0)
    qimg = QImage()
    qimg.loadFromData(data.read(), "PNG")
    return QIcon(QPixmap.fromImage(qimg))


class App:
    def __init__(self, argv):
        self.qapp = QApplication(argv)
        self.qapp.setApplicationName("ValTrans")
        self.qapp.setWindowIcon(make_icon())
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        logging.basicConfig(
            filename=str(LOG_DIR / "valtrans.log"),
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(name)s: %(message)s",
            encoding="utf-8")

        self.cfg = AppConfig.load()
        self.bridge = QtBridge()
        self.bridge.subtitle.connect(self._on_subtitle_ui)
        self.bridge.status.connect(self._on_status_ui)
        self.bridge.ptt.connect(self._on_ptt_ui)
        self.bridge.ptt_result.connect(self._on_ptt_result_ui)
        self.bridge.call.connect(lambda fn: fn())

        # 引擎与管线
        self.asr = CloudASR(self.cfg)
        self.mt = Translator(self.cfg)
        self.tts = TTSPlayer(voice=self.cfg.tts_voice, enabled=self.cfg.tts_enabled and not self.cfg.streamer_mode,
                             rate=self.cfg.tts_rate, pitch=self.cfg.tts_pitch)
        self.pipeline = Pipeline(self.cfg, on_subtitle=self.bridge.subtitle.emit,
                                 on_status=self.bridge.status.emit)
        # TTS 播放期间暂停采集识别：防止 loopback 模式把自己朗读的声音再识别（回声死循环）
        self.pipeline.external_gate = self.tts.playing
        self.ptt = ReversePTT(self.cfg, self.asr, self.mt,
                              on_result=self.bridge.ptt_result.emit,
                              on_state=self.bridge.ptt.emit)

        # UI
        self.win = MainWindow()
        self.page_home = HomePage(self.cfg)
        self.page_live = LivePage(self.cfg)
        self.page_quota = QuotaPage(self.cfg)
        self.page_styles = StylesPage(self.cfg)
        self.page_settings = SettingsPage(self.cfg)
        self.page_help = HelpPage(self.cfg)
        self.page_about = AboutPage(self.cfg, VERSION)
        for k, p in [("home", self.page_home), ("live", self.page_live),
                     ("quota", self.page_quota), ("styles", self.page_styles),
                     ("settings", self.page_settings), ("help", self.page_help),
                     ("about", self.page_about)]:
            self.win.register(k, p)
        self.win.goto("home")

        self.overlay = SubtitleOverlay(self.cfg)

        # 信号接线
        self.page_home.start_stop_clicked.connect(self.toggle_pipeline)
        self.page_home.toggle_changed.connect(self._on_toggle)
        self.page_styles.applied.connect(self._apply_overlay_cfg)
        self.page_settings.test_asr_clicked.connect(self._test_asr)
        self.page_settings.test_mt_clicked.connect(self._test_mt)
        self.page_settings.mic_test_clicked.connect(self._test_mic)
        self.page_settings.tts_preview_clicked.connect(self._tts_preview)
        self.page_settings.selftest_clicked.connect(self._selftest)
        self.page_settings.settings_saved.connect(self._on_settings_saved)
        self.page_quota.refresh_clicked.connect(self._refresh_quota)

        # 托盘
        self.tray = QSystemTrayIcon(make_icon())
        menu = QMenu()
        act_show = QAction("显示主窗口", menu)
        act_show.triggered.connect(self.win.showNormal)
        act_toggle = QAction("开始/停止翻译", menu)
        act_toggle.triggered.connect(self.toggle_pipeline)
        act_lock = QAction("锁定/解锁浮窗", menu)
        act_lock.triggered.connect(self.toggle_lock)
        act_wizard = QAction("重新运行初始化向导", menu)
        act_wizard.triggered.connect(self.rerun_wizard)
        act_quit = QAction("退出", menu)
        act_quit.triggered.connect(self.quit)
        for a in (act_show, act_toggle, act_lock, act_wizard):
            menu.addAction(a)
        menu.addSeparator()
        menu.addAction(act_quit)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(
            lambda r: self.win.showNormal() if r == QSystemTrayIcon.Trigger else None)
        self.tray.setToolTip("ValTrans · 瓦罗兰特实时语音翻译")

        # 全局热键（锁定/回看）
        self.hotkeys = None
        self._start_hotkeys()

        # 电平表定时器
        self._level_timer = QTimer()
        self._level_timer.timeout.connect(self._tick_level)
        self._level_timer.start(120)

    # ---------- 热键 ----------
    def _start_hotkeys(self):
        from pynput import keyboard
        mapping = {}
        try:
            mapping[self.cfg.hotkey_lock] = self.toggle_lock
        except Exception:
            pass
        try:
            mapping[self.cfg.hotkey_review] = self.overlay.review_history
        except Exception:
            pass
        if not mapping:
            return
        self.hotkeys = keyboard.GlobalHotKeys(mapping)
        self.hotkeys.start()

    def toggle_lock(self):
        self.overlay.set_locked(not self.cfg.overlay_locked)
        self.cfg.save()

    def rerun_wizard(self):
        from .ui.wizard import Wizard
        wz = Wizard(self.cfg)
        if wz.exec():
            self._apply_overlay_cfg()
            self.tts.enabled = self.cfg.tts_enabled and not self.cfg.streamer_mode

    def _on_toggle(self, key, val):
        if key == "tts_enabled":
            self.tts.enabled = val and not self.cfg.streamer_mode
        if key == "show_original":
            self.overlay.apply_config()
        if key == "streamer_mode":
            self.tts.enabled = self.cfg.tts_enabled and not val

    def _apply_overlay_cfg(self):
        self.overlay.apply_config()
        self.overlay.setVisible(bool(getattr(self.cfg, "overlay_enabled", True)))

    def _on_settings_saved(self):
        """设置页保存后：同步 TTS 参数、刷新主页采集模式提示、应用字幕开关。"""
        self.tts.voice_override = self.cfg.tts_voice
        self.tts.rate = self.cfg.tts_rate
        self.tts.pitch = self.cfg.tts_pitch
        self.page_home.update_mode_hint()
        self._apply_overlay_cfg()

    # ---------- 管线控制 ----------
    def toggle_pipeline(self):
        if self.pipeline._running.is_set():
            self.pipeline.stop()
            self.ptt.stop()
            self.page_home.set_running(False)
            self.win.set_status_text("未启动", theme.MUTED)
            self.tray.setToolTip("ValTrans · 已停止")
        else:
            try:
                self.pipeline.start()
                self.ptt.start()
                self.tts.voice_override = self.cfg.tts_voice
                self.tts.rate = self.cfg.tts_rate
                self.tts.pitch = self.cfg.tts_pitch
                self.tts.start()
                self.page_home.set_running(True, self.pipeline._capture.device_desc if self.pipeline._capture else "")
                self.win.set_status_text("监听中", theme.OK)
                self.tray.setToolTip("ValTrans · 监听中")
            except Exception as e:
                self.page_home.set_pipeline_status(f"启动失败: {e}")
                self.win.set_status_text("启动失败", theme.DANGER)

    # ---------- 回调（主线程） ----------
    def _on_subtitle_ui(self, ev: SubtitleEvent):
        self.page_live.add_subtitle(ev.original, ev.translated, ev.latency_ms,
                                    ev.fallback, getattr(ev, "error", ""))
        self.page_home.set_latency(ev.latency_ms)
        if getattr(self.cfg, "overlay_enabled", True):
            self.overlay.show_subtitle(ev.original, ev.translated,
                                       speaker="队友")
        if ev.translated and self.tts.enabled:
            self.tts.say(ev.translated, "zh")

    def _on_status_ui(self, s: str):
        self.page_home.set_pipeline_status(s)
        base = s.split(":")[0]
        color = theme.WARN if base == "recognizing" else theme.ACCENT
        self.win.set_status_text({"listening": "监听中", "recognizing": "识别中",
                                  "stopped": "已停止"}.get(base, s), color)

    def _on_ptt_ui(self, s: str):
        self.page_live.set_ptt(s)

    def _on_ptt_result_ui(self, translated, original):
        self.page_live.set_ptt("ready")
        self.page_live.add_subtitle(original + "（我）", translated, 0, False)
        if getattr(self.cfg, "overlay_enabled", True):
            self.overlay.show_subtitle(original, translated, speaker="我")
        self.tray.showMessage("ValTrans", "译文已复制：\n" + translated[:80],
                              QSystemTrayIcon.Information, 2000)

    # ---------- 周期 ----------
    def _tick_level(self):
        # 用最近一段缓存的块估算电平（简化：读取 pipeline 内最后块）
        lvl = getattr(self.pipeline, "last_rms", 0.0)
        self.page_live.set_level(lvl)

    # ---------- 测试动作 ----------
    def _test_asr(self):
        self.page_settings._save()
        self.page_settings.asr_hint.setText("识别测试中…（后台执行，不卡界面）")

        def run():
            import numpy as np, wave as wv, os
            samp = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                                "tests", "samples", "cable_captured.wav")
            try:
                w = wv.open(samp, "rb")
                audio = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0
                w.close()
                text, _ = self.asr.transcribe(audio, 16000)
                msg = f"识别测试 ✓ {self.asr.last_latency*1000:.0f}ms: {text[:40]}"
            except Exception as e:
                msg = f"识别测试失败: {e}"
            self.bridge.call.emit(lambda: self.page_settings.asr_hint.setText(msg))

        threading.Thread(target=run, daemon=True).start()

    def _test_mt(self):
        self.page_settings._save()
        self.page_settings.asr_hint.setText("翻译测试中…（后台执行，不卡界面）")

        def run():
            try:
                out = self.mt.translate("Enemy rotating to B, hold the site!", "zh")
                msg = f"翻译测试 ✓ {self.mt.last_latency*1000:.0f}ms: {out}"
            except Exception as e:
                msg = f"翻译测试失败: {e}"
            self.bridge.call.emit(lambda: self.page_settings.asr_hint.setText(msg))

        threading.Thread(target=run, daemon=True).start()

    def _test_mic(self):
        """回声测试：录音 2.5s → 外放回放。用户能亲耳听到自己 = 麦克风正常。"""
        self.page_settings._save()
        dev = self.page_settings.mic.currentData() or None
        hint = self.page_settings.mic_hint
        btn = self.page_settings.btn_mic_test
        btn.setEnabled(False)
        hint.setText("● 录音中 2.5 秒，请对着麦克风说话…")

        def run():
            import numpy as np, sounddevice as sd
            try:
                rec = sd.rec(int(16000 * 2.5), samplerate=16000, channels=1,
                             dtype="float32", device=dev)
                sd.wait()
                rms = float(np.sqrt(np.mean(rec ** 2)))
                if rms < 0.005:
                    self.bridge.call.emit(lambda: (
                        hint.setText(f"✗ 几乎没采到声音（电平 {rms:.3f}）。"
                                     "请检查麦克风选择、系统输入音量、Windows 隐私-麦克风权限。"),
                        btn.setEnabled(True)))
                    return
                self.bridge.call.emit(lambda: hint.setText(
                    f"● 录到 {rms:.3f} 电平 → 正在回放，你应该能听到自己的声音…"))
                sd.play(rec, 16000)
                sd.wait()
                self.bridge.call.emit(lambda: (
                    hint.setText(f"✓ 回声测试完成（电平 {rms:.3f}）。刚才能听到自己 = 麦克风正常。"),
                    btn.setEnabled(True)))
            except Exception as e:
                self.bridge.call.emit(lambda: (hint.setText(f"✗ 测试失败: {e}"), btn.setEnabled(True)))

        threading.Thread(target=run, daemon=True).start()

    def _tts_preview(self):
        self.page_settings._save()
        self.tts.voice_override = self.cfg.tts_voice
        self.tts.enabled = True
        self.tts.rate = self.cfg.tts_rate
        self.tts.pitch = self.cfg.tts_pitch
        self.tts.start()
        self.tts.say("敌人在B点，快转点！Rush B, let's go!", "zh")

    def _selftest(self):
        self.page_settings._save()
        self.page_settings.btn_selftest.setEnabled(False)
        self.page_settings.selftest_state.setText("自测运行中…（识别+翻译内置样本）")

        def run():
            try:
                import numpy as np
                import miniaudio
                samp = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                    "tests", "samples")
                cases = [("ja_raw.mp3", "日语"), ("en_raw.mp3", "英语"), ("pt_raw.mp3", "葡语")]
                lines = []
                total_ms = 0
                for fname, label in cases:
                    p = os.path.join(samp, fname)
                    if not os.path.exists(p):
                        continue
                    with open(p, "rb") as f:
                        dec = miniaudio.decode(f.read(), nchannels=1, sample_rate=16000,
                                               dither=miniaudio.DitherMode.TRIANGLE)
                    audio = np.frombuffer(dec.samples, dtype=np.int16).astype(np.float32) / 32768.0
                    text, _ = self.asr.transcribe(audio, 16000)
                    asr_ms = int(self.asr.last_latency * 1000)
                    zh = self.mt.translate(text, "zh") if text else "(识别为空)"
                    mt_ms = int(self.mt.last_latency * 1000)
                    total_ms += asr_ms + mt_ms
                    lines.append(f"{label}: {asr_ms}+{mt_ms}ms  {zh[:24]}")
                self.page_settings.selftest_state.setText(
                    "自测完成 ✓\n" + "\n".join(lines) +
                    f"\n平均单句云端耗时 {total_ms // max(1, len(lines))}ms（不含本地链路 <50ms）")
            except Exception as e:
                self.page_settings.selftest_state.setText(f"自测失败：{e}\n请先在上方填好有效 Key 并点「测试」。")
            finally:
                self.page_settings.btn_selftest.setEnabled(True)
        threading.Thread(target=run, daemon=True).start()

    def _refresh_quota(self):
        self.page_settings._save()
        # 网络请求全部放后台线程，结果经信号桥回主线程（不再卡界面）
        self.page_quota.set_quota("zhipu(GLM)", "无余额查询接口 · 免费额度以官网为准", True)
        key = self.cfg.mt_keys.get("siliconflow") or self.cfg.asr_keys.get("siliconflow")
        if not key:
            self.page_quota.set_quota("siliconflow", "未填 Key", False)
            return
        self.page_quota.set_quota("siliconflow", "查询中…", True)

        def run():
            try:
                from .core.security import safe_client
                with safe_client(timeout=8) as cl:
                    r = cl.get("https://api.siliconflow.cn/v1/user/info",
                               headers={"Authorization": f"Bearer {key}"})
                if r.status_code == 200:
                    data = r.json().get("data") or {}   # data 可能为 null，防 NoneType 崩溃
                    text, ok = f"余额 ¥{data.get('balance', '?')}", True
                elif r.status_code == 410:
                    text, ok = ("余额接口已下线（官方暂无替代）· 免费额度不受影响，"
                                "登录 cloud.siliconflow.cn 控制台查看"), True
                elif r.status_code == 401:
                    text, ok = "Key 无效（HTTP 401）", False
                else:
                    text, ok = f"查询失败（HTTP {r.status_code}）", False
            except Exception as e:
                text, ok = f"网络错误: {e}", False
            self.bridge.call.emit(lambda: self.page_quota.set_quota("siliconflow", text, ok))

        threading.Thread(target=run, daemon=True).start()

    # ---------- 运行 ----------
    def run(self) -> int:
        self.tray.show()
        if not self.cfg.first_run_done or not self.cfg.disclaimer_accepted:
            wz = Wizard(self.cfg)
            wz.exec()
        else:
            self.win.show()
        if getattr(self.cfg, "overlay_enabled", True):
            self.overlay.show()
        return self.qapp.exec()

    def quit(self):
        try:
            self.pipeline.stop()
            self.ptt.stop()
            if self.hotkeys:
                self.hotkeys.stop()
            self.cfg.save()
        finally:
            self.qapp.quit()
