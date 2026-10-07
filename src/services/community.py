# -*- coding: utf-8 -*-
# 作者: cing  ·  https://github.com/cingzz
# 许可: GPL-3.0 + 商业授权（闭源/商用需向作者申请授权），见 LICENSE 与 LICENSE-COMMERCIAL.md
#
"""公共词库同步（开源众包）—— 走公开 Git 仓库，不自建服务器。

为什么用 Git 仓库而不是中心 API
------------------------------
项目决定开源分发（github.com/cingzz）。这个场景下 Git 反而是
最优解：

  · 零服务器、零运营成本、永久可用（仓库不会「欠费下线」）
  · 词条变更**有 git 历史、可追溯、可回滚** —— 中心数据库做不到这点
  · **任何人可审可改**，走 PR 流程，天然有人把关
  · 不经过任何人的服务器 = 没有单点作恶/跑路风险

隐私红线（写死在代码里，不靠自觉）
------------------------------------
**只上传用户主动点过「提交误报」的那一条文本。**
不上传：完整对局记录、音频、API Key、设备信息、时间戳、用户身份。
导出函数 `error_reports.export_public()` 只吐 (src, dst, lang) 三元组。

数据格式（人可读、可 review、可手改）
------------------------------------
`shared/lexicon.json`：

    {
      "version": 1,
      "updated": "2026-10-03",
      "terms": [
        {"src": "they are setting up on a", "dst": "他们在A点架枪",
         "lang": "en", "reporters": 5}
      ]
    }

`reporters` 只写**去重后的上报人数**，不写是谁 —— 众包要的是共识度，
不是身份。

同步方向
--------
  pull：启动时 / 手动点「同步词库」-> 拉公共词库，合并进本地 TM
  push：本地有达标上报时 -> 生成一份 proposals 文件，
       **不自动 push**，而是告诉用户「有 N 条可提交，去开 PR」
       （自动 push 需要凭据，而且不该让用户不知情地往公共库写东西）
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

from ..core.config import CONFIG_DIR

_LOCK = None                      # 同步是低频操作，不加锁

SHARED_DIR = Path(__file__).resolve().parents[2] / "shared"
LEXICON = SHARED_DIR / "lexicon.json"
PROPOSALS = SHARED_DIR / "proposals.json"

# ---------------------------------------------------------------------------
# ★ v0.2.19：免 git 的玩家拉取通道
# ---------------------------------------------------------------------------
# 旧链路要求本机装 git + clone 仓库 + 会 pull——目标用户是玩家不是开发者，
# 而且大陆直连 GitHub 经常不通。现在：
#   1. 词库种子打进安装包（assets/lexicon.json → _internal/shared/）；
#   2. 启动后经 safe_client 拉 jsdelivr CDN 镜像（国内通常可达），
#      按 version 单调更新到用户缓存 %APPDATA%/ValTrans/lexicon.json，
#      再走现成的 merge_into_tm()；
#   3. 默认 7 天一次、任何失败静默（词库刷新是锦上添花，绝不影响主链）；
#   4. git pull 保留为开发者路径（pull()）。
# 上传侧不变：仍然手动开 PR、绝不自动 push（隐私设计，见 load_proposals）。
CACHE = CONFIG_DIR / "lexicon.json"
SYNC_STATE = CONFIG_DIR / "lexicon_sync.json"
CDN_URLS = [
    "https://fastly.jsdelivr.net/gh/cingzz/valtrans-lexicon@main/lexicon.json",
    "https://cdn.jsdelivr.net/gh/cingzz/valtrans-lexicon@main/lexicon.json",
]
REFRESH_INTERVAL_S = 7 * 86400


def _read_json(p: Path, default):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return default


def _write_json(p: Path, d) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(d, ensure_ascii=False, indent=2) + "\n",
                 encoding="utf-8")


def _lexicon_path() -> Path:
    """用户缓存（CDN 刷新产物）优先于安装包内置种子。"""
    if CACHE.exists():
        return CACHE
    return LEXICON


def lexicon() -> dict:
    return _read_json(_lexicon_path(), {"version": 1, "terms": []})


def _touch_sync_state() -> None:
    _write_json(SYNC_STATE, {"last_check": time.time()})


def refresh_from_cdn(force: bool = False) -> dict:
    """从 jsdelivr CDN 拉公共词库（免 git，玩家路径）。永不抛异常。

    version 单调比较：远端不比本地新就不动缓存。默认 7 天一次
    （lexicon_sync.json 记上次检查时间），force=True 立即查。
    """
    out = {"ok": False, "updated": False, "msg": ""}
    try:
        state = _read_json(SYNC_STATE, {"last_check": 0})
        if not force and time.time() - float(state.get("last_check", 0)) < REFRESH_INTERVAL_S:
            out["msg"] = "未到刷新周期（7 天一次）"
            return out
        from ..core.security import pooled_client
        client = pooled_client(timeout=30.0)
        raw = None
        for u in CDN_URLS:
            try:
                r = client.get(u, timeout=10.0)
                r.raise_for_status()
                cand = json.loads(r.content.decode("utf-8"))
                if isinstance(cand, dict) and isinstance(cand.get("terms"), list):
                    raw = cand
                    break
            except Exception:
                continue
        _touch_sync_state()
        if raw is None:
            out["msg"] = "CDN 暂不可达（不影响使用，词库仍用本地版本）"
            return out
        local = lexicon()
        if int(raw.get("version", 0)) <= int(local.get("version", 0)):
            out["ok"] = True
            out["msg"] = f"词库已是最新（v{local.get('version')}）"
            return out
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(json.dumps(raw, ensure_ascii=False, indent=2) + "\n",
                         encoding="utf-8")
        n = merge_into_tm()
        out["ok"] = True
        out["updated"] = True
        out["msg"] = f"词库已更新到 v{raw.get('version')}，合并 {n} 条到本地"
        return out
    except Exception as e:
        out["msg"] = f"词库刷新失败（不影响使用）：{type(e).__name__}"
        return out


def _key(t: dict) -> str:
    return f"{t.get('lang', 'en')}|{(t.get('src') or '').strip().lower()}"


def merge_from_file(p: Path) -> int:
    """把指定词库文件合并进本地翻译记忆。"""
    from . import tm
    data = _read_json(p, {"terms": []})
    n = 0
    for t in data.get("terms", []):
        src, dst = (t.get("src") or "").strip(), (t.get("dst") or "").strip()
        if not src or not dst:
            continue
        if tm.record(src, dst, t.get("lang", "en"), "public"):
            n += 1
    return n


def merge_into_tm() -> int:
    """把公共词库合并进本地翻译记忆（0 额外延迟，之后照常命中）。"""
    return merge_from_file(_lexicon_path())


def load_proposals() -> dict:
    """把本地达标的误报写成待提交文件（**不自动 push**）。

    只收「达到共识门槛」的；有分歧的一律不收 ——
    有争议的说法进公共库会让没参与的人白拿一个可能是错的答案。
    """
    from . import error_reports
    items = error_reports.export_public()
    if not items:
        _write_json(PROPOSALS, {"version": 1, "proposals": []})
        return 0
    # 合并到公共词库同一格式，便于对比 diff
    merged = { _key(t): dict(t, reporters=int(t.get("reporters", 0)))
               for t in lexicon().get("terms", []) }
    for it in items:
        k = _key(it)
        cur = merged.get(k)
        merged[k] = {"src": it["src"], "dst": it["dst"],
                     "lang": it.get("lang", "en"),
                     "reporters": (int(cur.get("reporters", 0)) + 1) if cur else 1}
    out = {"version": 1,
           "updated": time.strftime("%Y-%m-%d"),
           "proposals": sorted(merged.values(), key=lambda x: x["src"])}
    _write_json(PROPOSALS, out)
    return len(out["proposals"])


# ---------------------------------------------------------------------------
# git 操作（凭据由用户在本地配，不硬编码）
# ---------------------------------------------------------------------------
def _git(*args, repo: Path | None = None) -> tuple[int, str]:
    exe = "git"
    try:
        r = subprocess.run([exe, *args], cwd=str(repo) if repo else None,
                           capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=120)
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except FileNotFoundError:
        return 127, "找不到 git，请先安装 Git for Windows"
    except Exception as e:
        return 1, f"{type(e).__name__}: {e}"


def pull(repo: Path) -> dict:
    """从公共仓库拉取词库并合并（开发者路径；玩家走 refresh_from_cdn）。

    凭据建议用 Git Credential Manager（`git credential-manager` 交互登录）
    或 SSH key —— **不要**把令牌写进 URL 或配置文件。
    """
    if not (repo / ".git").exists():
        return {"ok": False, "msg": f"{repo} 不是 git 仓库"}
    rc, out = _git("pull", "--rebase", "origin", repo=repo)
    if rc != 0:
        return {"ok": False, "msg": f"拉取失败：{out.strip()[:300]}"}
    # ★ v0.2.19：git 拉新后以仓库文件为准合并，并同步用户缓存
    # （lexicon() 现在优先读缓存，不这里兜底会出现"仓库新了但缓存遮住"）
    n = merge_from_file(LEXICON)
    try:
        repo_v = int(_read_json(LEXICON, {}).get("version", 0))
        cache_v = int(_read_json(CACHE, {}).get("version", 0)) if CACHE.exists() else -1
        if repo_v > cache_v:
            CACHE.parent.mkdir(parents=True, exist_ok=True)
            CACHE.write_text(LEXICON.read_text(encoding="utf-8"), encoding="utf-8")
    except Exception:
        pass
    return {"ok": True, "merged": n, "msg": f"已同步，合并 {n} 条到本地词库"}


def status(repo: Path) -> dict:
    """仓库状态（给 UI 显示，不含任何凭据）。"""
    if not (repo / ".git").exists():
        return {"ok": False, "msg": "未初始化 git 仓库"}
    rc, rem = _git("remote", "v", repo=repo)
    rc2, br = _git("rev-parse", "--abbrev-ref", "HEAD", repo=repo)
    rc3, st = _git("status", "--porcelain", repo=repo)
    return {
        "ok": True,
        "remote": [x for x in rem.splitlines() if "fetch" in x],
        "branch": br.strip(),
        "dirty": len([x for x in st.splitlines() if x.strip()]),
        "terms": len(lexicon().get("terms", [])),
        "proposals": len(load_proposals_json_only()),
    }


def load_proposals_json_only() -> list:
    try:
        return _read_json(PROPOSALS, {}).get("proposals", [])
    except Exception:
        return []






if __name__ == "__main__":
    import io
    sys.stdout.reconfigure = getattr(sys.stdout, "reconfigure",
                                     lambda **k: None) and sys.stdout.reconfigure
    io.TextIOWrapper  # noqa
    sys.stdout.reconfigure(encoding="utf-8")
    print("公共词库同步自检")
    print("=" * 62)
    print("公共词库路径:", LEXICON)
    print("提案文件路径:", PROPOSALS)
    print("当前词条数:", len(lexicon().get("terms", [])))
    n = load_proposals()
    print("生成提案条数:", n)
    for t in load_proposals_json_only():
        print(f"   {t['src']!r} -> {t['dst']!r} (reporters={t['reporters']})")
    print()
    print("隐私自检：提案里只应有 src/dst/lang/reporters 四个字段")
    bad = [t for t in load_proposals_json_only()
           if set(t) - {"src", "dst", "lang", "reporters"}]
    print("   多余字段:", bad if bad else "无")
    print()
    print("（同步需要 git 凭据，按项目规范 的建议用 Credential Manager "
          "或 SSH key，不要把令牌写进 URL）")
