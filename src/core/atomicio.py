# -*- coding: utf-8 -*-
r"""原子写文件 —— 本项目**唯一**的写盘入口。

★ 为什么单独开一个模块
----------------------
外部审计（Step-5 P1-5 / MiMo M-3）点出：`tm.py` / `learning.py` /
`error_reports.py` / `community.py` 四处 JSON 状态文件都是**直接覆盖写**：

    p.write_text(json.dumps(d, ...), encoding="utf-8")

`write_text` 是「先截断、再一段段写」。在**截断之后、写完之前**这个窗口里
文件是**空的或半截的**。这个窗口平时几毫秒，撞上就出事：

    · 用户关机 / 断电 / 进程被杀  ->  tm.json 剩下 `{` 或干脆 0 字节
    · 磁盘满                       ->  同上
    · 杀毒软件 / 同步盘正在占用     ->  同上

而这些文件的加载方普遍写的是「读不到就当空」—— 于是**丢数据不报错**。
翻译记忆、已采纳的用户词表、错误报告去重键，全部一夜归零，
且用户只会觉得「怎么之前的记录都没了」，完全不知道是哪一步坏的。

★ 正确做法（项目里早就有，只是没统一）
--------------------------------------
`core/config.py:514-517` 一直是这么写的：

    tmp = CONFIG_FILE.with_name("config.json.tmp")
    tmp.write_text(json.dumps(d, ...), encoding="utf-8")
    os.replace(tmp, CONFIG_FILE)

`os.replace` 在同一个卷上是**原子**的：它要么完整替换、要么什么都不做，
不存在「写了一半」这个中间态。所以本模块不是发明新东西，
**是把已经验证过的写法收成一个函数**，让下一个写盘的人不用重新想。

★ 为什么收口到一个函数，而不是各处照抄
--------------------------------------
照抄 = 5 处各写一遍 = 下次新增第 6 处时又忘了。
本项目的教训原话：「有≠对」——「有写盘代码」和「写盘是原子的」是两件事，
而 grep 只能看见前者。
收口之后，守护测试只需要盯**一个函数**，加上「谁还在裸调 write_text」。

★ fsync 的取舍
--------------
严格版本还应对 tmp 做 `os.fsync`，确保数据真的落到盘上再替换。
这里**没有**加，理由是实测权衡：
    · 这几个文件是几十 KB 的 JSON，fsync 会让每次保存多几毫秒到几十毫秒
    · 不加 fsync 时，`os.replace` 已经能杜绝**进程被杀/异常中断**造成的
      半截文件（本条是这四个文件真正的杀手）；剩下的「整机掉电」窗口
      极小，且这类文件都可由云端重新拉取（词库）或可重建（统计）
如果哪天某个文件变成「丢了无法恢复」，再单独给它加 fsync ——
不要为了一个尚未出现的需求让所有写盘都变慢。
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Union

__all__ = ["atomic_write_text", "atomic_write_json"]

_PathLike = Union[str, os.PathLike, Path]


def _as_path(p: _PathLike) -> Path:
    return p if isinstance(p, Path) else Path(p)


def atomic_write_text(path: _PathLike, text: str,
                      encoding: str = "utf-8", newline: str | None = None) -> Path:
    """把 ``text`` 原子地写进 ``path``，返回目标路径。

    步骤：建父目录 -> 写同目录临时文件 -> ``os.replace`` 原子替换。

    ★ 临时文件必须与目标**同目录**
      跨目录的 replace 在 Windows 上会直接失败（`os.replace` 要求同卷），
      而 `shutil.move` 又不是原子的。同目录是唯一同时满足两点的做法。
      也因此不能图省事把 tmp 放进系统临时目录。

    ★ 临时文件名固定（`.tmp` 后缀）
      用 `tempfile.NamedTemporaryFile` 会得到随机名，失败时会在目录里
      留下一堆没人认领的垃圾文件。这里用固定名：正常路径下它永远会被
      replace 掉；异常路径下它是**唯一一个** `.tmp`，好认也好清理。
    """
    dst = _as_path(path)
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(dst.name + ".tmp")
    # newline="" 交给调用方决定；None 时用默认（平台无关，因为 text 里
    # 的换行已经由 json.dumps 决定，不再做转换）
    with open(tmp, "w", encoding=encoding, newline=newline) as fh:
        fh.write(text)
        fh.flush()
    os.replace(tmp, dst)
    return dst


def atomic_write_json(path: _PathLike, obj: Any, *,
                      indent: int | None = 2,
                      ensure_ascii: bool = False,
                      sort_keys: bool = False,
                      trailing_newline: bool = False) -> Path:
    """把 ``obj`` 序列化后原子写盘。

    默认参数对齐本项目既有用法：中文不转义（``ensure_ascii=False``）、
    缩进 2 空格、不排序键（排序会让 diff 变大，不利于人工核对）。

    ``trailing_newline`` 给 ``community.py`` 那种「写完补一个换行」的用法。
    """
    text = json.dumps(obj, ensure_ascii=ensure_ascii, indent=indent,
                      sort_keys=sort_keys)
    if trailing_newline:
        text += "\n"
    return atomic_write_text(path, text)
