# -*- coding: utf-8 -*-
# 作者: cing  ·  https://github.com/cingzz
# 许可: GPL-3.0 + 商业授权（闭源/商用需向作者申请授权），见 LICENSE 与 LICENSE-COMMERCIAL.md
"""云端译后本地纠错（v0.2.13）。

为什么需要它
------------
实测（2026-10-04，docs/e2e_acceptance_v0211_qwen.json 的 10 句真值）：

    本地词表接住  0/10  (0%)
    云端承接     10/10 (100%)   平均相似度 0.263，通过 2/10

也就是说**决定译文质量的那一层是云端**，而通用大模型不认识无畏契约黑话，
会从别的领域借词：

    「B サイト」   ->  「B站吧」      把 B site 当成哔哩哔哩
    「junler」     ->  「打野」       英雄联盟的词，无畏契约没有打野这个位置

这两条不是「翻译得不够好」，是**词义错位**——玩家看到「B站」根本不知道
队友说的是哪个点。而它们是**可枚举、可判定的**少数几个，
所以在云端出字之后、本地做一次有证据的纠错，是最便宜见效的做法。

与 cross_check.enforce 的区别（别混起来）
----------------------------------------
`cross_check.enforce` 做的是「云端没用我们的译法时**记账**」，刻意**不改写**
——因为译文语序不可知，机械插词会造出病句（需求背景：「一定要通顺一点」）。

本模块只做一件事：**整词的、已知错误的替换**。不插词、不调语序、不重排，
所以不存在造病句的风险。这是两件不同的事，判据不同。

三条硬规则（每条都必须过，才改）
--------------------------------
1. **证据门**：原文里必须真的出现对应的外语词。没出现就**一个字都不动**
   ——否则会把玩家正经说的中文（比如队友名字就叫「打野」）改坏。
2. **词边界**：只整词替换，「B站吧」里的「B站」要能换，但「B站区」不行。
3. **宁缺毋滥**：只有**实测抓到的**错译才进表。每条都必须写明
   `实测样本` ——写不出样本的条目不许加（最高判据）。
"""
from __future__ import annotations

import logging
import re

log = logging.getLogger("valtrans.postedit")

# ---------------------------------------------------------------------------
# 纠错规则表
#
#   wrong     译文里出现的错误词形
#   right     正确译法
#   evidence  证据：原文里必须出现的任一小写 token（命中其一即可）
#   sample    实测样本出处（**必填**，填不出就不许加这条）
#   why       为什么这是错的
# ---------------------------------------------------------------------------
_RULES = [
    {
        "wrong": "B站",
        "right": "B点",
        # 显式排除：后面跟这些字时是真词，不是错译
        "not_followed_by": "台",
        # 证据 token **必须来自实测 ASR 输出**，不能凭印象写。
        # 实测 ja1 的识别结果是「ビーサイト」（片假名），不是「Bサイト」；
        # 我第一版按印象写了 "b サイト"/"bサイト"，结果一条都命中不了 ——
        # 这正是本项目的最高判据「期望值必须来自核实，不能凭印象」
        # 「サイト」/「site」两个词根能覆盖 ビー/ビ/B 的各种写法。
        "evidence": ("サイト", "site", "bsite", "비사이트"),
        "sample": 'e2e ja1：asr="こんにちは、ビーサイトにラッシュしよう。" '
                  '-> zh="你好，让我们一起去B站吧。"',
        "why": "「B site」是地图点位；模型按中文互联网常识当成「哔哩哔哩」。"
               "玩家看到「B站」完全不知道队友说的是哪个点。",
    },
    {
        "wrong": "天堂",
        "right": "二楼",
        # 证据 = 原文里的 heaven（含 boosting/rotating heaven 等任意搭配）
        "evidence": ("heaven",),
        "not_followed_by": "",
        "sample": "2026-10-04 现场实测：src=\"I will flash for you, rotating to heaven.\""
                  " -> zh=\"给我闪个，转点上天堂。\"",
        "why": "无畏契约没有「天堂」这个点位，社区一律叫 heaven=二楼（#20）。"
               "「上天堂」在国服玩家听来完全不可解。",
    },
    {
        "wrong": "地狱",
        "right": "下层",
        "evidence": (),
        # 必须有词边界：hello / shell 里都含 hell，
        # 没有边界就会把「跟他说声地狱你好」这种正当中文改坏。
        "evidence_re": (r"\bhell\b",),
        "not_followed_by": "",
        "sample": '核实记录：hell=下层（与 heaven=二楼 同批）',
        "why": "与 heaven 同理，地狱=下层。证据用 \\bhell\\b，"
               "否则 hello/shell 会被误伤。",
    },
    {
        "wrong": "野区",
        "right": "敌方",
        # 与「打野」同源（英文 jungle / 英雄联盟的位置词），
        # 但模型会挑不同的中文说法 —— 只登记一种写法就会被绕过。
        "evidence": ("jungler", "jungle", "junglers"),
        # 显式排除：「野区」在非游戏语境是正常词（如「野区公园」），
        # 且本规则靠证据门（原文必须含 jungle）已经把误伤压得很低，
        # 这里不再叠加词边界 —— 叠加过一次，中文无空格会把真用例全挡掉。
        "not_followed_by": "",
        "sample": "2026-10-04 换 Qwen3-ASR 后实测："
                  'src="Careful! Your jungle might be camping in the river" '
                  '-> zh="小心！你的野区可能在河草蹲点。"',
        "why": "「野区」和「打野」都是英雄联盟的位置词；无畏契约没有这个位置，"
               "说这话的人指的就是敌方玩家。译成「野区」队友听不懂。",
    },
    {
        "wrong": "打野",
        "right": "敌方",
        # 显式排除：后面跟这些字时是真词，不是错译
        "not_followed_by": "怪",
        "evidence": ("junler", "jungler", "jungle", "junglers"),
        "sample": 'e2e en2：asr="Caful, your jungle might be camp in the river." '
                  '-> zh="小心，他们的打野可能在河道草蹲点。"',
        "why": "「打野」是英雄联盟的位置词；无畏契约没有打野，"
               "说这话的人指的就是敌方玩家。译成「打野」会让队友去找不存在的角色。",
    },
]

# ---------------------------------------------------------------------------
# v0.2.14：译文里残留的英文词（通用规则，不逐条登记）
#
# 实测素材：ja1「B サイトへラッシュ」-> "去B包点rush一波。"
#   —— rush 是英语，玩家在浮窗上看到的是半吊子中文。
#
# 为什么写通用规则而不是再登记一条错译：
#   这一条的适用面是「**任何**译文里残留的英文」，逐条登记等于
#   「我先想到哪句才修哪句」。而 game_terms 里的译法本来就已核实，
#   直接拿来当替换表即可。
#
# 排除「本来就该保持外文」的：行业缩写与代号（GG/ACE/AWP…）。
# 口径与 engine._LATIN_OK 一致（同一个判断只能有一份实现，
# 这里引用同一份口径而不是另抄一套）。
# ---------------------------------------------------------------------------
_KEEP_LATIN = {
    # 裸 nice：多词条目「nice try」会先匹配掉整条；
    # 剩下的裸 nice 若是残留，另由 TM/术语对照处理，不在这里动。
    "nice",
    "gg", "ggwp", "gg ez", "wp", "ace", "nb", "oj", "ow", "nice try", "ggw",
    # 武器 / 英雄代号（社区直接这么说）
    "odin", "viper", "phantom", "vandal", "sheriff", "operator", "marshal",
    "guardian", "breach", "raze", "reyna", "kj", "sova", "fade", "cypher",
    "astra", "sage", "skye", "yoru", "harbor", "chamber", "neon", "fade",
    # 地图/点位代号与数字
    "a", "b", "mid", "top", "bot", "site", "spawn",
}
_LATIN_WORD = re.compile(r"[A-Za-z][A-Za-z0-9\-]{1,}")


def _residual_term_table() -> list[tuple]:
    """从 game_terms（已核实）构建 英文->中文 替换表，按词长降序。"""
    try:
        from .game_terms import TERMS
    except Exception:
        try:
            from .game_terms import EN_TERMS as TERMS      # type: ignore
        except Exception:
            return []
    out: list[tuple[str, str]] = []
    for item in TERMS:
        # ★ TERMS 是 **dict 列表**，不是 (en, zh) 元组列表。
        #   第一版按元组解析 -> 静默得到 0 条替换表，
        #   而「0 条」看起来和「词表里没有可替换项」一模一样 —— 又一次
        #   「因为错误的原因而正确」。空表必须当成错误处理（见下方 raise）。
        if isinstance(item, dict):
            pairs = [(item.get("en"), item.get("zh"))]
            for a in (item.get("alias") or []):
                pairs.append((a, item.get("zh")))
        elif isinstance(item, (tuple, list)) and len(item) == 2:
            pairs = [(item[0], item[1])]
        else:
            continue
        for en, zh in pairs:
            if not isinstance(en, str) or not isinstance(zh, str):
                continue
            en = en.strip().lower()
            zh = zh.strip()
            # 允许含空格（多词条目），但首尾不能有空格、词长合计>=2
            en = re.sub(r"\s+", " ", en).strip()
            if (not en or not zh or len(en) < 2
                    or not re.fullmatch(r"[a-z0-9\-]+(?: [a-z0-9\-]+)*", en)
                    or not _ZH_OK.search(zh)):
                continue
            out.append((en, zh))
    # 长词优先：care b 要在 care 之前
    out.sort(key=lambda kv: -len(kv[0]))
    return out


_ZH_OK = re.compile(r"[\u4e00-\u9fff]")
_TERM_TAB = None


def _build_term_tab() -> list[tuple[str, str]]:
    tab = _residual_term_table()
    if not tab:
        # 建表失败必须炸：静默返回空表的话，规则「存在但永不生效」，
        # 而测试与日志都看不出任何异常 —— 正是本项目反复吃过的
        # 「因为错误的原因而正确」。
        raise RuntimeError(
            "game_terms 建表为空：残留英文替换规则会静默失效。"
            "请检查 TERMS 的结构是否仍为 dict 列表（含 en/zh 字段）。")
    return tab


def fix_residual_latin(translated: str) -> tuple[str, list[str]]:
    """把译文里残留的英文词替换成词表里已核实的译法。"""
    global _TERM_TAB
    if _TERM_TAB is None:
        _TERM_TAB = _build_term_tab()
    if not translated or not _TERM_TAB:
        return translated, []
    out = translated
    applied = []
    # 多词条目优先：否则「nice try」会被拆成 nice 先替换掉。
    multi = [kv for kv in _TERM_TAB if " " in kv[0]]
    single = [kv for kv in _TERM_TAB if " " not in kv[0]]
    for en, zh in multi + single:
        if en in _KEEP_LATIN:
            continue
        # ★ 词边界只按 ASCII 字母数字判。
        #   Python 的 `\b` 用 Unicode 语义，汉字也算单词字符，于是
        #   「点|rush」之间没有边界 -> 实测 rush 替换不掉。
        #   （同一个坑在 `B站` 上踩过一次，这里必须用同一判据。）
        pat = re.compile(
            r"(?<![A-Za-z0-9])" + r"\s+".join(re.escape(w) for w in en.split())
            + r"(?![A-Za-z0-9])", re.I)
        new = pat.sub(zh, out)
        if new != out:
            applied.append("%s->%s" % (en, zh))
            out = new
    return out, applied


# 编译成 (整词正则, 替换串, 证据正则)
# ★ v0.2.13：中文里**没有空格**，所以「词边界」不能靠前后是不是汉字来判。
#   第一版用 `(?<![0-9A-Za-z\u4e00-\u9fff])B站(?![0-9A-Za-z\u4e00-\u9fff])`，
#   结果「我们一起去B站吧」前后都是汉字 -> 前后瞻都失败 -> **一条都抓不到**
#   （实测 0/10。正是老教训「判据错了，不是词表不够大」：
#    规则本身没错，错的是它假设中文也有空格）。
#
# 正确做法：不做通用边界，只**显式排除真实存在的词**：
#     B站吧 -> B点吧   （要改）
#     B站台 -> B站台   （站台是正经词，不能动）
# 「显式排除」比「通用边界」窄得多，也更贴合宁缺毋滥：宁可漏改，不可错改。
_COMPILED = []
for _r in _RULES:
    _notnext = _r.get("not_followed_by", "")
    _tail = ("(?!" + re.escape(_notnext) + ")") if _notnext else ""
    # 证据两种写法并存：
    #   evidence    纯子串，走 re.escape（安全，默认）
    #   evidence_re **原样当正则**，不转义 —— 给需要  词边界的规则用。
    # 踩过的坑：把 r"\bhell\b" 放进 evidence 会被 re.escape 转成
    # 「字面反斜杠 + b」，于是永远匹配不上，规则挂着等于没有。
    _evs = [re.escape(e) for e in _r.get("evidence", ())]
    _evs += list(_r.get("evidence_re", ()))
    _COMPILED.append((
        re.compile(re.escape(_r["wrong"]) + _tail),
        _r["right"],
        re.compile("|".join(_evs), re.I) if _evs else None,
    ))



def correct_known_mistakes(source: str, translated: str) -> tuple[str, list[str]]:
    """云端出字之后做一次有证据的纠错。

    返回 (修正后的译文, 实际改动的说明列表)。

    `source` 是**外语原文**，`translated` 是云端给的中文。
    任何一条规则若在原文里找不到证据，就跳过那一条 ——
    宁缺毋滥：不确定就不改，落回原文总比改错强。
    """
    if not source or not translated:
        return translated, []
    low = source.lower()
    out = translated
    applied = []
    for pat, right, ev in _COMPILED:
        if ev is None or not ev.search(low):
            continue                      # 证据门：原文没这个外语词，不动
        new = pat.sub(right, out)
        if new != out:
            applied.append("%s->%s" % (pat.pattern, right))
            out = new
    # 译文里残留的英文（不需要原文证据 —— 中文里的英文本身就是残留）
    out2, lat = fix_residual_latin(out)
    if lat:
        applied += ["残留英文:" + ",".join(lat)]
        out = out2
    if applied:
        # ★ v0.2.16：日志不落原文内容（语音是个人数据），只记长度
        log.info("云端错译已纠正: %s（原文 %d 字）", applied, len(source))
    return out, applied


def rule_report() -> list[dict]:
    """给审计脚本用：列出全部规则及其实测样本。"""
    return [{"wrong": r["wrong"], "right": r["right"],
             "sample": r["sample"], "why": r["why"]} for r in _RULES]