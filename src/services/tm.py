# -*- coding: utf-8 -*-
# 作者: cing  ·  https://github.com/cingzz
# 许可: GPL-3.0 + 商业授权（闭源/商用需向作者申请授权），见 LICENSE 与 LICENSE-COMMERCIAL.md
#
"""翻译记忆（Translation Memory）+ 模糊匹配检索。

为什么做这个
------------
需求背景：
> 「能不能做个自学习的那种系统吗？就是它玩得越久，翻译得越久，它越准确，
>   不是靠我们上面讲的收录词、收录词语进词库的那种，而是他翻译越久又越准的那种」

现有 `learning.py` 方向是错的：它学的是「**云端自己翻出来的译文**出现 8 次」。
于是云端把 `they are setting up` 翻成「他们正在设立」，出现 8 次后就变成
「已确认的正确译法」——**把错误一起学了**，而且本地层优先于云端，
错得更快更久。

业界标准解法不是「统计谁出现得多」，而是**翻译记忆 + 模糊匹配**：

    Moslem et al., *Adaptive Machine Translation with Large Language Models*
    (EACL 2023, 被引 370+)
    做法：翻译前先从**已确认过的译文**里检索语义最接近的 2~3 条，
    连同待译句一起塞进 prompt 当 few-shot 示例。
    **论文实测：效果超过 Google Translate 和 DeepL。**

为什么这条路适合本项目：
  1. 学习信号来自**确认过的译文**，不是模型自己的输出 → 学不进错误
  2. **不需要训练任何模型**（用户明确禁止本地大模型）→ 只是 prompt 多几行
  3. 越玩历史越多 → 检索越准 → 越敢本地出字 → 越快 → 越玩得多

相似度算法：为什么不能直接用 SequenceMatcher
------------------------------------------
韩语/日语**没有空格**，且是黏着语（助词粘连在词根后面）：

    '저기 미드에서 기다려'     <- 13 个字符，只有 2 个空格
    'hearing heaven enemy'     <- 有完整词边界

纯编辑距离对前者几乎全是噪声（差一个助词就完全不同），
纯词元重叠对前者又因为切不出词而失效。
所以**双通道取最大**：
  · 词元通道（空格切分，命中整词）—— 适合英语
  · 字符 n-gram 通道（2-gram Jaccard/重叠）—— 适合日韩，
    它对「多一个助词」这类黏着变体天然宽容（n-gram 大部分仍重叠）

外加一条**同一句精确命中**直接满分（缓存层已经处理，这里兜底）。
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from pathlib import Path

_LOCK = threading.Lock()
_CACHE: dict | None = None

MAX_ENTRIES = 2000          # 记忆库上限，超了淘汰最久没用的
MAX_RETRIEVE = 3            # 注入 prompt 的示例条数（论文用 2~5）
MIN_SIM = 0.34              # 低于这个相似度就别注入了（噪声会干扰模型）


def _store_dir() -> Path:
    return Path(os.environ.get("APPDATA", Path.home())) / "ValTrans"


def _tm_path() -> Path:
    return _store_dir() / "tm.json"


def _load() -> dict:
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    try:
        d = json.loads(_tm_path().read_text(encoding="utf-8"))
        if not isinstance(d, dict) or "entries" not in d:
            d = {"entries": {}}
    except Exception:
        d = {"entries": {}}
    _CACHE = d
    return d


def _save(d: dict) -> None:
    try:
        p = _tm_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass          # 记忆库写失败绝不能影响翻译


# ---------------------------------------------------------------------------
# 相似度：词元通道 + 字符 n-gram 通道，取最大
# ---------------------------------------------------------------------------
_CJK = re.compile(r"[\u3040-\u30ff\uac00-\ud7af\u4e00-\u9fff]")
_WORD = re.compile(r"[a-z0-9']+|[^\s]")     # 英语按词，日韩按字


def _tokens(s: str) -> set[str]:
    return {t for t in _WORD.findall((s or "").lower()) if t}


def _bigrams(s: str) -> set[str]:
    s = re.sub(r"\s+", "", (s or "").lower())
    if len(s) < 2:
        return {s} if s else set()
    return {s[i:i + 2] for i in range(len(s) - 1)}


def _overlap(a: set, b: set) -> float:
    """重叠系数（比 Jaccard 宽容：查询串更短时也能给出有效分数）。"""
    if not a or not b:
        return 0.0
    inter = len(a & b)
    return inter / min(len(a), len(b))


def similarity(a: str, b: str) -> float:
    """0..1。词元通道与字符 n-gram 通道取最大，再轻微加权词元通道。"""
    a_l, b_l = (a or "").strip().lower(), (b or "").strip().lower()
    if not a_l or not b_l:
        return 0.0
    if a_l == b_l:
        return 1.0
    tok = _overlap(_tokens(a_l), _tokens(b_l))
    big = _overlap(_bigrams(a_l), _bigrams(b_l))
    # 双通道取大，但对「纯 CJK 无空格」输入略偏 n-gram
    if _CJK.search(a_l) or _CJK.search(b_l):
        return max(big, tok * 0.9)
    return max(tok, big * 0.9)


# ---------------------------------------------------------------------------
# 写入
# ---------------------------------------------------------------------------
def record(src: str, dst: str, lang: str = "en", src_kind: str = "user") -> bool:
    """记一条**已确认**的译文对。

    `src_kind` 决定它将来能被谁用：
      user  —— 用户手动确认/纠正（最高可信，可作为 few-shot 示例）
      seed  —— 从已核实词表播种（可信）
      cloud —— 云端自己翻的（**不可信**，仅留档，不参与检索）
    """
    src, dst = (src or "").strip(), (dst or "").strip()
    if not src or not dst or src == dst:
        return False
    with _LOCK:
        d = _load()
        k = f"{lang}|{src.lower()}"
        e = d["entries"].get(k)
        if e is None:
            e = {"src": src, "dst": dst, "lang": lang, "kind": src_kind,
                 "hits": 0, "t": time.time()}
            d["entries"][k] = e
        else:
            # 用户重新确认会覆盖旧译文（这才是「学习」）
            e["dst"] = dst
            e["kind"] = src_kind
            e["t"] = time.time()
        # 淘汰最久没用的
        if len(d["entries"]) > MAX_ENTRIES:
            items = sorted(d["entries"].items(), key=lambda kv: kv[1].get("t", 0))
            for kk, _ in items[:len(d["entries"]) - MAX_ENTRIES]:
                d["entries"].pop(kk, None)
        _save(d)
    return True




# ---------------------------------------------------------------------------
# 检索
# ---------------------------------------------------------------------------
def _anchor_terms_of(text: str) -> set:
    """文本里出现的、已核实的游戏术语集合（用作 few-shot 示例的锚）。

    只用 cross_check 的 CJK 索引（已担保词表的唯一来源），不另建词表。
    英文/数字条目不算 —— CJK 侧要做锚点，靠的是「 BUMiddleware」这类
    日/韩/中术语（サイト / 미드 / 리스폰…），英文锚点在日句子里天然不存在。
    """
    try:
        from .cross_check import cjk_index
    except Exception:
        return set()
    t = (text or "")
    if not t:
        return set()
    return {k for k in cjk_index() if k in t}


def retrieve(src: str, lang: str = "en", limit: int = MAX_RETRIEVE,
             min_sim: float = MIN_SIM) -> list[dict]:
    """检索与 `src` 最接近的**可信**译文对，按相似度降序。

    排除 src_kind == "cloud"：云端自己的输出不算知识，
    拿来当示例等于把模型的偏见喂回给它自己（这正是 learning.py 的老毛病）。
    """
    src = (src or "").strip().lower()
    if not src:
        return []
    d = _load()
    # CJK 侧的相似度不可信，阈值提到 0.85（见下方 _anchored 说明）
    _CJK_LANGS = ("ja", "ko", "zh", "yue")
    _is_cjk = lang in _CJK_LANGS or bool(_CJK.search(src or ""))
    _thr = max(min_sim, 0.85) if _is_cjk else min_sim
    _anchor_terms = _anchor_terms_of(src) if _is_cjk else None
    out = []
    for e in d["entries"].values():
        if e.get("kind") == "cloud":
            continue
        if lang and e.get("lang") and e["lang"] != lang:
            continue
        sim = similarity(src, e.get("src", ""))
        if sim < _thr:
            continue
        # ★ 术语锚定：CJK 侧光看相似度会注入错主题的示例（实测 ja3 被塞进
        #   「スモーク→烟」，而那句讲的是龙/重生）。要求示例与当前句
        #   **至少共享一个游戏术语**，否则宁可不注入。
        if _anchor_terms is not None:
            ex_terms = _anchor_terms_of(e.get("src", ""))
            if not (_anchor_terms & ex_terms):
                continue
        out.append({"src": e["src"], "dst": e["dst"], "sim": sim,
                    "kind": e.get("kind", "seed")})
    out.sort(key=lambda x: -x["sim"])
    return out[:limit]


def as_examples(src: str, lang: str = "en") -> str:
    """把检索结果拼成可直接塞进 prompt 的示例块（没有就返回空串）。"""
    hits = retrieve(src, lang)
    if not hits:
        return ""
    lines = [f"  「{h['src']}」-> 「{h['dst']}」" for h in hits]
    return ("下面是同一队伍/同一游戏里**已确认**的说法，"
            "请沿用同样的译法和口吻：\n" + "\n".join(lines))


def mark_used(src: str, lang: str = "en") -> None:
    """命中的示例用过了，刷新时间戳（LRU 抗淘汰）。"""
    k = f"{lang}|{(src or '').strip().lower()}"
    with _LOCK:
        d = _load()
        e = d["entries"].get(k)
        if e is not None:
            e["t"] = time.time()
            e["hits"] = e.get("hits", 0) + 1


def stats() -> dict:
    d = _load()
    by_kind: dict[str, int] = {}
    for e in d["entries"].values():
        by_kind[e.get("kind", "?")] = by_kind.get(e.get("kind", "?"), 0) + 1
    return {"total": len(d["entries"]), "by_kind": by_kind}


# ---------------------------------------------------------------------------
# 播种：从已核实词表初始化
# ---------------------------------------------------------------------------
def seed_from_verified() -> int:
    """把**有担保的**词条播种进记忆库。

    只播 provenance 认可的 —— 这正好和来源闸门复用同一套判据：
    没担保的猜测不进记忆库，避免用「可能错的东西」给模型做 few-shot。

    **同键只播一次，先到先得**（顺序与 translate_local 的查表顺序一致）。
    这不是洁癖：实测 `_PLACE['b main']='B大'` 先播，
    `_TRANSLATE_FIRST['b main']='B主'` 后播会**覆盖**它，
    记忆库里就留下了 'b main' -> 'B主' 这个错译，
    然后被当成 few-shot 示例喂给模型 —— 记忆库会把同键分歧**放大**。
    """
    from src.services import provenance as P
    import src.services.local_rules as L
    import src.services.cjk_slang as C

    seen: set[str] = set()
    pairs: list[tuple[str, str, str]] = []      # (src, dst, lang)

    def _add(src, dst, lang):
        if not isinstance(src, str) or not isinstance(dst, str):
            return
        src, dst = src.strip(), dst.strip()
        if not src or not dst or src == dst:
            return
        k = f"{lang}|{src.lower()}"
        if k in seen:
            return                                  # 同键已播，跳过
        seen.add(k)
        pairs.append((src, dst, lang))

    for tbl in ("_PLACE", "_ACT", "_GEAR", "_REPLY", "_TRANSLATE_FIRST",
                "_V25"):
        t = getattr(L, tbl, {})
        for k, v in t.items():
            if not isinstance(v, str) or not v.strip():
                continue
            if not P.is_verified(tbl, k):
                continue
            # 只播纯英文键（复合句对 few-shot 没用且占地方）
            if not re.fullmatch(r"[a-z0-9' \-]{1,28}", str(k).strip().lower()):
                continue
            _add(str(k), v, "en")

    for tbl, lang in (("KO_RULES", "ko"), ("KO_PHRASES", "ko"),
                      ("JA_RULES", "ja"), ("JA_PHRASES", "ja")):
        t = getattr(C, tbl, [])
        for k, v in t:
            if isinstance(v, str) and v.strip() and P.is_verified(tbl, k):
                _add(k, v, lang)

    # 英雄/武器官方译名（agents.py 是唯一来源，本身就经过联网核实）
    try:
        from src.services.agents import AGENTS, WEAPONS
        for en, zh in list(AGENTS.items()) + list(WEAPONS.items()):
            _add(en, zh, "en")
    except Exception:
        pass

    n = 0
    for src, dst, lang in pairs:
        if record(src, dst, lang, "seed"):
            n += 1
    return n


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    print("播种...", seed_from_verified(), "条")
    print("统计:", stats())
    print()
    print("相似度自检（不同语种各测一组）：")
    for a, b in [("go b main", "im going b"),
                 ("저기 미드에서 기다려", "저기 미드에서 기다려"),
                 ("저기 미드에서 기다려", "미드 기다려"),
                 ("go b main", "저기 미드에서 기다려"),
                 ("clutch 1v3", "they clutched 1v3"),
                 ("flash me", "flash")]:
        print(f"  {a!r:<28} vs {b!r:<22} -> {similarity(a, b):.3f}")
    print()
    for q, lang in [("go b main", "en"), ("저기 기다려", "ko"),
                    ("going to mid", "en")]:
        print(f"检索 {q!r} ({lang}):")
        for h in retrieve(q, lang):
            print(f"    sim={h['sim']:.3f}  {h['src']!r} -> {h['dst']!r}")
        if not retrieve(q, lang):
            print("    （无命中）")
