# -*- coding: utf-8 -*-
"""把私有仓 ValTrans 的源码同步到 GPL 发布仓 ValTrans-OpenSource。

为什么要有这个脚本
==================
GPL 要求：分发了二进制，就必须提供与之对应的源码。
ValTrans-OpenSource 就是那个「源码」，可它停在 0.2.22，而分发的包是 0.3.0 ——
分发 0.3.0 的二进制却只公开 0.2.22 的源，这是实打实的合规缺口。

它落后一整个版本，原因不复杂：**同步从来没有脚本**，一直是手工拷文件。
手工做的事会被跳过，尤其在改完一堆文件、急着发版的时候。
所以第一步不是补这一次，是把它变成一条命令。

范围怎么定的
------------
以 OpenSource/README.md 的「目录」一节为准：
    src/core、src/services、src/uiweb、assets、scripts、webui、packaging
tests/ 与 docs/ **不在声明范围内** —— 私有仓有四百多个测试脚本，
GPL 只要求与分发二进制对应的源码，把一次性诊断脚本永久钉进公开仓库
既没必要，也会让后来者分不清哪些是常驻判据。

刻意排除的东西（每一项都有理由）
------------------------------
    *.probechk      临时探针输出，可能带本机路径/中间结果
    webui/tests/_out/  前端构建中间产物
    webui/dist/     构建产物（发布时单独打，不进源码仓）
    assets/lexicon.json  从词库仓刷进来的，源在 valtrans-lexicon

安全
----
这是**公开仓库**。写盘前先跑密钥扫描，扫出任何东西直接中止，
不做「先写上去再说」。宁可同步失败，也不可泄露。

用法
----
    python scripts/sync_opensource.py            # 只报告，不写（默认）
    python scripts/sync_opensource.py --apply    # 真的写
"""
from __future__ import annotations

import argparse
import ast
import io
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PRIVATE = os.path.dirname(HERE)                       # ValTrans/
OSS = os.path.normpath(os.path.join(PRIVATE, "..", "ValTrans-OpenSource"))

# 同步范围：README「目录」一节声明的 + 构建要用的 packaging
SCOPE = ("src/", "assets/", "scripts/", "webui/", "packaging/")

# 排除：目录名命中即整棵跳过
# ★ `_out` 而不是 `out` —— 第一版写的 "out" 匹配不到 `webui/tests/_out/`，
#   于是两个构建中间产物 ic.js / tb.js 混进了「新增」清单，差点跟着进公开仓。
#   排除规则和被排除的路径**名字不一致**是最常见的漏法：它不报错，
#   只是安静地什么都不排除。
SKIP_DIRS = {".git", "__pycache__", "node_modules", "dist", "build",
             "dist_onefile", "_backups", ".venv", "out", "_out"}

# 排除：文件名后缀/路径命中即跳过（每条都在上面写清了理由）
SKIP_FILES = (
    ".probechk",              # 临时探针输出
    "assets/lexicon.json",    # 词库仓刷进来的，源在 valtrans-lexicon
    "webui/dist/",            # 前端构建产物
)

# 只在开源仓、私有仓已删除 -> 需要一起删（否则公开仓里留着已经不存在的代码）
# 这几个是 v0.3.0 砍掉的 Qt 兜底界面。
ALSO_DELETE = ("src/app.py", "src/ui/overlay.py", "src/ui/pages.py",
               "src/ui/shell.py", "src/ui/theme.py", "src/ui/wizard.py")


def _skip(rel: str) -> bool:
    return any(rel.endswith(sfx) or rel.startswith(sfx) for sfx in SKIP_FILES)


def walk(root: str, scope=SCOPE):
    out = {}
    for dp, dns, fns in os.walk(root):
        dns[:] = [d for d in dns if d not in SKIP_DIRS]
        for fn in fns:
            p = os.path.join(dp, fn)
            rel = os.path.relpath(p, root).replace(os.sep, "/")
            if not rel.startswith(scope) or _skip(rel):
                continue
            try:
                out[rel] = io.open(p, "rb").read()
            except OSError:
                pass
    return out


def scan_secrets(rels):
    """把要写的文件交给项目的密钥扫描器。

    这是公开仓库，宁可中止也不要泄露。复用 tests/_scan_secrets.py 的判定，
    不自己另写一套 —— 两套扫描规则必然会漂移，而漂移的那个会漏。
    """
    sc = os.path.join(PRIVATE, "tests", "_scan_secrets.py")
    if not os.path.exists(sc):
        return "★ 找不到 tests/_scan_secrets.py，无法担保不泄露密钥"
    r = subprocess.run([sys.executable, "-X", "utf8", sc],
                       capture_output=True, cwd=PRIVATE)
    out = (r.stdout or b"").decode("utf-8", "replace")
    if r.returncode != 0 or "未发现明文密钥" not in out:
        return "★ 密钥扫描未通过，中止同步：\n" + out[-1200:]
    return None


def _dead_path_strings(path, callees=None):
    """AST 找出**会被执行**的、指向不公开目录的路径/导入。

    判据必须用 AST，不能用「这一行出现过 tests/」：
    逐行匹配会把文档字符串里的**溯源引用**（「这个结论由 tests/x.py 钉住」）
    和**运行时依赖**（open("tests/x.json")）一起报警。混为一谈的后果不是
    多报几次，是人很快就不看它了 —— 而那时真问题才刚要来。
    """
    DEAD = ("tests", "docs", "_backups", "research")
    CALLEE = callees or {
        "open", "io.open", "__import__", "import_module",
        "importlib.import_module", "run_path", "SourceFileLoader",
        "spec_from_file_location", "exec", "eval", "Popen", "run",
        "check_call", "check_output", "listdir", "scandir", "walk",
        "join", "abspath", "realpath", "normpath", "exists", "isfile",
        "isdir", "commonpath",
    }
    hits, cited = [], []
    body = io.open(path, encoding="utf-8", errors="replace").read()
    try:
        tree = ast.parse(body)
    except SyntaxError as e:
        return ["<解析失败 %s>" % e], []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            v = node.value
            # 溯源引用按**子串**找：它嵌在句子里（「结论由 tests/x.py 钉住」），
            # 开头匹配永远找不到。但必须带上目录分隔符 —— 光匹配 `docs` 会把
            # `https://docs.python.org` 也算成"引用了 docs 目录"。
            # 而下面的依赖判定按**开头**匹配：只有路径本身以那个目录起头，
            # open() 才真的会走到它去。一个判据里两种匹配方式，
            # 是因为这两种「命中」根本不是一回事。
            if any((d + "/") in v or (d + "\\") in v for d in DEAD):
                cited.append(getattr(node, "lineno", 0))
        if not isinstance(node, ast.Call):
            continue
        name = getattr(node.func, "id", "") or getattr(node.func, "attr", "")
        if name not in CALLEE:
            continue
        for arg in list(node.args) + [k.value for k in node.keywords]:
            val = None
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                val = arg.value
            elif isinstance(arg, (ast.JoinedStr, ast.BinOp)):
                val = "".join(c.value for c in ast.walk(arg)
                              if isinstance(c, ast.Constant)
                              and isinstance(c.value, str))
            if val and any(val.startswith(d) for d in DEAD):
                hits.append("%s:%d %s(%r)"
                            % (os.path.basename(path),
                               getattr(arg, "lineno", 0), name, val[:32]))
    return hits, cited


def verify_reachable(root):
    """检查一棵源码树里，有没有代码会去读/导入不公开的目录。"""
    hits, cited = [], []
    src = os.path.join(root, "src")
    if not os.path.isdir(src):
        return ["<找不到 src/>"], []
    for dp, dns, fns in os.walk(src):
        dns[:] = [d for d in dns if d != "__pycache__"]
        for fn in fns:
            if fn.endswith(".py"):
                h, c = _dead_path_strings(os.path.join(dp, fn))
                hits += h
                cited += c
    return hits, cited


# ── 自证：判据必须同时咬得住「真依赖」和放过「溯源引用」──────────────
def _selftest():
    import tempfile
    print("  自证：同一个判据，两种写法必须一红一绿")
    rc = 0
    with tempfile.TemporaryDirectory() as td:
        s = os.path.join(td, "src")
        os.makedirs(s)

        # A. 真依赖：代码会去 open 一个不公开的文件 -> 必须红
        p = os.path.join(s, "dep.py")
        io.open(p, "w", encoding="utf-8").write(
            'import os\nDATA = open("tests/fixtures.json").read()\n')
        hits, _ = verify_reachable(td)
        if hits:
            print("    OK   真依赖被抓：%s" % hits[0])
        else:
            print("    ★ 代码真的会读 tests/ 却没抓到 = 假闸门"); rc = 1

        # B. 溯源引用：只是文档里提到 tests/ -> 必须绿
        io.open(p, "w", encoding="utf-8").write(
            '"""结论由 tests/test_providers.py 钉住。"""\nX = 1\n')
        hits, cited = verify_reachable(td)
        if not hits and cited:
            print("    OK   溯源引用被放行（cited=%d 行），没有误伤" % len(cited))
        else:
            print("    ★ 文档里提了一句 tests/ 就判红 = 噪音判据（hits=%s）"
                  % hits); rc = 1

        # C. 反向：把 A 的写法再放回去 -> 必须重新变红（证明不是一直绿）
        io.open(p, "w", encoding="utf-8").write(
            'import os\ncfg = os.path.join("docs", "secrets.json")\n')
        hits, _ = verify_reachable(td)
        if hits:
            print("    OK   os.path.join 也算：%s" % hits[0])
        else:
            print("    ★ os.path.join(\"docs\", ...) 没抓到"); rc = 1
    return rc


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="真的写盘（默认只报告）")
    ap.add_argument("--selftest", action="store_true",
                    help="只验证「公开代码不引用不公开目录」这条判据咬得住")
    args = ap.parse_args()

    if args.selftest:
        rc = _selftest()
        print("  自证 %s" % ("全部通过" if rc == 0 else "失败 —— 判据不可信"))
        return rc

    if not os.path.isdir(OSS):
        print("★ 找不到开源仓：%s" % OSS)
        return 2

    a, b = walk(PRIVATE), walk(OSS)
    new = sorted(set(a) - set(b))
    same = sorted(k for k in set(a) & set(b) if a[k] == b[k])
    upd = sorted(k for k in set(a) & set(b) if a[k] != b[k])
    # 只在开源仓、且是已知要删的 Qt 文件
    gone = sorted(k for k in ALSO_DELETE if os.path.exists(os.path.join(OSS, k)))

    print("=" * 78)
    print(" 同步 ValTrans -> ValTrans-OpenSource   （%s）"
          % ("写盘" if args.apply else "仅报告，加 --apply 才写"))
    print("=" * 78)
    print("  范围      %s" % ", ".join(SCOPE))
    print("  新增      %d" % len(new))
    print("  更新      %d" % len(upd))
    print("  删除      %d" % len(gone))
    print("  已一致    %d" % len(same))
    print("-" * 78)
    for rel in new:
        print("    + %s" % rel)
    for rel in gone:
        print("    - %s" % rel)

    if not (new or upd or gone):
        print("  已经同步，无需改动。")
        return 0

    err = scan_secrets([k for k in new + upd])
    if err:
        print()
        print(err)
        return 3

    if not args.apply:
        print()
        print("  （未写盘。确认无误后加 --apply）")
        return 0

    # 批量改写前先备份：把开源仓当前状态原样复制一份
    bak = os.path.join(PRIVATE, "_backups",
                       "opensource_sync_%s" % __import__("datetime")
                       .datetime.now().strftime("%Y%m%d-%H%M%S"))
    shutil.copytree(OSS, os.path.join(bak, "ValTrans-OpenSource"),
                    ignore=shutil.ignore_patterns(".git"))
    print()
    print("  已备份到 %s" % os.path.relpath(bak, PRIVATE).replace(os.sep, "/"))

    for rel in new + upd:
        dst = os.path.join(OSS, *rel.split("/"))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        io.open(dst, "wb").write(a[rel])
    for rel in gone:
        os.remove(os.path.join(OSS, *rel.split("/")))

    # 清掉随之变空的 src/ui/ 目录
    uidir = os.path.join(OSS, "src", "ui")
    if os.path.isdir(uidir) and not os.listdir(uidir):
        os.rmdir(uidir)

    print("  写入 %d 个、删除 %d 个。" % (len(new + upd), len(gone)))

    # 写完立刻验：同步完成 ≠ 同步正确。最典型的漏法是「拷过去了，
    # 但公开代码开始引用一个按 README 就不公开的目录」——编译、导入
    # 全都正常，只有用户真跑起来才炸。所以这一步放在写盘之后、提交之前。
    hits, cited = verify_reachable(OSS)
    if hits:
        print()
        print("★ 同步后的公开代码会去读不公开的目录：")
        for h in hits[:8]:
            print("      %s" % h)
        print("   已备份在 %s，可整体还原。" % os.path.basename(bak))
        return 4
    print("  校验通过：公开代码不会去读 tests/docs/_backups"
          "（另有 %d 处文档溯源，不参与执行）。" % len(cited))
    print("  下一步：去 %s 检查 README 的版本号与目录表，再 git commit。"
          % os.path.basename(OSS))
    return 0


if __name__ == "__main__":
    sys.exit(main())
