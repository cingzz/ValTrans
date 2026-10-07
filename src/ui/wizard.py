# -*- coding: utf-8 -*-
# 作者: cing  ·  https://github.com/cingzz
# 许可: GPL-3.0 + 商业授权（闭源/商用需向作者申请授权），见 LICENSE 与 LICENSE-COMMERCIAL.md
#
"""首次运行向导：免责声明 -> 音频配置自检 -> API Key -> 游戏设置提示。"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
                               QCheckBox, QStackedWidget, QLineEdit, QComboBox, QFrame,
                               QWidget)

from . import theme
from ..core.config import ASR_PRESETS


class Wizard(QDialog):
    def __init__(self, cfg, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.setWindowTitle("ValTrans 初始化向导")
        self.setFixedSize(560, 430)
        self.setStyleSheet(theme.QSS + "QDialog{background:%s;}" % theme.BG0)
        self.setWindowFlags(Qt.Dialog | Qt.WindowStaysOnTopHint)

        v = QVBoxLayout(self)
        v.setContentsMargins(24, 20, 24, 20)
        self.stack = QStackedWidget()
        v.addWidget(self.stack, 1)
        nav = QHBoxLayout()
        self.back_btn = QPushButton("上一步")
        self.next_btn = QPushButton("下一步")
        self.next_btn.setObjectName("Primary")
        nav.addStretch(1)
        nav.addWidget(self.back_btn)
        nav.addWidget(self.next_btn)
        v.addLayout(nav)

        self.back_btn.clicked.connect(self._back)
        self.next_btn.clicked.connect(self._next)

        # ---- 第1步：欢迎+免责 ----
        w1 = QWidget()
        v1 = QVBoxLayout(w1)
        t1 = QLabel("欢迎使用 ValTrans")
        t1.setObjectName("H1")
        v1.addWidget(t1)
        d = QLabel("把队友的外语语音实时变成中文字幕，并把你说的话翻译成外语发给队友。\n\n"
                   "开始前请阅读并同意以下声明：")
        d.setWordWrap(True)
        v1.addWidget(d)
        dc = QFrame()
        dc.setObjectName("CardInner")
        dv = QVBoxLayout(dc)
        dd = QLabel("1. 本软件与 Riot Games /《无畏契约》官方无关；\n"
                    "2. 仅读取系统音频，不注入游戏、不读内存；\n"
                    "3. 使用第三方软件存在理论封号风险，请自行评估承担；\n"
                    "4. 云端识别/翻译使用你自己注册的 API 服务，费用与额度以服务商为准。")
        dd.setWordWrap(True)
        dd.setStyleSheet("font-size:12px; color:%s;" % theme.MUTED)
        dv.addWidget(dd)
        v1.addWidget(dc)
        self.chk_agree = QCheckBox("我已阅读并同意上述声明")
        v1.addWidget(self.chk_agree)
        v1.addStretch(1)
        self.stack.addWidget(w1)

        # ---- 第2步：音频一键配置 ----
        w2 = QWidget()
        v2 = QVBoxLayout(w2)
        self.v2 = v2
        t2 = QLabel("音频一键配置")
        t2.setObjectName("H1")
        v2.addWidget(t2)
        self.audio_state = QLabel("正在检测虚拟声卡…")
        self.audio_state.setWordWrap(True)
        v2.addWidget(self.audio_state)
        self.btn_install_driver = QPushButton("🔧 一键安装虚拟声卡（官方 VB-CABLE 驱动）")
        self.btn_install_driver.setObjectName("Primary")
        self.btn_install_driver.clicked.connect(self._install_driver)
        self.btn_install_driver.setVisible(False)
        v2.addWidget(self.btn_install_driver)
        self.driver_state = QLabel("")
        self.driver_state.setObjectName("Muted")
        self.driver_state.setWordWrap(True)
        v2.addWidget(self.driver_state)
        steps = QLabel("装好驱动后你只需要做一件事：\n"
                       "  游戏内 设置→音频→「语音聊天输出设备」选 CABLE Input\n\n"
                       "其余全部自动完成：本软件会自动采集队友人声，并自动把声音回放到你的耳机"
                       "（软件级监听，无需在 Windows 声音面板手动设置侦听，不会有回声）。")
        steps.setObjectName("Muted")
        steps.setWordWrap(True)
        v2.addWidget(steps)
        self.chk_skip_audio = QCheckBox("改用 Loopback 模式（不装/不用虚拟声卡，会混入游戏音，准确率下降）")
        v2.addWidget(self.chk_skip_audio)
        v2.addStretch(1)
        self.stack.addWidget(w2)

        # ---- 第3步：API Key ----
        w3 = QWidget()
        v3 = QVBoxLayout(w3)
        t3 = QLabel("云端服务配置（只需粘贴一个 Key）")
        t3.setObjectName("H1")
        v3.addWidget(t3)
        expl = QLabel(
            "为什么需要 Key？本软件的商业模式与同类软件不同：\n"
            "  · 同类软件：向官方付费（¥5/2小时起），直接用他们调好的云端模型，用户不配置；\n"
            "  · 本软件：不收费、无账号体系——识别和翻译直接调用「你自己注册」的免费云端模型，\n"
            "    所以需要一次性的 Key 配置（之后永久有效，不用再管）。")
        expl.setWordWrap(True)
        v3.addWidget(expl)
        models = QLabel(
            "调用的是谁的模型？能力怎么样？\n"
            "  · 语音识别：SenseVoice（阿里巴巴开源）——中文/日语/韩语/英语/粤语，"
            "CJK 准确率业界第一梯队，专为短语音优化；\n"
            "  · 翻译：Hunyuan-MT-7B（腾讯开源）——WMT2025 国际翻译大赛 31 个语言对中 30 个第一；\n"
            "  · 免费额度对个人游戏使用完全够用（约数百小时/月）。\n"
            "  · 需要葡语（巴西服）等语言时，可在设置页把识别切换为 Groq whisper-large-v3。")
        models.setWordWrap(True)
        models.setObjectName("Muted")
        v3.addWidget(models)
        brow = QHBoxLayout()
        b1 = QPushButton("① 打开注册页面")
        b1.clicked.connect(lambda: self._open_url("https://cloud.siliconflow.cn/account/register"))
        b2 = QPushButton("② 打开密钥页面")
        b2.clicked.connect(lambda: self._open_url("https://cloud.siliconflow.cn/account/ak"))
        brow.addWidget(b1); brow.addWidget(b2); brow.addStretch(1)
        v3.addLayout(brow)
        krow = QHBoxLayout()
        krow.addWidget(QLabel("API Key"))
        self.key_asr = QLineEdit()
        self.key_asr.setPlaceholderText("粘贴 sk- 开头的密钥（识别+翻译共用）")
        krow.addWidget(self.key_asr, 1)
        self.btn_key_test = QPushButton("测试")
        self.btn_key_test.clicked.connect(self._test_key)
        krow.addWidget(self.btn_key_test)
        v3.addLayout(krow)
        self.key_state = QLabel("")
        self.key_state.setObjectName("Muted")
        v3.addWidget(self.key_state)
        v3.addStretch(1)
        self.stack.addWidget(w3)

        # ---- 第4步：完成 ----
        w4 = QWidget()
        v4 = QVBoxLayout(w4)
        t4 = QLabel("最后一步")
        t4.setObjectName("H1")
        v4.addWidget(t4)
        fin = QLabel("游戏内把显示模式改为「无边框窗口」\n"
                     "（设置→视频→显示模式），否则浮窗会被游戏盖住。\n\n"
                     "点击完成后，在主页按「开始翻译」即可。祝把把超神！")
        fin.setWordWrap(True)
        v4.addWidget(fin)
        v4.addStretch(1)
        self.stack.addWidget(w4)

        self._idx = 0
        self.stack.setCurrentIndex(0)
        self._sync_btns()

    # ---- 音频检测（进入第2步时执行） ----
    def detect_audio(self):
        from ..core.audio_capture import find_cable_devices
        try:
            cin, cout = find_cable_devices()
            if cout is not None:
                self.audio_state.setText("✓ 已检测到虚拟声卡（CABLE Output 可用），无需安装，直接点下一步。")
                self.btn_install_driver.setVisible(False)
                self.driver_state.setText("")
                self.chk_skip_audio.setChecked(False)
            else:
                self.audio_state.setText("✗ 未检测到虚拟声卡。点击下方按钮一键安装官方免费驱动（约 30 秒）：")
                self.btn_install_driver.setVisible(True)
        except Exception as e:
            self.audio_state.setText(f"检测失败: {e}")

    # ---- 一键安装 VB-CABLE 驱动（调起官方安装器，需用户在 UAC/驱动界面各点一次确认） ----
    def _install_driver(self):
        import os
        import ctypes
        exe = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__)))), "assets", "drivers", "VBCABLE_Setup_x64.exe")
        if not os.path.exists(exe):
            # 打包后路径（_internal/assets/drivers）
            base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            exe = os.path.join(base, "_internal", "assets", "drivers", "VBCABLE_Setup_x64.exe")
        if not os.path.exists(exe):
            self.driver_state.setText("找不到驱动文件，请到 vb-audio.com/Cable 手动下载安装。")
            return
        # ★ v0.2.16 安全：提权运行前必须验签（安装目录用户可写，防替换提权）
        from ...core.winverify import verify_signed
        _sig_ok, _sig_msg = verify_signed(exe)
        if not _sig_ok:
            self.driver_state.setText(
                f"驱动安装器签名校验未通过（{_sig_msg}），已阻止运行。"
                "请从 vb-audio.com/Cable 重新下载官方安装包。")
            return
        self.driver_state.setText("已调起官方安装器：① UAC 弹窗点「是」→ ② 驱动界面点「Install Driver」→ 完成后回来点「重新检测」。")
        try:
            ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, None, None, 1)
        except Exception as e:
            self.driver_state.setText(f"调起失败（{e}），请手动以管理员身份运行 {exe}")
            return
        if not hasattr(self, "btn_redetect"):
            self.btn_redetect = QPushButton("🔄 重新检测")
            self.btn_redetect.clicked.connect(self.detect_audio)
            self.v2.addWidget(self.btn_redetect)
        else:
            self.btn_redetect.setVisible(True)

    # ---- 打开网页 ----
    def _open_url(self, url):
        import webbrowser
        webbrowser.open(url)

    # ---- Key 连通性测试（免费模型 1-token 真实调用，不产生费用） ----
    def _test_key(self):
        key = self.key_asr.text().strip()
        if not key.startswith("sk-"):
            self.key_state.setText("Key 格式不对：应以 sk- 开头（在硅基流动「API 密钥」页面新建后复制）。")
            return
        self.key_state.setText("测试中…")
        def run():
            # 旧余额接口 /v1/user/info 已被官方下线(410)：改用免费翻译模型真实调用一次验证 Key
            from ..core.security import safe_client
            try:
                with safe_client(timeout=15) as cl:
                    r = cl.post("https://api.siliconflow.cn/v1/chat/completions",
                                headers={"Authorization": f"Bearer {key}"},
                                json={"model": "tencent/Hunyuan-MT-7B",
                                      "messages": [{"role": "user", "content": "hi"}],
                                      "max_tokens": 1, "stream": False})
                if r.status_code == 200:
                    self.key_state.setText("✓ Key 有效（真实调用成功）。点下一步继续。")
                elif r.status_code == 401:
                    self.key_state.setText("✗ Key 无效（HTTP 401），请重新复制粘贴。")
                else:
                    self.key_state.setText(f"✗ 服务返回 HTTP {r.status_code}，请稍后重试。")
            except Exception as e:
                self.key_state.setText(f"✗ 网络错误: {e}")
        import threading
        threading.Thread(target=run, daemon=True).start()

    def _sync_btns(self):
        i = self.stack.currentIndex()
        self.back_btn.setEnabled(i > 0)
        self.next_btn.setText("完成" if i == 3 else "下一步")

    def _back(self):
        if self._idx > 0:
            self._idx -= 1
            self.stack.setCurrentIndex(self._idx)
            self._sync_btns()

    def _next(self):
        i = self._idx
        if i == 0 and not self.chk_agree.isChecked():
            self.next_btn.setText("请先勾选同意")
            return
        if i == 0:
            self.cfg.disclaimer_accepted = True
        if i == 1:
            self.cfg.capture_mode = "loopback" if self.chk_skip_audio.isChecked() else "cable"
        if i == 2:
            k = self.key_asr.text().strip()
            if k:
                self.cfg.asr_keys[self.cfg.asr_preset] = k
                self.cfg.mt_keys[self.cfg.mt_preset] = k  # 识别+翻译共用同一个 Key
        if i == 3:
            self.cfg.first_run_done = True
            self.cfg.save()
            self.accept()
            return
        self._idx += 1
        self.stack.setCurrentIndex(self._idx)
        if self._idx == 1:
            self.detect_audio()
        self._sync_btns()
