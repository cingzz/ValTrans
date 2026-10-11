# -*- coding: utf-8 -*-
# 作者: cing  ·  https://github.com/cingzz
# 许可: GPL-3.0 + 商业授权（闭源/商用需向作者申请授权），见 LICENSE 与 LICENSE-COMMERCIAL.md
#
"""ValTrans 源码包。"""

# ★ 别在这里写死版本号。原���是 `__version__ = "0.1.0"`，
#   全项目零引用，但**任何人都可能顺手 `from src import __version__`**，
#   然后拿到一个停留在 0.1.0 的值 —— 而真正的版本在 src/version.py，
#   已经到 0.2.x 了。
#
#   这类「看起来能用、其实过期很久」的常量比没有更危险：
#   没有的时候你会去查文档，有了一个看起来合理的数字你就不查了。
#   版本号只有一处来源，要读就读 version.py。
from .version import VERSION as __version__  # noqa: F401
