# -*- coding: utf-8 -*-
"""划词翻译：取当前选中的文本 → 翻译 → 回填剪贴板。

★ 为什么必须模拟 Ctrl+C 而不是走 Win32 GetSelection
----------------------------------------------------
`GetSelection` 只能拿到自己窗口里的选区。这里要翻的是
**别的程序**（浏览器、PDF 阅读器、聊天软件、游戏聊天框）里的选中，
跨进程的选区 Win32 没有通用接口。

所以业界通行做法是「模拟 Ctrl+C → 读剪贴板 → 还原」。
代价是要动用户的剪贴板，因此 `grab_selection` 把**原内容原样还回去**，
只有显式 `keep=True`（用于回填译文）时才不还原。

★ 三个必须处理的坑
------------------
1. **剪贴板可能被占用**：别的程序（如剪贴板管理器）会锁住它。
   `SetClipboardData` 失败时必须抛出来，不能静默 ——
   静默的结果是「按了热键什么都没发生」，正是本项目明令禁止的反模式。

2. **选中为空**：没选中文字时按热键，不该弹「翻译失败」的红条，
   而该安静地什么都不做。空选区在 `grab_selection` 里就返回空串。

3. **按下热键会把 Ctrl 键留在按住状态**：模拟按键必须成对，
   否则用户接着打字会变成 Ctrl+字。这是最容易被忽略、
   而且一旦发生用户完全没法自己察觉的一类 bug。

★ 目标语言怎么定
----------------
自动：原文已经是中文 → 翻成英文（PTT 方向，队友看不懂中文时用）；
原文是外语 → 翻成中文（主方向）。
这个判断复用 `translate_gate.should_translate`，
与引擎里那条铁律是**同一份实现** ——
项目里最吃过亏的一类 bug 就是同一个判断写了两份、
两份结论相反（`looks_chinese` vs `should_translate`）。
"""
from __future__ import annotations

import ctypes
import logging
import time

_log = logging.getLogger("valtrans.selection")

# CF_UNICODETEXT
_CF_UNICODETEXT = 13
_USER32 = ctypes.windll.user32
_KERNEL32 = ctypes.windll.kernel32

# ★ v0.3.1：把 Win32 句柄类函数的 restype/argtypes 一次性声明在模块级
#   （外部审计 MiMo 命中，实测确认；读写两条路都中）
#
#   为什么必须显式声明
#   ------------------
#   ctypes 的**默认** restype 是 `c_int`（32 位）、默认按 c_int 传参。
#   而 HANDLE / HGLOBAL / SIZE_T 在 64 位 Windows 上是 64 位的。
#   于是：
#     · `handle = _KERNEL32.GlobalAlloc(...)`  -> 句柄被截成 32 位
#     · `ptr = _KERNEL32.GlobalLock(handle)`   -> 返回值又被截成 32 位
#   被截断的句柄传给 GlobalLock 往往直接返回 NULL，
#   表现就是**写剪贴板静默失败**（读路径同理，GetClipboardData 也截断）。
#
#   ★ 为什么现在还能用（这条比 bug 本身更重要）
#   ------------------------------------------
#   因为 Windows 的堆句柄数值常常恰好落在 32 位内，所以截断后"碰巧还是原值"。
#   也就是说：**这条 bug 不会稳定复现，它只在某个句柄值溢出 32 位时才发作**。
#   这类问题用「跑一遍看看能不能复制」是测不出来的，只能靠读代码定死。
#   本项目记过多次的「成功路径能跑 ≠ 失败路径能跑」，这里是同一族的另一面：
#   **今天能跑 ≠ 换台机器/换个句柄值还能跑**。
#
#   模块级声明而不是在函数里逐个设：函数里设会被下一个人复制粘贴时漏掉
#   （事实上读路径设了 restype，写路径没设 —— 就是这么漏的）。
_KERNEL32.GlobalAlloc.argtypes = (ctypes.c_uint, ctypes.c_size_t)
_KERNEL32.GlobalAlloc.restype = ctypes.c_void_p
_KERNEL32.GlobalLock.argtypes = (ctypes.c_void_p,)
_KERNEL32.GlobalLock.restype = ctypes.c_void_p
_KERNEL32.GlobalUnlock.argtypes = (ctypes.c_void_p,)
# 注意：SetClipboardData 在 **user32** 里，不在 kernel32
# （写成 _KERNEL32.SetClipboardData 不会报错 —— ctypes 按属性名惰性创建函数对象，
#   只在真正调用时才失败，于是这种错配能一直潜伏到某次复制时才炸。）
_USER32.GetClipboardData.argtypes = (ctypes.c_uint,)
_USER32.GetClipboardData.restype = ctypes.c_void_p
_USER32.SetClipboardData.argtypes = (ctypes.c_uint, ctypes.c_void_p)
_USER32.SetClipboardData.restype = ctypes.c_void_p

#: 模拟按键后等待的时间。太小会读到还没更新的剪贴板，
#: 太大在快速连按时会明显卡顿。80ms 是实测里稳定的取值。
_SETTLE_SECONDS = 0.08


class SelectionUnavailable(RuntimeError):
    """取不到选中文本 / 写不进剪贴板。调用方要把原因如实报给用户。"""


def _read_clipboard() -> str:
    """读剪贴板文本。失败返回空串（而不是抛）——
    读取失败多半是「本来就没有内容」，不该当成错误。"""
    try:
        import pyperclip
        return pyperclip.paste() or ""
    except Exception:
        # 刻意静默：读剪贴板失败就当「没内容」，下面还有 Win32 路径兜底
        pass
    if not _USER32.OpenClipboard(None):
        return ""
    try:
        handle = _USER32.GetClipboardData(_CF_UNICODETEXT)
        if not handle:
            return ""
        kernel = _KERNEL32
        kernel.GlobalLock.restype = ctypes.c_void_p
        ptr = kernel.GlobalLock(ctypes.c_void_p(handle))
        if not ptr:
            return ""
        try:
            return ctypes.c_wchar_p(ptr).value or ""
        finally:
            kernel.GlobalUnlock(ctypes.c_void_p(handle))
    except Exception as e:
        _log.debug("读剪贴板失败 %r", e)
        return ""
    finally:
        _USER32.CloseClipboard()


def _write_clipboard(text: str) -> None:
    """写剪贴板。**失败必须抛**，不能静默。"""
    if not text:
        raise SelectionUnavailable("译文为空，没有回填")
    try:
        import pyperclip
        pyperclip.copy(text)
        return
    except Exception as e:
        _log.debug("pyperclip 写入失败，改走 Win32：%r", e)
    # pyperclip 失败（常见于剪贴板被别的进程锁住）时走原生 API 再试一次
    if not _USER32.OpenClipboard(None):
        raise SelectionUnavailable(
            "剪贴板被其他程序占用，稍后再试一次") from None
    try:
        _USER32.EmptyClipboard()
        buf = ctypes.create_unicode_buffer(text)
        size = ctypes.sizeof(buf)
        handle = _KERNEL32.GlobalAlloc(0x2000, size)   # GMEM_MOVEABLE
        if not handle:
            raise SelectionUnavailable("分配剪贴板内存失败")
        ptr = _KERNEL32.GlobalLock(handle)
        if not ptr:
            raise SelectionUnavailable("锁定剪贴板内存失败")
        try:
            ctypes.memmove(ptr, ctypes.addressof(buf), size)
        finally:
            _KERNEL32.GlobalUnlock(handle)
        if not _USER32.SetClipboardData(_CF_UNICODETEXT, handle):
            raise SelectionUnavailable("写入剪贴板被拒绝")
    finally:
        _USER32.CloseClipboard()


def _tap_ctrl_c() -> None:
    """模拟一次 Ctrl+C。

    ★ 必须成对：keydown 后一定 keyup。
      只按下不抬起会让用户后续按键全变成 Ctrl+X，
      而用户完全不知道是自己刚才用了这个功能导致的。
    """
    VK_CONTROL, VK_C = 0x11, 0x43
    KEYEVENTF_KEYUP = 0x0002
    _USER32.keybd_event(VK_CONTROL, 0, 0, 0)
    try:
        _USER32.keybd_event(VK_C, 0, 0, 0)
        time.sleep(0.01)
        _USER32.keybd_event(VK_C, 0, KEYEVENTF_KEYUP, 0)
    finally:
        # 就算中间抛异常也要把 Ctrl 松开 —— 卡住 Ctrl 比报错严重得多
        _USER32.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)


def grab_selection() -> str:
    """取当前选中文本，并把剪贴板**原样还原**。

    返回空串表示「没选中任何文字」，调用方应当静默返回而不是报错。
    """
    saved = _read_clipboard()
    try:
        _tap_ctrl_c()
        time.sleep(_SETTLE_SECONDS)
        picked = _read_clipboard()
    finally:
        # 无论成功失败都还原：用户的剪贴板不该被这个功能悄悄换掉
        if saved:
            try:
                _write_clipboard(saved)
            except SelectionUnavailable as e:
                _log.warning("划词翻译：还原剪贴板失败 %s（原文已取到）", e)
    return picked if picked and picked != saved else ""


def fill_clipboard(text: str) -> None:
    """把译文回填到剪贴板（这是用户要的最终结果，不还原）。"""
    _write_clipboard(text)


def pick_target(text: str) -> str:
    """自动判断该翻成什么。

    已是中文 → 英文（PTT 方向）；否则 → 中文（主方向）。
    判断复用 translate_gate.should_translate，与引擎同源 ——
    同一个判断写两遍必然分叉，项目里已经因此出过 bug。
    """
    from ..services.translate_gate import should_translate
    return "en" if not should_translate(text, "zh") else "zh"