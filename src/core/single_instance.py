# -*- coding: utf-8 -*-
r"""单实例守卫。

为什么需要（2026-10-06 用户实测）
----------------------------------
用户报「我把软件后台退了，但它的弹窗还在桌面上，我根本退不了」。
日志给出了确定证据 —— 那次运行里**同时有两个实例**：

    01:35:30  全局热键已启动 …            <- 第 1 次
    01:35:30  全局热键已启动 …            <- 第 2 次
    01:35:32  DIAG complete …:60531      <- 端口 A
    01:35:33  DIAG complete …:7858       <- 端口 B
    01:35:33  overlay created  hwnd=397664
    01:35:40  overlay created  hwnd=1446250

全仓 grep `single_instance|CreateMutex|单实例|已在运行` = **零命中**。
两个实例各建一个浮窗；用户从托盘退掉的是其中一个，
**另一个的浮窗就留在桌面上了**，而那个进程他根本不知道在哪。

关键推论：**窗口能留在屏幕上，说明进程还活着** —— 进程一退出，
Windows 会回收它创建的所有窗口。所以这不是 close() 写错了，
是「有两个进程」的问题。修 close() 修不到点子上。

为什么用命名互斥量而不是锁文件
------------------------------
锁文件（`O_EXCL` / `CreateFile`+`CREATE_NEW`）会在进程被强杀时留下
**死锁文件**，下一次启动永远起不来 —— 那比多开一个实例更糟。
`CreateMutexW` 是**内核对象**：进程一死（哪怕 `taskkill /F`），
内核立刻自动释放，不留残留。这是 Windows 单实例的标准做法。

命名用 `Local\` 而非 `Global\`：同一登录会话内互斥就够，
且 `Global\` 在个别环境下需要额外权限、可能失败。
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes

MUTEX_NAME = r"Local\ValTrans.SingleInstance.v0200"
ERROR_ALREADY_EXISTS = 183
WAIT_OBJECT_0 = 0
WAIT_TIMEOUT = 0x102

_handle = None          # 持有句柄期间本进程就是唯一实例


def _k32():
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
    k.CreateMutexW.restype = wintypes.HANDLE
    k.CloseHandle.argtypes = [wintypes.HANDLE]
    k.CloseHandle.restype = wintypes.BOOL
    k.ReleaseMutex.argtypes = [wintypes.HANDLE]
    k.ReleaseMutex.restype = wintypes.BOOL
    k.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    k.WaitForSingleObject.restype = wintypes.DWORD
    return k


def acquire(wait_ms: int = 0, name: str = MUTEX_NAME) -> tuple[bool, str]:
    """尝试成为唯一实例，返回 (是否拿到, 说明)。

    `wait_ms` > 0 时会给「上一个实例刚退出」留宽限时间：
    先看锁是否已被占用，占用则等它释放。
    句柄会一直持有在模块级 `_handle` —— 一关掉就不再互斥了。
    """
    global _handle
    if _handle is not None:
        return True, "本进程已持有"
    k = _k32()
    # bInitialOwner=True：创建者即持有，别的进程打开同一名字会看到已占用
    h = k.CreateMutexW(None, True, name)
    if not h:
        return False, "CreateMutexW 失败 err=%d" % ctypes.get_last_error()
    already = ctypes.get_last_error() == ERROR_ALREADY_EXISTS
    if not already:
        _handle = h
        return True, "拿到互斥（此前无实例）"
    if wait_ms and wait_ms > 0:
        r = k.WaitForSingleObject(h, int(wait_ms))
        if r == WAIT_OBJECT_0:
            _handle = h
            return True, "拿到互斥（等待 %dms 后前一个实例退出了）" % wait_ms
        k.CloseHandle(h)
        return False, "已有实例在运行（等待 %dms 未退出）" % wait_ms
    k.CloseHandle(h)
    return False, "已有实例在运行"


def release() -> None:
    """正常退出时释放。进程被强杀时内核也会自动释放。

    静默：释放失败不影响退出流程（进程一死内核照样回收），
    所以这里不抛、不记日志 —— 属于「崩溃了也无所谓」的清理路径。
    """
    global _handle
    if _handle is None:
        return
    try:
        k = _k32()
        k.ReleaseMutex(_handle)
        k.CloseHandle(_handle)
    except Exception:
        pass          # 释放失败无所谓：进程退出时内核自动回收互斥量
    _handle = None


def activate_existing(title: str) -> bool:
    """把已存在实例的主窗口叫到前台（第二次启动时的友好行为）。

    （踩过的坑：`SetForegroundWindow` 会被前台锁挡住，
    必须先 `keybd_event(VK_MENU)` 假装用户按了 Alt。
    """
    try:
        u = ctypes.windll.user32
        hwnd = u.FindWindowW(None, title)
        if not hwnd:
            return False
        u.ShowWindow(hwnd, 9)          # SW_RESTORE
        VK_MENU = 0x12
        u.keybd_event(VK_MENU, 0, 0, 0)
        u.SetForegroundWindow(hwnd)
        u.keybd_event(VK_MENU, 0, 2, 0)
        return True
    except Exception:
        return False