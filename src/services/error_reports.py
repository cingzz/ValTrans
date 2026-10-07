# -*- coding: utf-8 -*-
# 作者: cing  ·  https://github.com/cingzz
# 许可: GPL-3.0 + 商业授权（闭源/商用需向作者申请授权），见 LICENSE 与 LICENSE-COMMERCIAL.md
#
"""误报上报（本地版）—— 用户教的第一份样本。

需求背景设计要点逐条落进实现）
----------------------------------------------
> 「之后可以在里面添加一个『误报』功能，当用户遇到翻译报错时，
>    可以让用户自己去提交误报。提交方式有两种：
>    1. 手动添加。2. 找到历史消息里的某一条，直接点进去，
>       选择『提交误报』。
>    如果提交的人多，它就显示重新去识别翻译；如果人少，就暂时不变，
>    或者就给他自己本地的调一下就好了。」

设计要点
--------
1. **两个入口共用一个出口**：`report()` 是唯一写入口，
   手动填和「历史里点那条」都调它 —— 不做两份实现
   （同一个判断只能有一份实现）。

2. **分级规则**（用户定的「人多人少」）在本地版就固化成可测试的常量，
   将来接联网时直接复用同一套判据：

       同一原句 + 同一纠错译文 = 1 组「共识」
       1~2 组  -> 只改上报者自己本地（立即生效）
       >= 3 组且组内唯一       -> 升级为「可信」，本地立即生效 + 标记可上报
       >= 3 组但组内有分歧     -> **不自动采纳任何一方**，标记「需人工审」

   最后一条是我加的：**多数不等于对**。游戏黑话有地域差异，
   硬投票会把少数但正确的说法覆盖掉（「大残」vs「残血」vs「快没血了」）。
   分歧时宁可交给人看，也不能让系统挑一个当标准。

3. **立刻生效**：上报后立刻写进 `tm.py`（kind="user"），
   同一句话下一次翻译就命中，0 额外延迟 —— 不用等云端。

4. **只存用户主动提交的那一条**，不采集完整对局记录。
   语音是个人数据，这条边界写死在代码里，不靠自觉（用户已认可的原则）。
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

_LOCK = threading.Lock()
_CACHE: dict | None = None

# 分级门槛（用户定的「人多人少」，固化为常量便于测试）
ADOPT_MIN_DISTINCT_REPORTS = 3      # >= 3 个**不同上报者**投同一个纠错
# 少于这个数 -> 只改上报者本地
LOCAL_ONLY_BELOW = ADOPT_MIN_DISTINCT_REPORTS
# 上报者身份：本机用一个随机 id（不上传、不关联账号）
# 联网版再换成真正的 per-user id；本地版只需要「同一个人不重复刷票」


def _store_dir() -> Path:
    return Path(os.environ.get("APPDATA", Path.home())) / "ValTrans"


def _path() -> Path:
    return _store_dir() / "error_reports.json"


def _load() -> dict:
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    try:
        d = json.loads(_path().read_text(encoding="utf-8"))
        if not isinstance(d, dict) or "items" not in d:
            d = {"items": {}, "me": _local_uid()}
    except Exception:
        d = {"items": {}, "me": _local_uid()}
    _CACHE = d
    return d


def _save(d: dict) -> None:
    try:
        p = _path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def _local_uid() -> str:
    """本机稳定随机 id：只用于「同一个人不重复刷票」，不含任何身份信息。"""
    import hashlib
    import uuid
    key = _store_dir() / ".uid"
    try:
        if key.exists():
            return key.read_text(encoding="utf-8").strip()
        u = uuid.uuid4().hex
        key.write_text(u, encoding="utf-8")
        return u
    except Exception:
        return hashlib.blake2b(str(os.environ.get("COMPUTERNAME", "")),
                               digest_size=8).hexdigest()


# ---------------------------------------------------------------------------
# 上报（两个入口的唯一出口）
# ---------------------------------------------------------------------------
def report(src: str, shown: str, correct: str,
           lang: str = "en", from_history: bool = False) -> dict:
    """提交一条误报。

    参数
      src        队友原话（检测到的源文本）
      shown      当时显示给用户的译文（可能是错的）
      correct    用户认为对的译文
      from_history 是否由「历史里点那条」触发（仅作记录，便于日后
                区分两个入口的使用情况）

    返回分级结果，供 UI 直接显示。
    """
    src, shown, correct = (src or "").strip(), (shown or "").strip(), \
        (correct or "").strip()
    if not src or not correct:
        return {"ok": False, "msg": "原话和正确译文不能为空"}
    if correct == shown:
        return {"ok": False, "msg": "译文没有变化，无需上报"}

    with _LOCK:
        d = _load()
        k = f"{lang}|{src.lower()}"
        item = d["items"].get(k)
        if item is None:
            item = {"src": src, "shown": shown, "lang": lang,
                    "proposals": {}, "t": time.time()}
            d["items"][k] = item
        # proposals: {纠错译文: {上报者uid: 次数}}
        prop = item["proposals"].setdefault(correct, {})
        uid = d.get("me") or _local_uid()
        prop[uid] = prop.get(uid, 0) + 1
        item["t"] = time.time()
        _save(d)

    return _classify(k)


def _distinct_reporter_count(item: dict, correct: str) -> int:
    prop = item.get("proposals", {}).get(correct, {})
    return len([u for u, n in prop.items() if n >= 1])


def _classify(key: str) -> dict:
    """分级 —— 用户定的「人多人少」，逻辑集中在这一个函数里。"""
    d = _load()
    item = d["items"].get(key)
    if not item:
        return {"ok": False, "msg": "未找到该条目"}

    proposals = item.get("proposals", {})
    # 只统计达到共识门槛（>=3 个不同上报者）的纠错
    strong = [c for c in proposals
              if _distinct_reporter_count(item, c) >= ADOPT_MIN_DISTINCT_REPORTS]

    if not strong:
        # 人少：只改上报者自己本地，立刻生效
        best = max(proposals, key=lambda c: sum(proposals[c].values()))
        n = _distinct_reporter_count(item, best)
        _apply_local(item, best)
        return {"ok": True, "level": "local", "reports": n,
                "dst": best,
                "msg": f"已按你的说法在本机生效（当前 {n} 人上报，"
                       f"满 {ADOPT_MIN_DISTINCT_REPORTS} 人可升级为共识）"}

    if len(strong) > 1:
        # 有分歧：不自动采纳任何一方，交给人看
        return {"ok": True, "level": "conflict",
                "candidates": strong,
                "msg": f"多人上报但说法不一致（{len(strong)} 种），"
                       f"暂不自动改，以免少数正确说法被覆盖"}

    # 共识：采纳
    _apply_local(item, strong[0])
    return {"ok": True, "level": "consensus", "dst": strong[0],
            "msg": "已有足够多的人报同一说法，已作为共识生效"}


def _apply_local(item: dict, dst: str) -> None:
    """写进翻译记忆 -> 同一句话下一次翻译就命中，0 额外延迟。"""
    try:
        from . import tm
        tm.record(item["src"], dst, item.get("lang", "en"), "user")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# 查询（给 UI 用）
# ---------------------------------------------------------------------------
def list_reports(limit: int = 50) -> list[dict]:
    """列出待审/已知的误报，供「误报中心」页面显示。"""
    d = _load()
    out = []
    for item in d["items"].values():
        props = item.get("proposals", {})
        out.append({
            "src": item.get("src"),
            "shown": item.get("shown"),
            "lang": item.get("lang", "en"),
            "proposals": [{"dst": c, "reporters": _distinct_reporter_count(item, c),
                           "votes": sum(props[c].values())}
                          for c in props],
            "t": item.get("t", 0),
        })
    out.sort(key=lambda x: -x["t"])
    return out[:limit]




def export_public() -> list[dict]:
    """导出**可公开**的部分（将来提交到公共词库仓库用）。

    隐私边界（用户已认可）：只导出**用户主动提交的那一条文本**，
    不含时间戳、不含设备信息、不含完整对局记录。

    **有分歧的条目一律不导出**（v0.2.11 修）：实测漏过一次 ——
    一条 item 同时有 2 种各达门槛的纠错时，两个都被导出，
    等于把「有争议」当成「已定论」推到公共库，让没参与的人白拿一个
    可能是错的答案。有分歧的必须先人工审（见 `_classify` 的 conflict 分支）。
    """
    out = []
    d = _load()
    for item in d["items"].values():
        strong = [c for c in item.get("proposals", {})
                  if _distinct_reporter_count(item, c) >= ADOPT_MIN_DISTINCT_REPORTS]
        if len(strong) != 1:
            continue                       # 0 个（没人到门槛）或 >1 个（有分歧）
        out.append({"src": item["src"], "dst": strong[0],
                    "lang": item.get("lang", "en")})
    return out


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    print("误报上报本地版自检")
    print("=" * 66)
    S = "they are setting up on a"
    print(f"1) 首次上报（人少 -> 只改本地）")
    print("  ", report(S, "他们架在A了。", "他们在A点架枪"))
    print()
    print("2) 提交空的 / 无变化的（应被拒）")
    print("   空:", report("", "x", "y"))
    print("   无变化:", report(S, "他们在A点架枪", "他们在A点架枪"))
    print()
    print("3) 模拟 3 个不同上报者投同一说法 -> 共识")
    import src.services.error_reports as E
    d = E._load()
    for i in range(3):
        item = d["items"][f"en|{S.lower()}"]
        item["proposals"].setdefault("他们在A点架枪", {})[f"user{i}"] = 1
    print("  ", E._classify(f"en|{S.lower()}"))
    print()
    print("4) 分歧：多人但说法不一致 -> 不自动采纳")
    print("  ", report(S, "x", "他们在A摆好了"))
    d2 = E._load()
    it = d2["items"][f"en|{S.lower()}"]
    for i in range(5):
        it["proposals"].setdefault("他们在A摆好了", {})[f"other{i}"] = 1
    print("  ", E._classify(f"en|{S.lower()}"))
    print()
    print("5) 立即生效验证（同一句话再翻一次）")
    from src.services.local_rules import translate_local
    from src.services import provenance as P
    P.VERIFIED.setdefault("_TRANSLATE_FIRST", {})
    from src.services import tm
    print("   TM 检索:", [h["dst"] for h in tm.retrieve(S, "en")][:3])
    print()
    print("6) 可公开导出（隐私边界）")
    for x in E.export_public():
        print("   ", x)
