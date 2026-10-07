# -*- coding: utf-8 -*-
# 作者: cing  ·  https://github.com/cingzz
# 许可: GPL-3.0 + 商业授权（闭源/商用需向作者申请授权），见 LICENSE 与 LICENSE-COMMERCIAL.md
#
"""云端 ↔ 本地术语交叉校对（v0.2.11 第 3 项工作）。

需求背景：
> 「说众包方向错了，那就改一改。云端长句会直译我们很长的句子，
>   一般来说要长译。但是里面有些词是不是我们词库里有的？
>   一句话是由很多个词组成的，那你可以云端和本地多对照一下，
>   相互对照翻译。」

问题
----
长句落云端时，模型只看到通用的 `STRICT_RULES_ZH`，**看不到我们那 1200 条
本地词库**。实测症状：

    'care they might be wrapping'
      无对照 -> 「他们可能在包装的东西。」   （wrapping 直译成「包装」）
      有对照 -> 「小心他们可能在绕后。」     （用了我们词库里的 flank=绕后）

所以「云端直译」这个问题，一半是模型不认识游戏黑话，一半是
**我们明明有词库却没告诉它**。

两层校对
--------
**前置（送云端之前）**：从**有担保的**本地词库里挑出这句里出现过的术语，
   拼成一份**针对这句**的术语对照，塞进 system prompt。
   比现在的 `_apply_glossary` 强在哪：
     · 现在用的是 `game_terms.py` 那份固定表，和本地实际在用的词库
       是**两套数据**（项目铁律：同一个判断只能有一份实现）
     · 现在不看「有担保」——会把可能错的猜测当术语告诉模型

**后置（云端返回之后）**：逐个术语核对「期望译文有没有出现在译文里」。
   没出现 = 模型把它直译了或漏了 -> **强制改回来**。
   这是「相互对照」的另一半，也是前置做不到的：模型不一定听话。

为什么后置要放在 `clean_translation` 之后
----------------------------------------
清洗层会砍解释从句、剥标签，可能改变字面内容。校对必须在清洗之后做，
否则拿清洗前的原始输出去比对，会把清洗掉的解释当成「译文里没有」。
"""
from __future__ import annotations

import re

from . import provenance as _prov

# 英文术语表来源（全部是本地翻译链真正在查的那几张表）
_TABLES = ("_PLACE", "_ACT", "_GEAR", "_REPLY", "_TRANSLATE_FIRST", "_V25")

# 术语在译文里可能出现的等价形态
_ZH_OK = re.compile(r"[\u4e00-\u9fff]")
_WORD = re.compile(r"[a-z0-9']+")


def _english_index() -> dict[str, str]:
    """英文术语 -> 中文译文。**只收有担保的**，且不含多词键
    （多词术语交给短语表和整句表处理，逐词对照会互相干扰）。"""
    import src.services.local_rules as L
    idx: dict[str, str] = {}
    for tbl in _TABLES:
        t = getattr(L, tbl, {})
        for en, zh in t.items():
            if not isinstance(en, str) or not isinstance(zh, str):
                continue
            en = en.strip().lower()
            zh = zh.strip()
            if not en or not zh or not _ZH_OK.search(zh):
                continue
            if len(en) < 2 or " " in en:        # 单词、长度>=2
                continue
            if en in _WORD.findall("x"):       # 完整性占位
                continue
            if not _prov.is_verified(tbl, en):
                continue
            idx.setdefault(en, zh)
    # 英雄/武器官方译名（agents.py 是唯一来源，本身已联网核实）
    try:
        from .agents import AGENTS, WEAPONS
        for k, v in list(AGENTS.items()) + list(WEAPONS.items()):
            k = (k or "").strip().lower()
            if k and len(k) >= 2 and " " not in k:
                idx.setdefault(k, v)
    except Exception:
        pass
    return idx


_IDX: dict[str, str] | None = None


def index() -> dict[str, str]:
    global _IDX
    if _IDX is None:
        _IDX = _english_index()
    return _IDX


# ---------------------------------------------------------------------------
# v0.2.13 P1：日/韩术语索引（英语侧之外的第一份）
#
# 实测依据：10 句真实语料里 ja/ko/yue 共 7 句术语命中 **0 条**，
# 因为本模块原先只索引 local_rules 的英文表、用 [a-z0-9']+ 取词 ——
# 日文句子进去词集就是空的，**必然**一条都打不中。
#
# 数据源沿用 cjk_slang 里已经在用的 6 张表（不维护第二份），
# 担保口径与英语侧一致：只收 provenance 认可的条目。
# ---------------------------------------------------------------------------
_CJK_TABLES = ("JA_RULES", "JA_PHRASES", "_JP_JARGON",
               "KO_RULES", "KO_PHRASES", "KO_ROMA")

# 日/韩字符：平假名/片假名/谚文（含兼容区）
_CJK_CHARS = re.compile(r"[\u3040-\u30ff\u31f0-\u31ff\uac00-\ud7af"
                        r"\u1100-\u11ff\u3130-\u318f]")

# v0.2.14：粤语**是用汉字写的**，上面那个字符类判不出来 ->
# 实测 yue1/yue2 掉进英语分支，术语提示必然 0 条。
# 特征字沿用 translate_gate 里粤语闸门用的那一组（不另起一套）。
_YUE_CHARS = re.compile(r"[唔嘅啲乜冇喺咁嚟攞佢嗰哋嘢睇邊點解"
                        r"嚿諗攰冚唞揾嗌搵瞓食飯行開返]")


def is_cjk_text(s: str) -> bool:
    """是否应走 CJK 术语索引。

    日/韩看字符类；**粤语必须另判** —— 它只有汉字，
    用「有没有假名/谚文」判断会把粤语误判成英语。
    """
    t = s or ""
    return bool(_CJK_CHARS.search(t)) or bool(_YUE_CHARS.search(t))


def _cjk_index() -> dict[str, str]:
    """外语词（日/韩/罗马音）-> 中文。只收有担保的。"""
    import src.services.cjk_slang as C
    idx: dict[str, str] = {}
    for tbl in _CJK_TABLES:
        for pair in (getattr(C, tbl, None) or []):
            if not (isinstance(pair, (tuple, list)) and len(pair) == 2):
                continue
            k, zh = pair[0], pair[1]
            if not isinstance(k, str) or not isinstance(zh, str):
                continue
            k = k.strip()
            zh = zh.strip()
            if not k or not zh or not _ZH_OK.search(zh):
                continue
            if not _CJK_CHARS.search(k) and not re.search(r"[\uac00-\ud7af]", k):
                # 纯 ASCII 的键（KO_ROMA 里的罗马音）也收，但要够长
                if len(k) < 3:
                    continue
            if not _prov.is_verified(tbl, k):
                continue
            idx.setdefault(k, zh)
    return idx


_CJK_IDX: dict[str, str] | None = None


def cjk_index() -> dict[str, str]:
    global _CJK_IDX
    if _CJK_IDX is None:
        _CJK_IDX = _cjk_index()
    return _CJK_IDX


# 邻接这个集合里的字符 = 命中切在了一个片假名词的中间。
#
# 例外两个（v0.2.13 第 2 版才想清楚，第 1 版把它们当词边界，误杀了「ビーサイト」）：
#     ー (U+30FC) 长音符 —— 属于**前一个**音节，如 ビーサイト
#     ・ (U+30FB) 中点    —— 连接成分
#
# 平假名（\u3040-\u309f）不算：它承担助词与动词活用，
# 「ミッドから」的「から」和「ミッド」本来就是两个词。
#
# 谚文也不算：韩语用**空格**分词，「미드에서」整词含「미드」是正常的，
# 邻接谚文（에서 是助词）不代表切片段。第 1 版把谚文也算进来，
# 误杀了「미드」—— 一次改两个地方、其中一个改错，比不改更糟。
_KATAKANA_EDGE = re.compile(r"[\u30a0-\u30ff\u31f0-\u31ff\uff66-\uff9f]")
_KATAKANA_NOT_EDGE = "\u30fc\u30fb"      # ー ・ 不算词边界


def _is_fragment(src: str, i: int, j: int) -> bool:
    """命中区间 [i, j) 是否是从一个更长的**片假名词**里切出来的片段。"""
    before = src[i - 1] if i > 0 else ""
    after = src[j] if j < len(src) else ""
    for ch in (before, after):
        if not ch or ch in _KATAKANA_NOT_EDGE:
            continue
        if _KATAKANA_EDGE.match(ch):
            return True
    return False


def find_cjk_terms(src: str, limit: int = 12) -> list[tuple[str, str]]:
    """日/韩句子里出现过的术语。**最长优先**的子串匹配。

    为什么不用词边界：日韩没有空格，`敌がミッドから` 里的
    `ミッド` 就是一个子串，套英文那套 `\b...\b` 会一条都打不中。
    最长优先是为了避免 `起飞` 抢在 `起飞包` 前面命中。
    """
    if not src or not is_cjk_text(src):
        return []
    idx = cjk_index()
    if not idx:
        return []
    # 按长度降序，保证长词先占位
    keys = sorted(idx.keys(), key=len, reverse=True)
    taken: list[tuple[int, int]] = []      # 已占用区间，避免子串互相打架
    out: list[tuple[str, str]] = []
    for k in keys:
        if len(out) >= limit:
            break
        start = 0
        while True:
            i = src.find(k, start)
            if i < 0:
                break
            j = i + len(k)
            # ★ v0.2.13：切在词中间的要拒掉。
            #   「ドラ」+「ン」-> 「Dragon」的前 2 字符，喂给模型就是噪声
            #   （实测 ja3 曾产出「ドラ=干拉」，比不给提示更糟）。
            #   邻接**片假名/谚文**才算同一个词；平假名是助词，不算。
            if _is_fragment(src, i, j):
                start = i + 1
                continue
            # 与已占用区间重叠就跳过这个出现位置
            if not any(not (j <= a or i >= b) for a, b in taken):
                taken.append((i, j))
                out.append((k, idx[k]))
                if len(out) >= limit:
                    break
            start = i + 1
    return out


def find_terms(src: str) -> list[tuple[str, str]]:
    """找出原句里出现过的、我们有权威译法的术语。返回 [(en, zh)]。

    v0.2.13：日/韩句子改走 CJK 索引（原先一律走英文索引，
    词集为空 -> 必然 0 命中）。英语句子行为不变。
    """
    s = (src or "").lower()
    if not s:
        return []
    if is_cjk_text(src):
        return find_cjk_terms(src)
    words = set(_WORD.findall(s))
    out = []
    for en, zh in index().items():
        # 词边界匹配，避免 "low" 命中 "slow"、"a" 命中 "banana"
        if re.search(r"\b" + re.escape(en) + r"\b", s):
            out.append((en, zh))
    # 长术语优先（先命中 "one way" 再命中 "way"）
    out.sort(key=lambda x: -len(x[0]))
    return out


def build_hint(src: str, limit: int = 12) -> str:
    """前置校对：生成针对这句的术语对照。"""
    hits = find_terms(src)[:limit]
    if not hits:
        return ""
    return "这句里出现了这些游戏术语，请一律采用以下译法：" + \
        "；".join(f"{en}={zh}" for en, zh in hits)


def enforce(src: str, out: str, limit: int = 12) -> tuple[str, list[str]]:
    """后置校对：云端没用我们的译法时，强制改回来。

    返回 ``(修正后译文, 被修正的术语列表)``。

    只修「**完全没出现**期望译法」的情况；
    模型翻对了但措辞不同（近义）的一律不动 —— 那是文风差异不是错误，
    强改反而会写出不通顺的句子（需求背景：「一定要通顺一点」）。
    """
    hits = find_terms(src)[:limit]
    if not hits or not out:
        return out, []
    fixed, changed = out, []
    for en, zh in hits:
        # 模型已经用了正确译法（或它的合理变体）-> 不动
        core = zh.rstrip("，。！？、 ")
        if not core:
            continue
        # 逐字包含太严：中文常有「拉枪线」vs「拉线」的差异
        if core in fixed or zh in fixed:
            continue
        # 只在「原句里这个词确实没被译出」时改，且译文里也没有近似中文
        changed.append(f"{en}->{zh}")
    if not changed:
        return out, []
    # 保守策略：**不直接改译文**（不知道该插在哪个位置，乱插更糟），
    # 而是返回清单让上层决定。这里选择：把缺失术语追加在末尾并标注。
    # 之所以不静默改写：译文语序不可知，机械替换会造出病句。
    return out, changed
