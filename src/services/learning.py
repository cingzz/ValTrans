# -*- coding: utf-8 -*-
# 作者: cing  ·  https://github.com/cingzz
# 许可: GPL-3.0 + 商业授权（闭源/商用需向作者申请授权），见 LICENSE 与 LICENSE-COMMERCIAL.md
#
"""v0.2.6 ②：云端兜底句子的自学习（用户确认后才入库）。

用户的原话要求（逐条落进设计）
--------------------------------
1.「队友说一句话，本地词库里面找不到，就上云端翻译」
2.「下次他又说同样的话…系统就可以自主地更新学习」
3.「一定要说很久，而不是说一两遍就自主学习了」   ← 关键约束
4.「当它加入本地词库的时候，软件要给我们用户提示，
    问我们是不是要加入本地词库」                  ← 必须人工确认

为什么必须这么保守
------------------
「说 2 次就自动入库」会直接把垃圾写进词库：
    ASR 误识别（"he is low" 听成 "he is love"）
    云端错译（"flash" 翻成"烟"）
一旦入库，这条错译会永久生效，且本地层会优先于云端 —— 错得更快更久。
所以阈值定得高：默认 8 次 + 跨 30 分钟 + 云端译文稳定（两次译文一致）。

数据流
------
    翻译请求 → 本地未命中 → 云端成功
                      ↓
              record_cloud_fallback(text, target, out)
                      ↓
              次数达标 + 时间跨够 + 译文稳定
                      ↓
              进入 candidates（候选，不影响翻译）
                      ↓
              用户在 UI 点「采纳」→ 写进 user_lexicon.json
                      ↓
              翻译时优先查 user_lexicon（用户教的最优先）

数据只存本地，不上传。
一次性脚本。
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# 阈值（用户强调「一定要说很久」——这些数是刻意保守的）
# ---------------------------------------------------------------------------
MIN_COUNT = 8              # 至少出现 8 次（一两绝不学）
MIN_SPAN_SEC = 30 * 60     # 且必须跨越 30 分钟（排除同一局的连说）
MAX_ENTRIES = 500          # 候选池上限，防无限膨胀
STALE_DAYS = 30            # 30 天没再出现就淡出


def _store_dir() -> Path:
    from ..core.config import CONFIG_DIR
    d = Path(CONFIG_DIR) / "learning"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _cand_path() -> Path:
    return _store_dir() / "candidates.json"


def _lex_path() -> Path:
    return _store_dir() / "user_lexicon.json"


_LOCK = threading.Lock()
_CACHE: dict | None = None


def _load() -> dict:
    global _CACHE
    with _LOCK:
        if _CACHE is not None:
            return _CACHE
        p = _cand_path()
        if p.exists():
            try:
                _CACHE = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                _CACHE = {}
        else:
            _CACHE = {}
        _CACHE.setdefault("entries", {})
        return _CACHE


def _save(d: dict) -> None:
    try:
        _cand_path().write_text(
            json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass


def _key(text: str, target: str) -> str:
    return f"{target}::{(text or '').strip().lower()}"


# ---------------------------------------------------------------------------
# 记录：每次云端兜底成功都调
# ---------------------------------------------------------------------------

def record_cloud_fallback(text: str, target: str, out: str) -> None:
    """记录一次云端兜底。只计数，不影响翻译结果。

    译文稳定性检查：连续两次译文必须一致才继续累计。
    模型输出会漂移（"他们下包了" / "他们在A点下包了"），
    不一致的说明这条翻译本身就不确定，更不该自动入库。
    """
    if not text or not out:
        return
    # ★ v0.2.16：src==dst = 云端根本没翻、兜底退回的原文。
    #   记进去会攒出「英文→英文」的假词条请用户采纳（采纳后经
    #   lexicon_lookup 永久压过云端）。自学习只学**真的翻过的**。
    if (text or "").strip() == (out or "").strip():
        return
    d = _load()
    k = _key(text, target)
    now = time.time()
    e = d["entries"].get(k)
    if e is None:
        e = {"src": text.strip(), "target": target, "dst": out.strip(),
             "count": 0, "first": now, "last": now, "consistent": 1}
        d["entries"][k] = e
    else:
        # 译文变了 -> 稳定性重置（说明这条翻译拿不准）
        if e.get("dst", "").strip() != out.strip():
            e["consistent"] = 1
            e["dst"] = out.strip()
        else:
            e["consistent"] = e.get("consistent", 1) + 1

    e["count"] = e.get("count", 0) + 1
    e["last"] = now

    # 超出上限：淘汰最久未出现的
    if len(d["entries"]) > MAX_ENTRIES:
        items = sorted(d["entries"].items(), key=lambda kv: kv[1].get("last", 0))
        for kk, _ in items[:len(d["entries"]) - MAX_ENTRIES]:
            d["entries"].pop(kk, None)

    _save(d)


# ---------------------------------------------------------------------------
# 查询候选
# ---------------------------------------------------------------------------

def _ready(e: dict, now: float) -> bool:
    """是否达到「可以问用户了」的门槛。"""
    if e.get("count", 0) < MIN_COUNT:
        return False
    if now - e.get("first", now) < MIN_SPAN_SEC:
        return False
    if e.get("consistent", 0) < 2:      # 译文至少稳定 2 次
        return False
    return True


def list_candidates(include_all: bool = False) -> list:
    """返回候选列表，按进度排序。

    include_all=False 只返回「够格问用户」的；
    include_all=True 返回全部（用于 UI 显示进度条）。
    """
    d = _load()
    now = time.time()
    out = []
    for e in d["entries"].values():
        if now - e.get("last", 0) > STALE_DAYS * 86400:
            continue
        if not include_all and not _ready(e, now):
            continue
        cnt = e.get("count", 0)
        span = int(now - e.get("first", now))
        out.append({
            "src": e.get("src", ""),
            "target": e.get("target", "zh"),
            "dst": e.get("dst", ""),
            "count": cnt,
            "span_sec": span,
            "consistent": e.get("consistent", 1),
            "ready": _ready(e, now),
            "progress": min(1.0, cnt / MIN_COUNT),
        })
    out.sort(key=lambda x: (not x["ready"], -x["count"]))
    return out




# ---------------------------------------------------------------------------
# 采纳 / 忽略
# ---------------------------------------------------------------------------

def load_lexicon() -> dict:
    """用户已采纳的词库。翻译时优先于内置表。"""
    p = _lex_path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def lexicon_lookup(text: str, target: str):
    """查用户词库。命中返回 (译文, 'user')，否则 (None, '')。"""
    lex = load_lexicon()
    if not lex:
        return None, ""
    k = _key(text, target)
    v = lex.get(k)
    if v:
        return v, "user"
    return None, ""


def adopt(src: str, dst: str, target: str = "zh") -> bool:
    """用户点「采纳」：写入用户词库并清掉候选。"""
    if not src or not dst:
        return False
    p = _lex_path()
    lex = load_lexicon()
    lex[_key(src, target)] = dst.strip()
    try:
        p.write_text(json.dumps(lex, ensure_ascii=False, indent=2),
                     encoding="utf-8")
    except OSError:
        return False
    # 从候选池移除
    d = _load()
    d["entries"].pop(_key(src, target), None)
    _save(d)
    return True


def ignore(src: str, target: str = "zh") -> bool:
    """用户点「忽略」：清掉候选，且记成「别再问我」。"""
    d = _load()
    k = _key(src, target)
    e = d["entries"].get(k)
    if e is not None:
        e["ignored"] = True
        d["entries"][k] = e
        _save(d)
    return True




# ---------------------------------------------------------------------------
# 自动加入模式（用户勾了「下次不用询问」之后生效）
# ---------------------------------------------------------------------------

def _pref_path():
    return _store_dir() / "prefs.json"


def get_prefs() -> dict:
    """学习偏好。目前只有 auto_add（下次不用询问，自动加入）。"""
    p = _pref_path()
    if not p.exists():
        return {"auto_add": False}
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        return {"auto_add": bool(d.get("auto_add", False))}
    except Exception:
        return {"auto_add": False}


def set_pref(k: str, v) -> dict:
    d = get_prefs()
    d[k] = v
    try:
        _pref_path().write_text(json.dumps(d, ensure_ascii=False, indent=2),
                                encoding="utf-8")
    except OSError:
        pass
    return d


def auto_adopt_ready() -> list:
    """自动模式下：把所有达标的候选直接入库。

    仍受同一套阈值约束（≥8 次 / 跨 30 分钟 / 译文稳定），
    只是不再问用户。返回被采纳的条目列表。
    """
    if not get_prefs().get("auto_add"):
        return []
    done = []
    for c in list_candidates():
        if adopt(c["src"], c["dst"], c["target"]):
            done.append(c)
    return done




def stats() -> dict:
    """学习系统统计，给设置页/浮窗用。"""
    d = _load()
    now = time.time()
    ready = len(list_candidates())
    total = 0
    for e in d["entries"].values():
        if not e.get("ignored"):
            total += e.get("count", 0)
    return {
        "tracked": len(d["entries"]),
        "ready": ready,
        "cloud_hits": total,
        "lexicon": len(load_lexicon()),
        "thresholds": {
            "min_count": MIN_COUNT,
            "min_span_sec": MIN_SPAN_SEC,
            "min_consistent": 2,
        },
    }


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    print("=== 自学习系统自检 ===")
    print("阈值:", f"≥{MIN_COUNT} 次 + 跨 ≥{MIN_SPAN_SEC // 60} 分钟 + 译文稳定 ≥2 次")
    print()
    print("模拟：同一句被云端翻译 10 次（全部一致）")
    for i in range(10):
        record_cloud_fallback("they gonna stack B main", "zh", "他们要堆B大")
    # 篡改 first 时间以模拟"说很久"
    d = _load()
    for k in d["entries"]:
        d["entries"][k]["first"] = time.time() - 3600
    _save(d)

    c = list_candidates()
    print(f"  够格的候选: {len(c)}")
    for e in c:
        print(f"    {e['src']!r} -> {e['dst']!r}  "
              f"({e['count']}次/跨{e['span_sec'] // 60}分钟/稳定{e['consistent']})")

    print()
    print("模拟：只说 2 次（用户明确说不能学）")
    for i in range(2):
        record_cloud_fallback("rare callout nobody says", "zh", "冷门报点")
    c2 = list_candidates()
    print(f"  够格的候选: {len(c2)}（应为 1，只有前面那句）")
    print(f"  被挡住的: 'rare callout nobody says' 在候选里吗: "
          f"{'rare callout nobody says' in [e['src'] for e in c2]}")

    print()
    print("=== 采纳 ===")
    if c:
        ok = adopt(c[0]["src"], c[0]["dst"], c[0]["target"])
        print(f"  采纳 {c[0]['src']!r}: {ok}")
        print(f"  查词库: {lexicon_lookup(c[0]['src'], 'zh')}")
    print()
    print("统计:", stats())