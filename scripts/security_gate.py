# -*- coding: utf-8 -*-
"""推送前安全闸门 —— 有任何一项不过就 exit 1，不允许提交。

为什么要做成**闸门**而不是一次性检查
------------------------------------
「源码里 grep 不到 sk-」不等于安全，而且**一次检查过后就忘了**。
放进仓库后，任何人（包括未来的维护者）在 commit 前跑一次，
就能在东西进 git 历史**之前**拦住 —— 密钥一旦进过历史，删文件也删不掉。

★ 为什么不用「简单 grep」就行
--------------------------
踩过两次真实误报/漏报，都是自证当场抓出来的：
  1. 裸 `sk-` 正则把 CSS 的 `mask-sk-composite` 当成密钥；
  2. `Authorization` 判据要求冒号后必须有引号，于是
     `Authorization: Bearer xxx`（HTTP 标准写法，没有引号）反而漏掉。

所以判据必须是「像真 Key 的形态」，并且自证必须同时验证
**该拦的拦得住**与**不该拦的放得过**——只有前者叫漏报，两者都过才算闸门。

真要拦的：
  · 明文 API Key（sk- 开头、长度合理）
  · Bearer / Authorization 头里的令牌
  · 私钥 PEM、云厂商 AKIA / AIza / gh*_ / Slack 令牌
  · **git 历史里**的密钥（删文件删不掉，只能重写历史）
  · 被纳入版本控制的 config.json / .env / *.key / *.pem

自证：python scripts/gate_selftest.py
"""
from __future__ import annotations

import argparse
import io
import os
import re
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

TEXT_EXT = (".py", ".js", ".jsx", ".json", ".txt", ".md", ".iss", ".spec",
            ".toml", ".yml", ".yaml", ".ini", ".cfg", ".env", ".css",
            ".html", ".ps1", ".bat", ".csv")
BINARY_EXT = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".onnx",
              ".wav", ".mp3", ".exe", ".dll", ".pyd", ".sys", ".cat", ".inf",
              ".zip", ".mp4")
SKIP_DIR = {"node_modules", "__pycache__", ".venv", "_internal", ".git",
            "dist", "build"}

SIGNATURES = [
    ("明文 API Key",
     re.compile(r"""(?:sk|key|api)[_-]?[A-Za-z0-9]{0,4}\s*[=:]\s*['"][A-Za-z0-9_\-]{20,}['"]""")),
    ("sk- 形态的长串",
     re.compile(r"(?<![A-Za-z\-])sk-[A-Za-z0-9]{20,}(?![A-Za-z0-9\-])")),
    # 引号**可选**：HTTP 头标准写法 `Authorization: Bearer xxx` 没有引号。
    ("Authorization/Bearer",
     re.compile(r"[Aa]uthorization['\"]?\s*[=:]\s*['\"]?[Bb]earer\s+"
                r"[A-Za-z0-9_\-\.]{16,}")),
    ("裸 Bearer 令牌",
     re.compile(r"(?<![A-Za-z_\-])[Bb]earer\s+[A-Za-z0-9_\-\.]{32,}"
                r"(?![A-Za-z0-9_\-])")),
    ("PEM 私钥",
     re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |PGP )?PRIVATE KEY-----")),
    ("AWS 访问键",
     re.compile(r"(?<![A-Z0-9])AKIA[0-9A-Z]{16}(?![A-Z0-9])")),
    ("Google API Key",
     re.compile(r"(?<![A-Za-z0-9_\-])AIza[0-9A-Za-z_\-]{35}(?![A-Za-z0-9_\-])")),
    ("GitHub 令牌",
     re.compile(r"(?<![A-Za-z0-9])(?:ghp|gho|ghu|ghs|ghr|github_pat)_[A-Za-z0-9_]{20,}")),
    ("Slack 令牌",
     re.compile(r"(?<![A-Za-z0-9])xox[baprs]-[A-Za-z0-9\-]{10,}")),
    ("支付相关凭据",
     re.compile(r"(?:weixin|alipay|wxpay)[_-]?(?:id|key|mch)[_-]?\s*[=:]\s*['\"][A-Za-z0-9]{16,}")),
]

# 明知无害的前缀（CSS 属性名等）—— 命中即忽略
ALLOW_PREFIX = ("mask-", "-webkit-mask", "border-", "webkit-", "moz-")

# ---------------------------------------------------------------------------
# 测试夹具（假 Key）的识别 —— v0.3.1
# ---------------------------------------------------------------------------
# ★ 为什么必须有这一段
# --------------------
# 修这个闸门前，它对本仓库**恒 exit 1**：唯一那处命中是
#     tests/test_asr_failure_path.py
#         BAD_KEY = <自述无效的假 Key，形如 sk- + THISKEY + ...>
# 一个**自述无效**的假 Key，被当成了泄漏。
# （这里不写完整形态：完整形态会被**本文件自己**的签名扫出来，
#   虽然会被判成夹具不判红，但按 scripts/gate_selftest.py 开头
#   立的规矩，检测器文件里不该出现可扫描的完整凭据。）
#
# 后果不是「多报一次」，是**整个闸门失效**：
#   既然跑一次必然红，那就没人会再看它的输出 ——
#   哪怕哪天真混进了一把真 Key，报警和往常一模一样，谁也不会抬头。
#   本项目已经写过：「永远红的报告等于没有报告」。
#   一个只会喊狼来了的哨兵，比没有哨兵更危险，因为它让人以为有哨兵。
#
# ★ 为什么不用白名单
# ------------------
# 白名单要「每个夹具登记一次」，文件一多就腐烂：
#   · 新增测试夹具时没人记得登记 -> 闸门又变红 -> 又没人看
#   · 登记过的东西永远不会被复查 -> 真 Key 被误登记进去也没人发现
# 改用**负特征**（真 Key 满足不了的性质），它不会随文件数量退化：
#
#   ① 自述标记：token 里出现大写占位词（THISKEY / PLACEHOLDER / ...）
#      真 Key 是 base64/hex 随机串，不会拼出可读英文单词。
#   ② 极低熵：同一字符连续 ≥8 次（00000000 / aaaaaaaa）
#      base64 里出现 8 连同字符的概率约 (1/64)^7 ≈ 4e-14，实际不可能。
#
# 两条都是「真 Key 不可能满足」，而不是「我们选择放过」。
# 代价是夹具仍然会被打印出来（INFO 而非静默），
# 所以「放过了什么」始终是可复核的。
FIXTURE_MARKS = (
    "THISKEY", "THISIS", "PLACEHOLDER", "INTENTIONALLY", "NOTAREAL",
    "NOT_A_REAL", "YOURKEY", "YOUR_KEY", "YOURTOKEN", "EXAMPLEKEY",
    "DUMMYKEY", "SAMPLEKEY", "FAKEKEY", "DEADBEEF", "TESTKEY",
    "CHANGEME", "REPLACEME",
)
_FIXTURE_RUN = re.compile(r"(.)\1{7,}")     # 同一字符连续 ≥8 次

STRICT = False        # --strict 时置 True：夹具也一并判红


def is_fixture(s: str) -> bool:
    """这段看起来是**测试用的假凭据**，而不是真泄漏。

    只认两种负特征（见上方注释）。**不接受人工登记** ——
    白名单会腐烂，负特征不会。
    `--strict` 下一律返回 False（宁可误报，也不放过）。
    """
    if STRICT:
        return False
    u = s.upper()
    if any(m in u for m in FIXTURE_MARKS):
        return True
    return bool(_FIXTURE_RUN.search(s))

FORBIDDEN_NAMES = {"config.json", "secrets.json", ".env", ".env.local",
                   "credentials.json", "token.json", ".github_token"}
FORBIDDEN_EXT = (".key", ".pem", ".pfx", ".p12")


def iter_files(root):
    for dp, dn, fn in os.walk(root):
        dn[:] = [d for d in dn if d not in SKIP_DIR]
        for f in fn:
            ext = os.path.splitext(f)[1].lower()
            if ext in BINARY_EXT:
                continue
            if ext and ext not in TEXT_EXT:
                continue
            p = os.path.join(dp, f)
            try:
                if os.path.getsize(p) > 12 * 1024 * 1024:
                    continue
                yield p, io.open(p, encoding="utf-8", errors="replace").read()
            except OSError:
                continue


def scan_tree(root):
    print()
    print("=" * 70)
    print(" 扫描工作树：%s" % root)
    print("=" * 70)
    nfiles = 0
    found = []
    fixtures = []
    for p, txt in iter_files(root):
        nfiles += 1
        base = os.path.basename(p)
        if base in FORBIDDEN_NAMES or p.lower().endswith(FORBIDDEN_EXT):
            found.append((p, 0, "敏感文件名", base))
        for name, rx in SIGNATURES:
            for m in rx.finditer(txt):
                s = m.group(0)
                if any(s.lower().startswith(a) for a in ALLOW_PREFIX):
                    continue
                ln = txt[:m.start()].count("\n") + 1
                # 夹具**不静默**：照样打印，只是不判红。
                # 静默会让人无法复核「闸门到底放过了什么」。
                if is_fixture(s):
                    fixtures.append((p, ln, name, s))
                    continue
                found.append((p, ln, name, s))
    for p, ln, name, s in fixtures:
        masked = s[:10] + "…" + s[-3:] if len(s) > 16 else s
        print("  INFO [测试夹具，放行] %s:%d  %s"
              % (os.path.relpath(p, root), ln, masked))
    for p, ln, name, s in found:
        masked = s[:10] + "…" + s[-3:] if len(s) > 16 else s
        print("  FAIL [%s] %s%s  %s"
              % (name, os.path.relpath(p, root),
                 (":%d" % ln) if ln else "", masked))
    print("  扫了 %d 个文本文件，命中 %d 处（另识别测试夹具 %d 处）"
          % (nfiles, len(found), len(fixtures)))
    return found


def scan_git_history(root):
    print()
    print("=" * 70)
    print(" 扫描 git 历史（删文件也删不掉历史，所以这一步才有意义）")
    print("=" * 70)
    if not os.path.isdir(os.path.join(root, ".git")):
        print("  （不是 git 仓库，跳过）")
        return []
    p = subprocess.run(["git", "log", "--all", "-p", "--no-color"],
                       cwd=root, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    blob = p.stdout or ""
    found = []
    nfix = 0
    for name, rx in SIGNATURES:
        for m in rx.finditer(blob):
            s = m.group(0)
            if any(s.lower().startswith(a) for a in ALLOW_PREFIX):
                continue
            if is_fixture(s):
                nfix += 1
                continue
            found.append(("历史", 0, name, s))
    n = subprocess.run(["git", "rev-list", "--all", "--count"], cwd=root,
                       capture_output=True, text=True,
                       encoding="utf-8", errors="replace").stdout.strip()
    for _, _, name, s in found:
        print("  FAIL [历史中的 %s] %s…" % (name, s[:10]))
    print("  %s 次提交，命中 %d 处（另识别测试夹具 %d 处）"
          % (n or "0", len(found), nfix))
    if not found:
        print("  OK   历史干净")
    return found


def scan_staged(root):
    print()
    print("=" * 70)
    print(" 扫描暂存区（已 add 未 commit）")
    print("=" * 70)
    if not os.path.isdir(os.path.join(root, ".git")):
        print("  （不是 git 仓库，跳过）")
        return []
    names = subprocess.run(["git", "diff", "--cached", "--name-only"],
                           cwd=root, capture_output=True, text=True,
                           encoding="utf-8", errors="replace").stdout
    names = [n for n in names.split("\n") if n.strip()]
    if not names:
        print("  （暂存区为空）")
        return []
    blob = ""
    for n in names:
        blob += subprocess.run(["git", "show", ":" + n], cwd=root,
                               capture_output=True, text=True,
                               encoding="utf-8", errors="replace").stdout
    found = []
    nfix = 0
    for n in names:
        base = os.path.basename(n)
        if base in FORBIDDEN_NAMES or n.lower().endswith(FORBIDDEN_EXT):
            found.append((n, base))
    for name, rx in SIGNATURES:
        for m in rx.finditer(blob):
            s = m.group(0)
            if any(s.lower().startswith(a) for a in ALLOW_PREFIX):
                continue
            if is_fixture(s):
                nfix += 1
                continue
            found.append((name, s))
    for n, s in found:
        print("  FAIL [暂存] %s" % s)
    print("  暂存 %d 个文件，命中 %d 处（另识别测试夹具 %d 处）"
          % (len(names), len(found), nfix))
    if not found:
        print("  OK   暂存区干净")
    return found


def check_tracked(root):
    print()
    print("=" * 70)
    print(" 确认用户配置没被纳入版本控制")
    print("=" * 70)
    if not os.path.isdir(os.path.join(root, ".git")):
        print("  （不是 git 仓库，跳过）")
        return 0
    r = subprocess.run(["git", "ls-files"], cwd=root, capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    tracked = [f for f in r.stdout.split("\n") if f.strip()]
    bad = [f for f in tracked
           if os.path.basename(f) in FORBIDDEN_NAMES
           or f.lower().endswith(FORBIDDEN_EXT)]
    if bad:
        print("  FAIL 已被跟踪的敏感文件: %s" % bad)
        return len(bad)
    print("  OK   已跟踪 %d 个文件，其中无敏感配置" % len(tracked))
    return 0


def main():
    global STRICT
    ap = argparse.ArgumentParser(description="提交前安全闸门")
    ap.add_argument("roots", nargs="*", default=["."])
    ap.add_argument("--no-git", action="store_true",
                    help="跳过 git 历史与暂存区检查")
    ap.add_argument("--strict", action="store_true",
                    help="测试夹具（假 Key）也判红。用于发布前最后把关："
                         "默认允许夹具是为了让闸门「能红也能绿」，"
                         "但发布产物里本就不该有假 Key 这种噪音")
    args = ap.parse_args()
    STRICT = bool(args.strict)

    total = 0
    for r in (args.roots or ["."]):
        root = os.path.abspath(r)
        if not os.path.isdir(root):
            print("跳过（不存在）: %s" % r)
            continue
        total += len(scan_tree(root))
        if not args.no_git:
            total += len(scan_git_history(root))
            total += len(scan_staged(root))
            total += check_tracked(root)

    print()
    print("=" * 70)
    if total:
        print(" 安全闸门：未通过（%d 处）。**不要提交。**" % total)
        print("=" * 70)
        return 1
    print(" 安全闸门：通过")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
