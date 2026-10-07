# -*- coding: utf-8 -*-
"""上报反馈：收集诊断信息 + 日志尾巴，拼成一份可提交到 GitHub issue 的草稿。

为什么存在这个模块
------------------
「翻译错了」有 `report_error`（针对某一句译文，走词库分级），
但「软件崩了 / 浮窗不显示 / 装不上 / 想提建议」这类**软件问题**
没有入口 —— ���户要么去翻源码，要么不反馈。

为什么不做「一键上传」
--------------------
GitHub 创建 issue 的接口必须带密钥。密钥随安装包分发 = 把仓库写权限
公开给每一个下载者。所以只做**准备**：把信息填好，用户点一下提交。

★ 隐私边界（这是设计约束，不是事后补的说明）
-------------------------------------------
日志会被放进公开的 issue 里，所以必须先确认它不含敏感信息。
实测本机 webui.log 共 26 万字符，扫描结果：

    API Key 形态      0 处
    Authorization 头   0 处
    Windows 用户名/路径  0 处
    邮箱              0 处
    内网地址          0 处

日志只记「程序做了什么」，不记「用户说了什么」——
翻译原文/译文从 v0.2.16 起一律不落盘（见 engine 里日志调用点的注释）。
即便如此，仍在 UI 上明示「发前请看一眼」，因为日志可能含本机路径。
"""
from __future__ import annotations

import io
import os
import platform
import re
import sys
from pathlib import Path

from ..core.config import LOG_DIR

# GitHub issue 正文上限约 64KB；但 URL 本身也有长度限制（浏览器/服务器），
# 所以只放「尾部若干字符」，其余让用户按需自己拖文件。
LOG_TAIL_CHARS = 3000

REPO = "cingzz/ValTrans"
ISSUE_NEW = "https://github.com/%s/issues/new" % REPO

# 再扫一遍：万一将来日志格式变了，这里能拦住明显的密钥形态。
_SECRET_PAT = re.compile(
    r"sk-[A-Za-z0-9]{16,}"
    r"|eyJ[A-Za-z0-9_\-]{30,}"
    r"|Bearer\s+[A-Za-z0-9._\-]{16,}"
    r"|-----BEGIN [A-Z ]*PRIVATE KEY-----"
)


def _redact(text: str) -> tuple[str, int]:
    """把疑似密钥替换掉。返回 (文本, 替换了几处)。

    这是**兜底**，不是主要防线 —— 真正的防线是「日志压根不写密钥」。
    但万一某个第三方库把自己的配置打进日志，我们不替它背锅。
    """
    n = 0

    def _sub(_m):
        nonlocal n
        n += 1
        return "[已隐去疑似密钥]"

    return _SECRET_PAT.sub(_sub, text), n


def _log_tail(max_chars: int = LOG_TAIL_CHARS) -> dict:
    """取最新日志的尾部。

    为什么取尾部：出问题的那一刻一定在日志最后面。

    ★ 为什么「按时间倒序逐个装填」而不是「拼起来再切尾部」
      修复前是 files[0] + files[1] 拼好，再 text[-max_chars:]。
      拼接顺序是「最新 → 最旧」，所以切出来的尾部恰好是**最旧那个文件** ——
      实测草稿末尾是 valtrans.log（10-01，2.4KB 的历史残留），
      而真正相关的 webui.log（当天，282KB）被整段截掉了。
      后果是用户崩了上报，收到的是一周前的日志，完全没用。
      现在改成：按新到旧依次「各取一段尾部」，预算用完就停。
    """
    out = {"text": "", "files": [], "redacted": 0, "total_bytes": 0}
    try:
        d = Path(LOG_DIR)
        if not d.is_dir():
            return out
        files = sorted((p for p in d.iterdir() if p.is_file()),
                       key=lambda p: p.stat().st_mtime, reverse=True)
        parts = []
        budget = max_chars
        for p in files:
            try:
                raw = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            out["files"].append({
                "name": p.name,
                "kb": round(p.stat().st_size / 1024, 1),
                "path": str(p),
            })
            out["total_bytes"] += p.stat().st_size
            if budget <= 200:
                break                      # 预算不够再放一个文件的头了
            seg = raw[-budget:]
            parts.append("===== %s (%.0f KB 的最后 %d 字符) =====\n%s"
                         % (p.name, len(raw) / 1024, len(seg), seg))
            budget -= len(seg)
        text = "\n\n".join(parts)
        text, out["redacted"] = _redact(text)
        out["text"] = text
    except Exception:
        pass
    return out


def _cfg_summary() -> str:
    """配置摘要 —— **只列键名，绝不取值，也不解密**。

    API Key 是 DPAPI 加密存着的。反馈里需要的是「配了哪个服务商」
    （能解释「为什么连不上」），而不是 Key 本身。

    ★ 这里刻意**不调用** `_decrypt_keys`
    ------------------------------
    第一版是 `asr = _decrypt_keys(cfg.asr_keys or {})` 然后
    `", ".join(sorted(asr.keys()))` —— 解密出来的明文只用到了键名，
    密文本身完全用不上。等于**为了打印三个字，把三把明文 Key 短暂
    放进了内存**。明文 Key 在内存里多待一刻就多一分风险
    （异常栈、内存转储、误加进日志），而这里一个字都用不上。
    改成直接读原始 dict 的键名：零解密、零明文。
    """
    try:
        from ..core.config import AppConfig
        cfg = AppConfig.load()
        asr = cfg.asr_keys or {}          # 不解密：这里只要键名
        mt = cfg.mt_keys or {}
        return "\n".join([
            "- 语音采集模式: %s" % getattr(cfg, "capture_mode", "?"),
            "- 识别服务: %s" % (", ".join(sorted(asr.keys())) or "未配置"),
            "- 翻译服务: %s" % (", ".join(sorted(mt.keys())) or "未配置"),
            "- 浮窗: %s%s" % (
                "启用" if getattr(cfg, "overlay_enabled", False) else "关闭",
                "（已锁定穿透）" if getattr(cfg, "overlay_locked", False) else ""),
            "- 主界面: %s" % ("WebView2" if os.environ.get(
                "VALTRANS_UI") != "qt" else "PySide6（兼容回退）"),
        ])
    except Exception as e:
        return "- （读取配置失败: %s）" % e


def build_draft(local_version: str = "") -> dict:
    """组装反馈草稿。前端拿它拼 GitHub issue 正文。"""
    log = _log_tail()
    env = [
        "### 环境",
        "",
        "- ValTrans: v%s" % (local_version or "?"),
        "- 系统: %s %s (%s)" % (platform.system(), platform.release(),
                                platform.machine()),
        "- Python: %s" % platform.python_version(),
        "",
        "### 当前配置",
        "",
        _cfg_summary(),
    ]
    if log["files"]:
        env += ["", "### 日志文件", ""]
        env += ["- `%s` (%.1f KB)" % (f["name"], f["kb"])
                for f in log["files"]]
        env += ["", "> 日志可能包含本机路径等信息，发送前请确认可以公开。"]
    else:
        env += ["", "> 没有找到日志文件（可能还没运行过）。"]

    return {
        "ok": True,
        "version": local_version,
        "issue_url": ISSUE_NEW,
        "repo": REPO,
        "env_block": "\n".join(env),
        "log_tail": log["text"],
        "log_redacted": log["redacted"],
        "log_files": log["files"],
        "log_dir": str(LOG_DIR),
        "body_hint": len(env) + len(log["text"]),
    }
