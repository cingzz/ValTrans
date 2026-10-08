# -*- mode: python ; coding: utf-8 -*-
# ValTrans PyInstaller 打包配置（onefile，单文件）
#
# ★ 为什么不直接改 valtrans.spec
# -----------------------------
# valtrans.spec 是 onedir（exe + _internal/ 目录），已经过 16 项产物验证，
# 也是安装包和免安装版的来源，**不能动**。
# 这里另开一份 onefile 变体，专供「下载一个文件双击就能用」的需求。
#
# ★ onefile 与 onedir 的取舍
# -------------------------
#  onedir：启动快（无解压），但必须整个目录一起分发
#  onefile：单文件，启动时把 215MB 解压到 %TEMP% 再跑
#
# onefile 的代价是真实的，不是零成本：
#  · 冷启动多等 5~15 秒（解压 215MB）；之后走缓存会快一些
#  · 需要 %TEMP% 有 250MB 以上可用空间
#  · AV 误报率明显更高（自解压 exe 的通病）
#  · 运行时若被强杀，可能在 %TEMP% 留下残目录
# 所以**两种都发**：安装包和免安装版走 onedir（快、干净），
# 这个单文件版给「就想点一个文件」的人。
import os

block_cipher = None
ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))

a = Analysis(
    [os.path.join(ROOT, "src", "main.py")],
    pathex=[ROOT],
    binaries=[],
    datas=[
        (os.path.join(ROOT, "assets", "silero_vad.onnx"), "assets"),
        (os.path.join(ROOT, "assets", "icon.ico"), "assets"),
        (os.path.join(ROOT, "assets", "drivers"), "assets/drivers"),
        (os.path.join(ROOT, "assets", "samples"), "assets/samples"),
        # ★ 与 onedir 保持一致：community.py 在 frozen 下解析到 _internal/shared/
        (os.path.join(ROOT, "assets", "lexicon.json"), "shared"),
        (os.path.join(ROOT, "webui", "dist"), "webui_dist"),
    ],
    hiddenimports=[
        "src", "src.app", "src.core.config", "src.core.security",
        "src.core.audio_capture", "src.core.segmenter", "src.core.pipeline",
        "src.services.engine", "src.services.tts", "src.services.reverse_ptt",
        "src.ui.theme", "src.ui.shell", "src.ui.pages", "src.ui.overlay",
        "src.ui.wizard",
        "src.uiweb", "src.uiweb.host", "src.uiweb.api",
        # ★ v0.2.22：上报反馈。api.py 里是函数内延迟 import，
        #   显式列出来双保险 —— 少一个 hiddenimport 就整块功能静默消失，
        #   而打包不会报错。
        "src.services.feedback",
        "webview", "webview.platforms.edgechromium", "webview.platforms.winforms",
        "webview.http", "bottle", "pystray", "pystray._win32",
        "sounddevice", "pyaudiowpatch", "pynput", "edge_tts", "miniaudio",
        "pyperclip", "soxr", "onnxruntime", "httpx", "anyio",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "torch", "torchvision", "torchaudio", "matplotlib", "scipy",
        "tkinter", "pandas", "IPython", "jedi", "PyQt5",
    ],
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# ★ onefile：没有 COLLECT，所有内容直接进 EXE。
#   runtime_tmpdir=None -> 走系统 %TEMP%。
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="ValTrans",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    icon=os.path.join(ROOT, "assets", "icon.ico"),
)
