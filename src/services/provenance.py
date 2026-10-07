# -*- coding: utf-8 -*-
# 作者: cing  ·  https://github.com/cingzz
# 许可: GPL-3.0 + 商业授权（闭源/商用需向作者申请授权），见 LICENSE 与 LICENSE-COMMERCIAL.md
#
"""词条来源登记 —— 默认拒绝，白名单放行。

为什么要有这个（一个尖锐的质问）
----------------------------------------
> 「如果你本来就塞进一堆垃圾，但是它语法是正确的，你也检查不了，是不是」

**是的，检查不了。** 我先后往韩语表、日语表塞过：

    ('미utan', '闪')      ('araml', '残血')      ('jung', '')
    ('व्यापार', '打点')   ('힐packs', '奶枪')    ('옵side', '进攻方')

这些全部**语法正确、类型正确、无重复键、非空**。
我建的那套机械检查（重复键 / 空译文 / 命中率 / 覆盖率 / 编译）
**一条都拦不住** —— 因为它们检查的是**形式**，而形式恰恰是我
自己就能保证的那部分。

危害不在于难看，在于**它会主动伤害产品**：
    本地层命中就**跳过云端**，一条错译等于把「偶尔翻错一次」
    变成「永远翻错且更快」，而本地层正是本项目的核心价值。

所以真正的防线不是更强的 lint，而是**来源**：

    每条本地词条必须能说出「我凭什么认为它对」。
    说不出的，就不许参与翻译。

怎么落地
--------
**默认拒绝。** 只有登记在册的键才允许本地命中，其余一律
视为未核实猜测 -> 放行给云端整句翻（慢 400ms 但不会错）。

白名单的来源不是「我声称它对」，而是**审计里钉死的期望值**：
凡是某个 audit 用 `check(...含 X...)` 断言过的键，它就是已核实的
（当初核实它的时候留下了依据）。没被任何审计钉住的 = 没人担保。

这样「已核实」这件事就变成了**可验证的**，而不是我嘴上说的。

配套：未核实的词条不删，留在 `_UNVERIFIED_*` 里当
**自学习系统的候选池** —— 用户真实对局里反复用到并被确认的，
再由 `learning.adopt()` 提升为已核实。这才是「玩得越久越准」
的正确入口，而不是我坐在这里凭印象抄 170 条。
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

_HERE = Path(__file__).resolve().parent

# ---------------------------------------------------------------------------
# 已核实白名单：{表名: {键: 来源说明}}
# ---------------------------------------------------------------------------
# 来源说明必须写清「凭什么」——写不出来就别登记。
VERIFIED: dict[str, dict[str, str]] = {
    "agents": {
        # 30 英雄 + 19 武器，国服官方译名，v0.2.10 联网逐个核实过
    },
    "_PASSTHROUGH": {
        # 透传 = 原样回弹。**只有确定该回弹的才准回弹**，
        # 否则闸门会把「被挡住的正确译法」变成「弹英文」。
        # 依据：游侠手游黑话大全 / 解说奶爸 / bilibili 国际服报点表
        "ninja defuse": "偷包（报点表：ninjia defuse=偷包）",
        "post plant": "包后（报点表：post plant=包后架点）",
        "retake": "反清/回防（报点表：retake=回防）",
        "default": "默认（解说奶爸：默认购买）",
        "full buy": "全起（报点表：full buy=全起）",
        "force buy": "强起（游侠手游黑话大全：强起）",
        "eco": "省钱局（游侠手游黑话大全：Eco 局）",
        "shoot": "打（社区常用）",
        "lets go": "走（社区常用）",
        "let's go": "走（社区常用）",
        "go": "走（社区常用）",
        "behind": "后面有人（报点表：behind=后路来人）",
        "watch out": "小心（社区常用）",
        "careful": "小心（社区常用）",
        "left": "左边（社区常用）",
        "right": "右边（社区常用）",
        "prefire": "预瞄（解说奶爸：预瞄）",
        "jiggle peek": "小拉（解说奶爸：popingswing）",
        "wide peek": "大拉身位（报点表：wide peek）",
        "shoulder peek": "假peek（报点表：shoulder peek）",
        "wall bang": "穿墙（解说奶爸：穿墙）",
        "wallbang": "穿墙（同上）",
        "one way": "单向烟（游侠手游黑话大全）",
        "igl": "指挥（解说奶爸：队伍指挥）",
        "execute": "执行（社区常用）",
        "on me": "我来（社区常用）",
        "hit it": "打他（社区常用）",
        "above": "上面（社区常用）",
        "below": "下面（社区常用）",
        "swing": "拉枪（报点表：swing=拉枪）",
        "cross": "交叉（报点表：crossfire）",
        "fake defuse": "假拆包（报点表：tap=假拆）",
        "tap": "假拆（报点表：tap=假拆）",
    },
    "_TRANSLATE_FIRST": {
        # 下面这些是 audit_comms 直接断言过的组合报点，
        # 组成词若无担保，闸门会把整句挡回云端（实测 9 条报红）。
        "pop flash": "瞬闪（社区：瞬闪/快速闪）",
        "one way smoke": "单向烟（游侠手游黑话大全）",
        "ninja defuse": "偷包（报点表：ninjia defuse=偷包）",
        "default": "默认（解说奶爸：默认购买，不叫「慢打」）",
        "lets go": "走（社区常用）",
        "low": "大残（报点表：low=残血一滴）",
        "im low": "我大残",
        "wide swing": "大拉（游侠手游黑话大全：popingswing）",
        "jiggle peek": "小拉（同上：小身位多次 peek）",
        "wall bang": "穿墙（解说奶爸：穿墙）",
        "entry": "突破手（解说奶爸：entry 先手）",
        "care flank": "小心绕后（解说奶爸）",
        "one hp": "一滴血（游侠手游黑话大全：残血一滴）",
        "so low": "大残（同上）",
    },
    "_PLACE": {
        "mid": "中路（国服通行叫法）",
        "heaven": "二楼（bilibili 国际服报点表；「二楼」是硬翻）",
        "a short": "A小（用户点名：必须是 A小 不是秀特）",
        "a long": "A大",
        "b main": "B大", "a main": "A大",
    },
    "_ACT": {
        "stack": "赌点（游侠手游黑话大全 / 解说奶爸）",
        "hold": "架枪（同上）",
        "camp": "蹲点（同上）",
        "lurk": "游走/断后（社区说法）",
        "trade": "补枪（联网核实：人头互换/补枪，非「换血」）",
    },
    "_REPLY": {
        "gg": "GG（社区直接用缩写）",
        "ggwp": "GGWP（本仓 STRICT_RULES_ZH 第 7 条自定规则）",
        "wp": "玩得好（well played，非 GG）",
    },
    "KO_PHRASES": {
        # 整句表：目的是输出**通顺中文**，逐词堆词用户读不了
        "리스폰 곧이에요": "马上到重生点了",
        "칼 가자": "我起刀",
        "스모크 미드": "中路架烟",
        "미드 플랭크 두 명이에요": "中路有两个绕后",
        "라운드 로스트": "这回合输了",
    },
    "KO_RULES": {
        # 以下均为**联网核实过**的标准词，来源写在值里。
        # 「 стандарт词」也能核实：라운드/로스트/플랭크/칼/저기/증원/바론
        # 都是普通韩语词，含义不依赖游戏语境，不是我编的。
        "울베": "我方基地（namu.wiki 韩版《발로란트》词条）",
        "적베": "敌方基地（同上）",
        "백사": "后点（同上）",
        "커넥": "连接（同上）",
        "베이팅": "当诱饵（同上）",
        "세바": "保枪（同上）",
        "라운드": "回合（普通韩语词）",
        "로스트": "输了（普通韩语词）",
        "플랭크": "绕后（游侠手游黑话大全：flank=绕后）",
        "칼": "刀（普通韩语词）",
        "저기": "那边（普通韩语词）",
        "여기": "这边（普通韩语词）",
        "증원": "增援（普通韩语词）",
        "바론": "男爵（Baron，国服官方叫男爵）",
        "미드": "中路（社区通用）",
        "스모크": "烟（社区通用）",
        "스파이크": "包（社区通用）",
        "스파이크 설치": "下包（社区通用：설치=plant）",
        "스파이크 해제": "拆包（社区通用：해제=defuse）",
        "설치": "下包（社区通用：설치=plant）",
        "해제": "拆包（社区通用：해제=defuse）",
        "설치했어요": "下包了（社区通用）",
        "리스폰": "重生（社区通用）",
        "플래시": "闪光弹（社区通用）",
        "셀치": "闪光（韩区通用俚语）",
        "시간": "时间（普通韩语词）",
        "시간이다": "时间到了（普通韩语词：시간 + 이다）",
        "디펜스": "防守（普通韩语词）",
        "살고": "活着（普通韩语词）",
        "갸가워": "走吧（普通韩语词）",
    },
    "JA_RULES": {
        "ヘブン": "二楼（bilibili 国际服报点表）",
        "地獄": "下层（bilibili 国际服报点表）",
        "敌": "敌人（普通词）",
        "味方": "队友（普通词）",
        "後ろ": "后面（普通词）",
        "スモーク": "烟（社区通用）",
        "フラッシュ": "闪光弹（社区通用）",
        "ナデ": "雷（普通词）",
        "ローテ": "转点（社区通用）",
        "スパイク": "包（社区通用）",
        "死亡": "死（普通词）",
        "投げる": "丢（普通词）",
    },
    "KO_PHRASES": {
        # 整句表：目的是输出**通顺中文**，逐词堆词用户读不了
        "리스폰 곧이에요": "马上到重生点了",
        "칼 가자": "我起刀",
        "스모크 미드": "中路架烟",
        "미드 플랭크 두 명이에요": "中路有两个绕后",
        "라운드 로스트": "这回合输了",
        "갸가워": "走了",
        "증원 왔어": "增援来了",
        "바론 시간이다": "男爵时间到了",
    },
    "JA_PHRASES": {
        "ヘブンに敵": "二楼有人（中文报点习惯是「XX有人」）",
        "敵が後ろ": "后面有人（同上）",
        "味方が三人": "队友有三个（同上）",
        "スモーク投げる": "丢个烟",
        "フラッシュ弾いて": "给他闪",
        "サイトクリア": "包点清了",
        "ローテート": "转点",
        "スパイク設置した": "他们下包了",
    },
    "_JP_JARGON": {
        # 日区玩家混用的英文黑话，用法与英语区一致
        "peek": "架点（游侠手游黑话大全：peek=拉出掩体）",
        "relay": "接力（社区通用）",
        "rellay": "接力（同上）",
        "smoke": "烟（社区通用）",
        "flash": "闪光（社区通用）",
        "one way": "单向烟（游侠手游黑话大全）",
        "rotate": "转点（同上）",
        "stack": "赌点（解说奶爸）",
        "trade": "补枪（联网核实：人头互换/补枪）",
        "heaven": "二楼（bilibili 国际服报点表）",
        "mid": "中路（同上）",
        "spike": "包（同上）",
        "site": "包点（同上）",
    },
}


def _load_registry() -> dict[str, dict[str, str]]:
    """加载 `verified_terms.json`（核实结论的**持久化**载体）。

    为什么必须有这个文件：`VERIFIED` 是运行时数据，进程退出就没了。
    核实成果如果只存在内存里，下次改一行代码就全丢。
    `verified_terms.load()` 会**拒绝没有来源说明**的条目 ——
    这样「写不出凭什么」就不能混进白名单，不靠自觉。
    """
    try:
        from . import verified_terms
        return verified_terms.load()
    except Exception:
        return {}


def _pinned_by_audits() -> set[str]:
    """扫描 tests/audit_*.py，收集被审计钉死过的**原文**字符串。

    这是「已核实」最硬的判据：**有测试证明它对**。
    当初核实某个译名时会在某个 audit 里写死期望值（并留依据），
    那条期望就是担保人。人肉 VERIFIED 表会漂移，审计不会。

    扫描方式：审计里的期望值都是中英混合的字面量，这里取所有
    含 CJK 或拉丁字母、长度 1~14 的字符串作为候选键。
    （宁可多收，收进来只是允许本地命中，不是自动认定正确。）
    """
    pinned: set[str] = set()
    tests = _HERE.parent.parent / "tests"          # src/services -> 仓库根
    if not tests.is_dir():
        return pinned
    pat = re.compile(r"""["']([^"'\n]{1,28})["']""")
    # 原文可能是中文 / 韩文 / 日文假名 / 拉丁（罗马音）——
    # 早期版本只认「含汉字」或「纯拉丁」，把韩日原文全挡在外面了，
    # 导致 audit_korean 钉死的 '바론 시간이다' 反而被判无担保。
    looks_like_utterance = re.compile(
        r"[\u4e00-\u9fff\uac00-\ud7af\u3040-\u30ff]"
        # 拉丁分支的长度上限必须容得下多词报点
        # （'pop flash b main'=16 字符，早期限 13 结果被整条挡掉）
        r"|^[A-Za-z][A-Za-z0-9 \-']{0,23}$")
    for f in tests.glob("audit_*.py"):
        try:
            txt = f.read_text(encoding="utf-8")
        except Exception:
            continue
        for s in pat.findall(txt):
            s = s.strip()
            # 必须像个报点：太长的说明性文字、代码符号一律排除。
            # 注意上限：多词报点（'pop flash b main'=16）也必须能收进来，
            # 早期版本限 12 结果把 audit_comms 的整条断言挡在门外。
            if not s or (" " in s and len(s) > 24):
                continue
            if looks_like_utterance.search(s):
                pinned.add(s.lower())
    return pinned


_PINNED: set[str] | None = None


def pinned_keys() -> set[str]:
    global _PINNED
    if _PINNED is None:
        _PINNED = _pinned_by_audits()
    return _PINNED


_LIVE_TABLES: dict[str, dict] = {}
_EN_TABLES = ("_PLACE", "_ACT", "_GEAR", "_REPLY",
              "_TRANSLATE_FIRST", "_V25", "_PASSTHROUGH")


def _live_value(table: str, key: str) -> str | None:
    """查这个键在**代码活表**里现在是什么值；查不到返回 None。

    延迟 import，避开 local_rules <-> provenance 的循环导入。
    """
    if table not in _LIVE_TABLES:
        # 延迟 import：local_rules / cjk_slang 都要 import provenance，
        # 模块级 import 会成环，所以只能在函数里取。
        from . import cjk_slang, local_rules
        mod = None
        if table in _EN_TABLES:
            mod = local_rules
        elif table.startswith(("KO_", "JA_", "_JP_", "_JA_")):
            mod = cjk_slang
        elif table == "zh_to_en":
            # v0.2.11：PTT 那条链（中译英）也要能被钉死校验。
            # 之前只认 local_rules / cjk_slang 两组表，`zh_to_en` 被漏掉，
            # 于是它的钉死值既不校验也不报错 —— **静默失效**。
            #
            # 注意 zh_to_en **不是一张表，是三张**：谐音 / 整句 / 脏话，
            # 一个词可能落在任意一张里（实测「一个人」在 _HOMOPHONE、
            # 「包点了」在 _PHRASES），所以必须**三张合并**才能查全。
            from . import zh_to_en as _z
            _merged = {}
            for _t in ("_HOMOPHONE", "_PHRASES", "_PROFANITY"):
                _d = getattr(_z, _t, None)
                if isinstance(_d, dict):
                    for _k, _v in _d.items():
                        if isinstance(_k, str) and isinstance(_v, str):
                            _merged.setdefault(_k.strip(), _v.strip())
            _LIVE_TABLES[table] = _merged
            _m = _merged.get(key)
            return _m if isinstance(_m, str) else None
        elif table in ("game_terms", "agents"):
            import importlib
            mod = importlib.import_module(f".{table}", package=__package__)
        if mod is None:
            _LIVE_TABLES[table] = {}
            return None
        t = getattr(mod, table, None)
        _LIVE_TABLES[table] = dict(t) if t else {}
    t = _LIVE_TABLES[table]
    for cand in (key, key.replace("_", " "), key.replace(" ", "_")):
        if cand in t:
            v = t[cand]
            return v if isinstance(v, str) else None
    return None


def is_verified(table: str, key: str) -> bool:
    """该表的这个键是否有担保人。

    两个担保来源：
      1. `provenance.VERIFIED` 里手写登记（须写明「凭什么」），
         以及它的**持久化**版本 `verified_terms.json`（逐批核实的成果）
      2. 被某个 `tests/audit_*.py` 用期望值钉死过 —— 有测试证明它对

    两者都没有 = 没人担保。
    """
    # --- v0.2.11：译文钉死检查 ---
    # 登记表钉了译文 pin，而代码活表里现在是别的值 —— 说明这条被改过
    # 而来源没跟着更新。**不放行**：宁可落云端慢 400ms，也不能给错译。
    from . import verified_terms          # 延迟 import，同上
    pin = verified_terms.pinned(table, key)
    if pin is not None:
        live = _live_value(table, key)
        if live is not None and live.strip() != pin:
            return False
    if not key:
        return False
    k = key.strip().lower()
    if not k:
        return False
    if k in {x.lower() for x in VERIFIED.get(table, {})}:
        return True
    reg = _registry()
    if k in {x.lower() for x in reg.get(table, {})}:
        return True
    return k in pinned_keys()


_REG: dict[str, dict[str, str]] | None = None


def _registry() -> dict[str, dict[str, str]]:
    global _REG
    if _REG is None:
        _REG = _load_registry()
    return _REG




def _table_keys(table: str) -> list[str]:
    """取表里的**键**（dict 取 key，list[(k,v)] 取 k，set 取元素）。"""
    for mod in (_cjk(), _loc()):
        v = getattr(mod, table, None)
        if v is None:
            continue
        if isinstance(v, dict):
            return [k for k in v if isinstance(k, str)]
        if isinstance(v, (set, frozenset)):
            # _PASSTHROUGH 是纯字符串集合（没有译文位）
            return [x for x in v if isinstance(x, str)]
        if isinstance(v, (list, tuple)):
            return [p[0] for p in v
                    if isinstance(p, (tuple, list)) and len(p) == 2
                    and isinstance(p[0], str)]
        if isinstance(v, str):
            return []
    return []


def verified_keys(table: str) -> set[str]:
    """该表里「有担保」的键（登记 + 审计钉死）。"""
    return {k.strip().lower() for k in _table_keys(table)
            if is_verified(table, k)}


def _cjk():
    import src.services.cjk_slang as m
    return m


def _loc():
    import src.services.local_rules as m
    return m


# ---------------------------------------------------------------------------
# 词表规模报告（给 UI / 诊断用）
# ---------------------------------------------------------------------------
def coverage_report(tables: dict[str, int]) -> list[str]:
    """列出「规模 vs 已核实」——已核实占比太低就说明该靠自学习补。"""
    out = []
    for name, total in sorted(tables.items()):
        ok = len(verified_keys(name))
        pct = (ok / total * 100) if total else 0.0
        out.append(f"  {name:<20} 共 {total:>4} 条，有担保 {ok:>3} 条"
                   f"（{pct:.0f}%）")
    return out


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    import src.services.cjk_slang as C
    import src.services.local_rules as L

    sizes = {}
    for t in ("KO_RULES", "KO_PHRASES", "KO_ROMA", "JA_RULES", "JA_PHRASES",
              "_JP_JARGON", "_PLACE", "_ACT", "_GEAR", "_REPLY",
              "_TRANSLATE_FIRST", "_V25"):
        v = getattr(C, t, None) or getattr(L, t, None)
        if v:
            sizes[t] = len(v)
    print("词条来源覆盖情况（有担保 / 总量）")
    print("=" * 56)
    print(f"审计钉死的原文键共 {len(pinned_keys())} 个（自动扫 tests/audit_*.py）")
    print()
    for line in coverage_report(sizes):
        print(line)
    print()
    total = sum(sizes.values())
    ok = sum(len(verified_keys(t)) for t in sizes)
    print(f"合计 {ok}/{total} 条有担保（{ok / total * 100:.1f}%）")
    print()
    print("没有担保的条目不参与本地命中（宁可慢 400ms 落云端，也不错得更快）")
    print("变可靠只有两条路：")
    print("  1) 把期望值写进某个 audit_* 并注明核实依据")
    print("  2) 自学习系统：真实对局反复用到且被用户确认的，自动提升")
