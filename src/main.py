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
    # v0.3.0：砍掉 PySide6 兜底界面（src/app.py + src/ui/* 已删除）。
    #
    #   为什么敢砍：PySide6 占打包产物 _internal 的 91.6MB / 44.5%，而它
    #   只是「Web 界面起不来时的备用界面」，主链路从来不是它。
    #   **字幕浮窗完全不受影响** —— Web 路径的浮窗是
    #   src/uiweb/native_overlay.py（WinForms 分层窗口 + GDI+，v0.2.11），
    #   本来就没走 Qt；src/ui/overlay.py 那个 QWidget 版只有 Qt 界面在用。
    #
    #   代价（用户拍板接受）：WebView2 起不来时不再有备用界面。正因如此，
    #   这里**不能静默** —— 设过 VALTRANS_UI=qt 的老配置要看得见，否则
    #   人会对着一个「设了没反应」的环境变量发懵，还以为是软件坏了。
    #   打一行到 stderr 再照常启动 Web，不中断（中断 = 用户什么都打不开）。
    if os.environ.get("VALTRANS_UI", "").lower() == "qt":
        print("[ValTrans] v0.3.0 已移除 PySide6 兜底界面："
              "VALTRANS_UI=qt 不再生效，继续启动 Web 界面。",
              file=sys.stderr)

    # 默认：Web UI（React + WebView2）。启动失败由 host.run 记进
    # logs/webui.log 并打到 stderr，不在此处再包一层 except
    # （多一层 except 就多一个吞错的地方，棘轮 audit_silent_except 也会拦）。
    from src.uiweb.host import run
    return run()


if __name__ == "__main__":
    raise SystemExit(main())
