# -*- mode: python ; coding: utf-8 -*-
# ValTrans PyInstaller 打包配置（onedir）
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
        # ★ v0.2.19：公共词库种子打进安装包（community.py 在 frozen 下解析到
        #   _internal/shared/，正好对上）。发布前用 valtrans-lexicon 仓库的
        #   lexicon.json 刷新 assets/lexicon.json。
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

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ValTrans",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon=os.path.join(ROOT, "assets", "icon.ico"),
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="ValTrans",
)
