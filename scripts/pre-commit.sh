#!/bin/sh
# pre-commit 安全闸门 —— 有密钥就别想提交。
#
# 为什么要做成 git hook，而不是「记得跑一下」
# ----------------------------------------
# 「记得跑一下」等于「迟早会忘」。而密钥一旦进过 git 历史，
# **删文件也删不掉**，只能重写历史 + 吊销凭据。所以必须在 commit
# 那一刻拦住，而不是事后补救。
#
# 安装（仓库已 git init 后执行一次）：
#     sh scripts/pre-commit.sh .git/hooks/pre-commit
# Windows：
#     copy scripts\pre-commit.sh .git\hooks\pre-commit
#
# 手动完整检查：
#     python scripts/security_gate.py .
#
# 自证（证明它真的有用，而不是摆设）：
#     python scripts/hook_selftest.py
#
# 如需临时跳过（**不建议**）：git commit --no-verify
#   出了事，历史里的密钥是删不掉的。
set -e

PY=python
command -v python >/dev/null 2>&1 || PY=python3
command -v python  >/dev/null 2>&1 || PY=py

echo "[pre-commit] 运行安全闸门…"
if "$PY" scripts/security_gate.py .; then
  echo "[pre-commit] 通过，继续提交。"
  exit 0
fi

echo ""
echo "[pre-commit] ✋ 提交被拦下：检测到疑似密钥或敏感文件。"
echo ""
echo "  · 如果是真密钥：**不要**用 --no-verify 硬过。"
echo "    先把它从文件里删掉，再确认 git 历史里也没有"
echo "    （删文件删不掉历史，只能重写历史 + 吊销该凭据）。"
echo "  · 如果是误报：改 scripts/security_gate.py 的判据，"
echo "    并在同一次提交里说明为什么它是安全的 —— 别只是把它藏起来。"
exit 1
