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

（★ v0.3.1 更正：下面这份扫描结果是**一次性观察**，不是被强制的
  不变量。它当时没错，但「这次扫出来是 0」不等于「以后都是 0」——
  换台机器、第三方库多打一行栈，0 就不再是 0。而且它漏掉了一个
  **与日志内容无关**的确定泄露：`log_dir`（= %APPDATA%\\ValTrans\\logs，
  必然含 Windows 用户名）被原样拼进公开 issue 正文。所以现在
  真正的保证是 `tests/test_feedback_privacy.py` 那道**端到端判据**：
  拼出来的 issue URL 里不许出现本机用户名。扫描结果只能当参考。）

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


# ---------------------------------------------------------------------------
# 路径 / 用户名脱敏
# ---------------------------------------------------------------------------
# ★ 为什么密钥脱敏不够（这一条是 v0.3.1 外部审计后补的）
# --------------------------------------------------------------------------
# 本模块顶部写着「实测本机 webui.log 共 26 万字符，扫描结果：
# Windows 用户名/路径 0 处」。**那是一次性观察，不是被强制的不变量** ——
# 换台机器、换个版本、第三方库多打一行栈，0 就不再是 0。
# 更要命的是有一处**确定会**泄露、而且和日志内容无关：
#
#     LOG_DIR = %APPDATA%\ValTrans\logs
#             = C:\Users\<你的名字>\AppData\Roaming\ValTrans\logs
#
# 这个字符串被原样拼进 `build_draft()["log_dir"]`，
# 再被前端拼进**公开 issue 的正文**（FeedbackDialog 里两处）。
# 也就是说：任何人只要提一次反馈，GitHub 上就永久留下他的 Windows 用户名。
# 密钥形态扫描器**拦不住它** —— 它不是密钥。
#
# 所以按平台各补一条规则，且**在 Python 侧脱**：
# 前端只是拼装，改前端防不住 `log_tail` 里第三方库打进来的路径。
# ---------------------------------------------------------------------------

# 「用户目录」的通用形态。**不**按精确用户名匹配，是为了连日志里出现的
# **别人**的路径（用户粘贴的日志、第三方库报错里的路径）也一起脱掉。
_WIN_USERDIR = re.compile(
    r"(?i)([A-Za-z]:[\\/]+(?:Users|Documents and Settings)[\\/]+)"
    r"([^\\/\s\"']+)")
_NIX_USERDIR = re.compile(r"((?:/home/|/Users/))([^/\s\"']+)")

# 裸用户名（不在路径里）的替换条件 —— 宁可漏一点，不可误伤诊断信息。
#   · 长度 >= 4：短用户名（sam / tom / kim / max / lee）几乎必然撞上
#     正文里的英文单词（maximum / tomorrow / maximum），一换就把日志换坏，
#     排查问题的人看到一堆 <用户名>um 只会以为工具坏了。
#   · 常见词黑名单同理：用户名就叫 admin / user / test 的机器上，
#     全局替换会把 "user" / "test" 全吃掉，日志直接没法读。
_BARE_MIN_LEN = 4
_BARE_SKIP = frozenset({
    "admin", "user", "users", "test", "guest", "root", "home",
    "system", "system32", "temp", "tmp", "name", "default",
    "public", "data", "logs", "log", "valtrans",
})


def _user() -> str:
    """本机用户名 —— **不抛异常，所以不需要 try/except**。

    ★ v0.3.1：原来是 `try: getpass.getuser() except Exception: ""`。
      静默吞异常棘轮（tests/audit_silent_except.py）当场判红。
      去查怎么写理由豁免时才回过头问：**这两个 except 真的需要吗？**

      `getpass.getuser()` 本来就是依次读 LOGNAME / USER / LNAME /
      USERNAME 这几个环境变量，读不到才抛。既然如此，直接读环境变量
      就能达到同样效果，而且**读不到就是读不到，返回空串** ——
      下游本来就把空串当「不知道用户名」处理（跳过裸名替换，
      路径组件规则照常工作）。

      结论：**最好的修法不是给 except 写理由，而是让它不存在。**
      写理由豁免只是把「有异常」变成「有理由的异常」，
      而这里它连存在价值都没有。（另见 _home()，同一个道理。）
    """
    for k in ("USERNAME", "USER", "LOGNAME"):
        v = (os.environ.get(k) or "").strip()
        if v:
            return v
    return ""


def _home() -> str:
    """本机 home 目录 —— 同样不抛异常，直接读环境变量。

    覆盖面和 `pathlib.Path.home()` 一致：Windows 看 USERPROFILE，
    再退到 HOMEDRIVE+HOMEPATH；POSIX 看 HOME。读不到就返回空串，
    于是 `_redact_paths` 跳过第 ① 步（home 换 ~），直接走第 ② 步的
    平台形态规则 —— 那条规则本来就不依赖「知道 home 在哪」，
    所以这里「读不到」不会造成任何漏脱敏。
    """
    h = (os.environ.get("USERPROFILE") or os.environ.get("HOME") or "").strip()
    if h:
        return h
    d = (os.environ.get("HOMEDRIVE") or "").strip()
    p = (os.environ.get("HOMEPATH") or "").strip()
    return (d + p) if (d and p) else ""


def _redact_paths(text: str) -> tuple[str, int]:
    """把本机路径里的用户名换成占位符。返回 (文本, 替换了几个组件)。

    顺序是有讲究的，从「零误报」到「有取舍」：

      ① 先把**本机 home 目录整串**换成 `~`
         精确字符串替换，不可能误伤，且最有用 ——
         `C:\\Users\\John\\AppData\\Roaming\\ValTrans\\logs`
         -> `~\\AppData\\Roaming\\ValTrans\\logs`
         排查的人照样知道是哪个文件，而用户名没了。
      ② 再按平台形态吃掉**任何**用户目录组件（含别人的路径）
      ③ 最后才考虑裸用户名，且带长度与黑名单两道闸
    """
    n = 0

    # ① home 目录整串 -> ~（零误报）
    home = _home()
    if home and len(home) > 3:
        if home in text:
            text = text.replace(home, "~")
            n += text.count("~")          # 粗略计数即可，只用于 UI 提示

    # ② 平台形态的用户目录组件
    def _sub(m):
        nonlocal n
        n += 1
        return m.group(1) + "<用户名>"

    text = _WIN_USERDIR.sub(_sub, text)
    text = _NIX_USERDIR.sub(_sub, text)

    # ③ 裸用户名（最后一道，带两道闸）
    u = _user()
    if len(u) >= _BARE_MIN_LEN and u.lower() not in _BARE_SKIP:
        rx = re.compile(r"\b%s\b" % re.escape(u), re.IGNORECASE)

        def _sub2(m):
            nonlocal n
            n += 1
            return "<用户名>"

        text = rx.sub(_sub2, text)

    return text, n


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
    out = {"text": "", "files": [], "redacted": 0, "paths_redacted": 0,
           "total_bytes": 0}
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
        # 路径/用户名脱敏放在密钥之后：两套规则互不重叠，
        # 且这里的计数**不并进** `redacted` —— 前端把它显示成
        # 「已自动隐去 N 处疑似密钥」，混进路径数就变成假话了。
        text, out["paths_redacted"] = _redact_paths(text)
        out["text"] = text
    except Exception as e:
        # ★ v0.3.1：这里原来是 `except Exception: pass` ——
        #   静默吞异常棘轮（tests/audit_silent_except.py）判红，判得对。
        #   光写「为什么可以静默」其实不够：读日志失败的**后果是可见的**
        #   （用户在反馈框里看到一块空白的日志区），却查不到原因，
        #   只会以为「我没运行过软件」。所以不豁免，改成**把原因带出去**。
        #   这符合棘轮给出的处理方式②：静默会藏 bug -> 至少记下来。
        out["error"] = "%s: %s" % (type(e).__name__, e)
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
            # v0.3.0：Qt 兜底界面已移除，主界面只剩 WebView2。
            # 但**不能直接写死「WebView2」四个字**：万一用户还留着
            # VALTRANS_UI=qt 的旧快捷方式，反馈草里就得看得见这件事 ——
            # 否则排查的人会以为是界面坏了，其实是那个变量早就不管用了。
            "- 主界面: WebView2" + ("（VALTRANS_UI=qt 已在 v0.3.0 移除，不生效）"
                                   if os.environ.get("VALTRANS_UI", "").lower() == "qt"
                                   else ""),
        ])
    except Exception as e:
        return "- （读取配置失败: %s）" % e


def build_draft(local_version: str = "") -> dict:
    """组装反馈草稿。前端拿它拼 GitHub issue 正文。

    ★ 字段的公开/私有边界（v0.3.1 起明确写死）
    ---------------------------------------------------------------
    这个 dict 会被前端**直接拼进公开 issue 的 URL**，
    所以每个字段都必须问一句「这个能公开吗」：

        env_block / log_tail / body_hint  → 公开，已各自脱敏
        log_dir                            → **公开**，必须脱敏
        log_dir_full                       → **仅本地显示**，禁止进 issue
                                             （用户要靠它在自己机器上找文件，
                                              所以不能脱；代价是它绝不能外传）

    为什么提供两个而不是一个：脱敏后的路径 `~\\AppData\\...` 够用但不好找，
    用户在对话框里看到完整路径才知道去哪拖文件。两个字段 + 一条守卫
    （tests/test_feedback_privacy.py 断言 issue_url 里不含用户名）比
    「只给一个、靠人记得别外传」可靠 —— 本项目这轮已经因为
    「注释说做完了」栽过五次。
    """
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

    _dir_full = str(LOG_DIR)
    _dir_safe, _dir_n = _redact_paths(_dir_full)

    return {
        "ok": True,
        "version": local_version,
        "issue_url": ISSUE_NEW,
        "repo": REPO,
        "env_block": "\n".join(env),
        "log_tail": log["text"],
        "log_redacted": log["redacted"],
        "log_paths_redacted": log["paths_redacted"] + _dir_n,
        # 读日志失败时的原因（空串 = 正常）。留着让前端能显示出来，
        # 否则「日志区是空的」和「没有日志文件」在界面上一模一样。
        "log_error": log.get("error", ""),
        "log_files": log["files"],
        "log_dir": _dir_safe,
        "log_dir_full": _dir_full,
        "body_hint": len(env) + len(log["text"]),
    }
