# -*- coding: utf-8 -*-
"""pre-commit hook 实测 —— 证明它真的拦得住，而不是写完就算。

「闸门写好了」和「闸门有用」是两件事。这份脚本真跑一次 git commit，
分别用正常文件与含假密钥的文件各提交一次，验证：
  ① 正常文件能提交（hook 不能把仓库锁死）
  ② 含密钥的提交被拦下
  ③ 密钥确实没有进 git 历史

★ 不要在测试里用 `git clean -fd`
---------------------------------
上一轮就是因为在**刚 init、还没提交过任何东西**的目录里跑了
`git clean -qfd`，把整个仓库内容（src/ webui/ README.md 全部）
当成「未跟踪文件」删掉了 —— 它看起来只是清理，实际是销毁。
这里改成只删自己造的那一个探针文件。
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
HOOK_SRC = os.path.join(HERE, "pre-commit.sh")
FAKE = "sk-" + "Z9y8X7w6V5u4T3s2R1q0P9o8N7m6L5k4"


def sh(cmd, cwd):
    # 每条 git 命令都带临时身份：开发机上可能**没配** user.name/email，
    # 不隔离的话 commit 会先死在 "Author identity unknown"，
    # 根本走不到 hook —— 那会让「测试通过」变成假象。
    if cmd.startswith("git "):
        cmd = "git -c user.email=selftest@local -c user.name=selftest " \
              + cmd[4:]
    return subprocess.run(cmd, cwd=cwd, shell=True, capture_output=True,
                          text=True, encoding="utf-8", errors="replace")


def main() -> int:
    bad = 0
    hooks = os.path.join(ROOT, ".git", "hooks")
    if not os.path.isdir(os.path.join(ROOT, ".git")):
        print("  跳过：还不是 git 仓库")
        return 0

    print("=" * 70)
    print(" 安装 hook")
    print("=" * 70)
    os.makedirs(hooks, exist_ok=True)
    shutil.copy2(HOOK_SRC, os.path.join(hooks, "pre-commit"))
    print("  已复制到 .git/hooks/pre-commit")

    probe = os.path.join(ROOT, "_hook_probe.py")
    print()
    print("=" * 70)
    print(" 实测 1：正常文件必须能提交")
    print("=" * 70)
    io.open(probe, "w", encoding="utf-8", newline="\n").write(
        'VERSION = "0.2.22"\n')
    sh("git add _hook_probe.py", ROOT)
    r = sh('git commit -m "test: normal file"', ROOT)
    committed = r.returncode == 0
    print("  %s 正常提交%s" % ("OK  " if committed else "FAIL",
                            "成功" if committed else "被拒"))
    print("      %s" % ((r.stdout or r.stderr).strip().split("\n") or [""])[0][:90])
    if not committed:
        bad += 1

    print()
    print("=" * 70)
    print(" 实测 2：含假 Key 的提交必须被拦")
    print("=" * 70)
    io.open(probe, "w", encoding="utf-8", newline="\n").write(
        'KEY = "%s"\n' % FAKE)
    sh("git add -A", ROOT)
    r = sh('git commit -m "test: with key"', ROOT)
    blocked = r.returncode != 0
    print("  %s 含密钥提交%s" % ("OK  " if blocked else "FAIL",
                           "被拦" if blocked else "竟然成功了"))
    out = (r.stdout or "") + (r.stderr or "")
    print("      %s" % (out.strip().split("\n") or [""])[0][:90])
    if not blocked:
        bad += 1
        print("  !! hook 没生效 —— 修好之前不要提交任何东西")

    print()
    print("=" * 70)
    print(" 确认密钥没进 git 历史")
    print("=" * 70)
    h = sh("git log --all -p", ROOT)
    in_hist = FAKE in (h.stdout or "")
    print("  %s 历史里%s该密钥"
          % ("OK  " if not in_hist else "FAIL", "**含**" if in_hist else "不含"))
    if in_hist:
        bad += 1

    # 清理：只删自己造的探针，**不用 git clean**
    sh("git reset -q", ROOT)
    if os.path.exists(probe):
        os.remove(probe)

    print()
    print("=" * 70)
    print(" 结果：%d 项不符" % bad)
    print("=" * 70)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
