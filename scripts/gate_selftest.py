# -*- coding: utf-8 -*-
"""安全闸门自证 —— 注入真泄露验证「必须拦」，同时验证「不该拦的放得过」。

为什么闸门必须自证
------------------
「闸门跑起来没报错」不等于「闸门有用」。本项目在写这道闸门时
当场被自证抓出两个问题：

  1. 裸 `sk-` 正则把 CSS 的 `mask-sk-composite` 当成密钥（误报）；
  2. `Authorization` 判据要求冒号后必须有引号，于是
     `Authorization: Bearer xxx`（HTTP 标准写法，没有引号）反而漏掉。

两处都不是事后 review 发现的，是自证逼出来的。所以这份自证
和闸门本身同等重要 —— 没有它，闸门只是给人安全感的摆设。

★ 所有假密钥都必须**拆成片段**
----------------------------
第一版把 AWS 访问键、PEM 私钥头这些直接写成字面量，于是
**这个自证文件自己被判红** —— 检测器文件触发了检测器，
自证里所有「必须放行」的用例变成「必须拦」，全红。

第二版把代码里的字面量拆了，却**在注释里**为了说明问题
又把完整形态写了出来 —— 说明文字照样被扫，一样判红。

所以连注释都不能出现完整形态，只能描述「一个 AWS 访问键」而不给原文。

为什么不用「把这两个文件从扫描里排除」：那种做法等于开一个
魔法例外，而例外是可以被人用来藏真泄露的。拆片段更彻底。

跑法：
    python scripts/gate_selftest.py
"""
from __future__ import annotations

import io
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
GATE = os.path.join(HERE, "security_gate.py")

FAKE_KEY = "sk-" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"
FAKE_TOKEN = "abcdef0123456789" + "abcdef0123456789"        # 32 字符
_PEM = ("-----BEGIN " + "RSA " + "PRIVATE KEY-----\n" + "MIIE...\n")
_AWS = "AKIA" + "IOSFODNN7EXAMPLE"
_GHP = "ghp_" + "abcdefghijklmnopqrstuvwxyz0123"
_XOX = "xoxb-" + "123456789012-" + "abcdefghijkl"
_PLACEHOLDER = "sk-" + "xxxx"          # 文档常见的占位写法，必须放行

CASES = [
    # (说明, 注入内容, 是否必须拦下)
    ("明文 API Key（赋值）", 'API_KEY = "%s"\n' % FAKE_KEY, True),
    ("明文 API Key（JSON）", '{"siliconflow": "%s"}\n' % FAKE_KEY, True),
    ("Authorization 带引号",
     'h = {"Authorization": "Bearer %s"}\n' % FAKE_TOKEN, True),
    ("Authorization 无引号（HTTP 标准写法）",
     "Authorization: Bearer %s\n" % FAKE_TOKEN, True),
    ("裸 Bearer 令牌", 'curl -H "Bearer %s"\n' % FAKE_TOKEN, True),
    ("PEM 私钥", _PEM, True),
    ("AWS 访问键", 'A = "%s"\n' % _AWS, True),
    ("GitHub 令牌", 'T = "%s"\n' % _GHP, True),
    ("Slack 令牌", 'S = "%s"\n' % _XOX, True),
    # ↓ 以下必须放行（误报比漏报更烦人：没人看红着的闸门）
    ("CSS 属性 mask-sk-composite",
     "x{mask-composite:exclude;-webkit-mask-composite:xor}\n", False),
    ("CSS border-sk", "y{border-image-slice:1;border-sk:x}\n", False),
    ("sk- 短串（不足阈值）", 'n="sk-short"\nv="sk-abc"\n', False),
    ("正常源码", 'print("hi")\nVERSION="0.2.22"\n', False),
    ("文档里的示例 Key（占位）",
     '例如 API_KEY = "%s" # 占位\n' % _PLACEHOLDER, False),
]


def run(paths, no_git=True):
    args = [sys.executable, "-X", "utf8", GATE]
    if no_git:
        args.append("--no-git")
    p = subprocess.run(args + paths, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def main() -> int:
    print("=" * 70)
    print(" 安全闸门自证")
    print("=" * 70)
    probe = os.path.join(ROOT, "_gate_selftest_probe.py")
    bad = 0

    rc, out = run([ROOT])
    if rc != 0:
        print("  FAIL 原状（干净仓库）就被判红 —— 闸门误伤了正常代码")
        for l in out.split("\n"):
            if "FAIL" in l:
                print("       %s" % l.strip()[:100])
        bad += 1
    else:
        print("  OK   原状（干净仓库）放行")

    try:
        for label, content, must_block in CASES:
            io.open(probe, "w", encoding="utf-8", newline="\n").write(content)
            rc, out = run([ROOT])
            blocked = rc != 0
            good = blocked == must_block
            if not good:
                bad += 1
            print("  %s %-36s %s（期望%s）"
                  % ("OK  " if good else "FAIL", label,
                     "拦下" if blocked else "放行",
                     "必须拦" if must_block else "必须放行"))
            if not good and must_block:
                for l in out.split("\n"):
                    if "FAIL" in l:
                        print("        %s" % l.strip()[:100])
    finally:
        if os.path.exists(probe):
            os.remove(probe)

    # ③ 只存在于 git 历史里的泄露（工作树已干净但历史里有 —— 最危险）
    print()
    print("  --- 只在 git 历史里的泄露（删文件删不掉的那些）---")
    base = os.environ.get("LOCALAPPDATA", ".")
    hist = os.path.join(base, "_gate_hist_test")
    shutil.rmtree(hist, ignore_errors=True)
    os.makedirs(hist, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=hist, capture_output=True)
    io.open(os.path.join(hist, "cfg.py"), "w", encoding="utf-8").write(
        'KEY = "%s"\n' % FAKE_KEY)
    # 这两行必须各自独立成行。曾经它们被吞进上一行的注释里，
    # 于是文件从未被 add、历史里什么都没有，闸门当然放行 ——
    # 而输出会显示成「漏抓」。**改动没验证就以为改好了**的典型。
    subprocess.run(["git", "add", "-A"], cwd=hist, capture_output=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                    "commit", "-qm", "x"], cwd=hist, capture_output=True)
    os.remove(os.path.join(hist, "cfg.py"))       # 工作树删掉，历史里还在
    # 必须**不传** --no-git，否则等于自己把历史检查关掉，
    # 再据此断言「漏抓」—— 那是自证写错了，不是闸门坏了。
    rc, _ = run([hist], no_git=False)
    if rc != 0:
        print("  OK   拦下历史中的泄露")
    else:
        print("  FAIL 漏抓：工作树干净但 git 历史里有 Key，闸门却放行")
        bad += 1
    shutil.rmtree(hist, ignore_errors=True)

    # ④ 被纳入版本控制的配置文件
    print()
    print("  --- 被纳入版本控制的 config.json ---")
    bad_dir = os.path.join(base, "_gate_cfg_test")
    shutil.rmtree(bad_dir, ignore_errors=True)
    os.makedirs(bad_dir, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=bad_dir, capture_output=True)
    io.open(os.path.join(bad_dir, "config.json"), "w",
            encoding="utf-8").write('{"asr_keys":{}}\n')
    subprocess.run(["git", "add", "-f", "config.json"], cwd=bad_dir,
                   capture_output=True)
    rc, _ = run([bad_dir])
    if rc != 0:
        print("  OK   拦下被强制纳入的 config.json")
    else:
        print("  FAIL 漏抓：config.json 进了版本库")
        bad += 1
    shutil.rmtree(bad_dir, ignore_errors=True)

    print()
    print("=" * 70)
    print(" 自证结论：%d 项不符" % bad)
    print("=" * 70)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
