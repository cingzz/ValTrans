# -*- coding: utf-8 -*-
# 作者: cing  ·  https://github.com/cingzz
# 许可: GPL-3.0 + 商业授权（闭源/商用需向作者申请授权），见 LICENSE 与 LICENSE-COMMERCIAL.md
#
"""Authenticode 签名校验（WinVerifyTrust，ctypes 直调 wintrust，无第三方依赖）。

为什么要有这个（v0.2.16 安全审计）
--------------------------------
安装器以 PrivilegesRequired=lowest 装到 %LOCALAPPDATA%\\Programs\\ValTrans
——**整棵安装目录对当前用户可写**，而 assets/drivers/VBCABLE_Setup_x64.exe
随后被 `ShellExecuteW("runas")` 提权执行。若该 exe 被本机恶意程序预先
替换，就等于替它提权（本地提权链）。

所以：任何要提权运行的可执行文件，运行前必须先过这里。
判定标准：WinVerifyTrust 返回 0（签名链完整且受信）才放行，
其余一律拒绝（fail-closed），拒绝信息如实告知用户。
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes

# WINTRUST_ACTION_GENERIC_VERIFY_V2 = {00AAC56B-CD44-11d0-8CC2-00C04FC295EE}


class _GUID(ctypes.Structure):
    _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]


_GENERIC_VERIFY_V2 = _GUID(
    0x00AAC56B, 0xCD44, 0x11D0,
    (ctypes.c_ubyte * 8)(0x8C, 0xC2, 0x00, 0xC0, 0x4F, 0xC2, 0x95, 0xEE))

_WTD_UI_NONE = 2
_WTD_REVOKE_NONE = 0
_WTD_CHOICE_FILE = 1
_WTD_STATEACTION_VERIFY = 1
_WTD_STATEACTION_CLOSE = 2
_TRUST_E_NOSIGNATURE = 0x800B0100


def verify_signed(path: str) -> tuple[bool, str]:
    """校验文件 Authenticode 签名。返回 (是否可信, 说明)。

    校验器本身出错/平台异常一律按**不可信**处理（fail-closed），
    由调用方给出「手动从官网下载」的兜底指引。
    """
    class _FILE_INFO(ctypes.Structure):
        _fields_ = [("cbStruct", wintypes.DWORD),
                    ("pcwszFilePath", wintypes.LPCWSTR),
                    ("hFile", wintypes.HANDLE),
                    ("pgKnownSubject", ctypes.c_void_p)]

    # 字段顺序与 wintrust.h 的 WINTRUST_DATA 一致（union 用 pFile 代表，
    # x64 下 ctypes 默认对齐 = MSVC 默认对齐）
    class _TRUST_DATA(ctypes.Structure):
        _fields_ = [("cbStruct", wintypes.DWORD),
                    ("pPolicyCallbackData", ctypes.c_void_p),
                    ("pSIPClientData", ctypes.c_void_p),
                    ("dwUIChoice", wintypes.DWORD),
                    ("fdwRevocationChecks", wintypes.DWORD),
                    ("dwUnionChoice", wintypes.DWORD),
                    ("pFile", ctypes.c_void_p),
                    ("dwStateAction", wintypes.DWORD),
                    ("hWVTStateData", wintypes.HANDLE),
                    ("pwszURLReference", ctypes.c_void_p),
                    ("dwProvFlags", wintypes.DWORD),
                    ("dwUIContext", wintypes.DWORD)]

    try:
        fi = _FILE_INFO(ctypes.sizeof(_FILE_INFO), str(path), None, None)
        td = _TRUST_DATA()
        td.cbStruct = ctypes.sizeof(_TRUST_DATA)
        td.dwUIChoice = _WTD_UI_NONE              # 不弹任何签名 UI
        td.fdwRevocationChecks = _WTD_REVOKE_NONE
        td.dwUnionChoice = _WTD_CHOICE_FILE
        td.pFile = ctypes.cast(ctypes.byref(fi), ctypes.c_void_p)
        td.dwStateAction = _WTD_STATEACTION_VERIFY

        trust = ctypes.windll.wintrust.WinVerifyTrust
        trust.restype = ctypes.c_long
        hr = trust(None, ctypes.byref(_GENERIC_VERIFY_V2), ctypes.byref(td))
        if hr == 0:
            # 释放 VERIFY 拿到的状态句柄
            td.dwStateAction = _WTD_STATEACTION_CLOSE
            try:
                trust(None, ctypes.byref(_GENERIC_VERIFY_V2), ctypes.byref(td))
            except Exception:
                pass
            return True, "签名有效"
        hr_u = hr & 0xFFFFFFFF
        if hr_u == _TRUST_E_NOSIGNATURE:
            return False, "文件未签名"
        return False, f"WinVerifyTrust hr=0x{hr_u:08X}"
    except Exception as e:
        return False, f"校验器异常 {type(e).__name__}"


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    target = sys.argv[1] if len(sys.argv) > 1 else ""
    ok, msg = verify_signed(target)
    print(f"{target}\n  -> {'可信' if ok else '不可信'}（{msg}）")
    raise SystemExit(0 if ok else 1)
