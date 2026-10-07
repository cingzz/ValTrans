# -*- coding: utf-8 -*-
# 作者: cing  ·  https://github.com/cingzz
# 许可: GPL-3.0 + 商业授权（闭源/商用需向作者申请授权），见 LICENSE 与 LICENSE-COMMERCIAL.md
#
"""ValTrans 入口：python -m src.main"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# 保证以源码目录或打包后均可运行
if getattr(sys, "frozen", False):
    sys.path.insert(0, str(Path(sys.executable).parent))
else:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main() -> int:
    ui = os.environ.get("VALTRANS_UI", "web").lower()
    if ui == "qt":
        # 旧 PySide6 界面（兜底保留，可随时回退）
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QFont
        from PySide6.QtWidgets import QApplication
        QApplication.setHighDpiScaleFactorRoundingPolicy(
            Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
        from src.app import App
        app = App(sys.argv)
        app.qapp.setFont(QFont("Microsoft YaHei UI", 9))
        return app.run()
    # 默认：Web UI（React + WebView2）
    from src.uiweb.host import run
    return run()


if __name__ == "__main__":
    raise SystemExit(main())
