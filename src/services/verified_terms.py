# -*- coding: utf-8 -*-
"""词条核实的**持久化登记表**。

为什么要单独存一个文件
----------------------
`provenance.VERIFIED` 是**运行时**数据：进程退出就没了。
如果核实成果只存在内存里，下次改一行代码就全丢了。

所以：核实结论落在这里（版本控制），`provenance.py` 启动时加载。

这个文件是**审阅对象**，不是代码 —— 每一条都必须能回答：
    「你凭什么说它对？」
所以每条都带 `src`（来源说明）。写不出 `src` 的条目不许进来
（`load()` 会直接拒绝），这样「来源」就不是靠自觉了。

格式
----
    {
      "_PLACE": {
        "stairs": "英汉字典对应词，非 VALORANT 专属叫法（2026-10-03）",
        ...
      }
    }
新增批次时用 `tests/lexicon_review.py accept <表> <键> "<来源>"`
或直接编辑本文件（建议带来源说明，便于 review）。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
REGISTRY = _HERE / "verified_terms.json"


def load() -> dict[str, dict[str, str]]:
    """加载核实登记表。**缺 `src` 的条目直接拒绝**（防止空来源蒙混）。"""
    try:
        data = json.loads(REGISTRY.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}
    out: dict[str, dict[str, str]] = {}
    pins: dict[str, dict[str, str]] = {}
    bad: list[str] = []
    # ★ v0.2.16：清空必须发生在**填充之前**——旧顺序是先填后 clear，
    #   每次进程启动 META 必为空（读写往返又不闭合）。
    META.clear()
    _PINNED.clear()
    for table, terms in data.items():
        if not isinstance(terms, dict):
            continue
        clean, pin = {}, {}
        for k, v in terms.items():
            if not isinstance(k, str) or not k.strip():
                bad.append(f"{table}: 空键")
                continue
            why, zh = v, None
            extra = {}
            if isinstance(v, dict):
                # v0.2.11：{"why": 来源, "zh": 钉死的译文, "level": 来源可信度}
                why, zh = v.get("why", ""), v.get("zh")
                # **其它字段必须原样保留**。之前只留 why，把 `level`
                # 悄悄丢掉了 —— 于是「已打上可信度标记」的条目
                # 下次读回来又是「没有标记」，读写往返不闭合。
                for _k2, _v2 in v.items():
                    if _k2 not in ("why", "zh"):
                        extra[_k2] = _v2
                if zh is not None and not (
                        isinstance(zh, str) and zh.strip()):
                    bad.append(f"{table}[{k!r}] 钉死的译文不是非空字符串")
                    continue
            if not isinstance(why, str) or not why.strip():
                # 来源为空 = 「我不知道凭什么」，不允许进白名单
                bad.append(f"{table}[{k!r}] 来源为空")
                continue
            clean[k.strip()] = why.strip()
            for _k2, _v2 in extra.items():
                # level 这类元数据挂到 load() 返回的字符串值上不方便，
                # 所以单独存一份映射，供 audit_sources.py 用。
                META.setdefault(table, {}).setdefault(k.strip(), {}).update(extra)
            if isinstance(zh, str) and zh.strip():
                # ★ v0.2.16：pinned() 查询用 .strip().lower()，save() 落盘
                #   也 lower——load() 这边必须同样 lower，否则大小写混合键
                #   经启动路径钉死查询会 miss
                pin[k.strip().lower()] = zh.strip()
        out[table] = clean
        if pin:
            pins[table] = pin
    if bad:
        print(f"[verified_terms] 拒绝 {len(bad)} 条不合格登记：{bad[:5]}",
              file=sys.stderr)
    _PINNED.update(pins)
    return out


# 表 -> 键 -> 额外元数据（level 等，非钉死字段）
META: dict = {}

# 表 -> 键 -> 钉死的译文（只有明确钉过的键才在里面）
_PINNED: dict[str, dict[str, str]] = {}


def pinned(table: str, key: str) -> str | None:
    """该键是否**钉死了译文**；没钉过返回 None。"""
    return _PINNED.get(table, {}).get((key or "").strip().lower())


def save(data: dict[str, dict[str, str]]) -> int:
    """写回登记表，返回写入条数。

    v0.2.11：**写盘后必须同步刷新 `_PINNED`**。
    之前只写文件、不动 `_PINNED`，于是刚登记的条目立刻查不到钉死值，
    `is_verified()` 照样放行 —— 而且是**静默**放行，钉死机制等于没生效。
    这个 bug 是 `tests/audit_pinned_values.py` 的 B 段自证抓出来的：
    机制写完看着没问题，一跑就露馅。
    """
    n = 0
    for terms in data.values():
        n += len(terms)
    REGISTRY.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")
    # 用刚写出去的内容刷新缓存（不重读文件：省一次 IO，也避免读到自己
    # 还没落完的内容）
    fresh: dict[str, dict[str, str]] = {}
    for table, terms in data.items():
        if not isinstance(terms, dict):
            continue
        pin = {}
        for k, v in terms.items():
            if isinstance(k, str) and isinstance(v, dict):
                zh = v.get("zh")
                if isinstance(zh, str) and zh.strip():
                    pin[k.strip().lower()] = zh.strip()
        if pin:
            fresh[table] = pin
    _PINNED.clear()
    _PINNED.update(fresh)
    META.clear()
    for _t, _terms in data.items():
        if not isinstance(_terms, dict):
            continue
        for _k, _v in _terms.items():
            if isinstance(_v, dict):
                _x = {a: b for a, b in _v.items() if a not in ('why','zh')}
                if _x:
                    META.setdefault(_t, {})[_k] = _x
    return n


if __name__ == "__main__":
    import sys as _s
    _s.stdout.reconfigure(encoding="utf-8")
    d = load()
    tot = sum(len(v) for v in d.values())
    print(f"登记表：{REGISTRY}")
    print(f"已登记 {tot} 条，覆盖 {len(d)} 张表")
    for t, terms in sorted(d.items()):
        print(f"  {t:<20} {len(terms)} 条")
    print()
    print("约定：每条必须有 src（来源说明）。写不出来源的不要登记。")
