# -*- coding: utf-8 -*-
# 作者: cing  ·  https://github.com/cingzz
# 许可: GPL-3.0 + 商业授权（闭源/商用需向作者申请授权），见 LICENSE 与 LICENSE-COMMERCIAL.md
#
"""accent.py 重写：加两道安全闸门，把误伤压到 0。

上一版的失败（实测 9/12 误伤，不可接受）
------------------------------------------
    i love this game        -> i low this game
    nice shot my friend     -> ns shoot my friend
    he is a good player     -> he is a kit boiler
    thank you very much     -> thanks you fire much
根因：**盲目逐词替换**。只要某个词的辅音骨架能在游戏词表里找到
同骨架的词，就替换。游戏词表里有 shot/nice/fire 这类本来
就是普通英文单词的条目，于是正常句子被毁。

重写后的两道闸门（缺一不可）
----------------------------
闸门 A「上下文」：整句里必须已经出现 ≥1 个**本来就认识**的游戏词
    有 -> 说明这句确实在报点，纠错安全
    无 -> 说明这是普通英文对话，一字不动
  反例：i love this game（无游戏词）-> 不纠
  正例：enemi in heaven（含 heaven）-> 可纠 enemi

闸门 B「不是普通英文词」：待纠的词本身不能是常见英文单词
  love / friend / good / player / help / please / much / fire …
  这些词即使骨架撞上也不动。
  反例：nice shot my friend -> friend 是常见词 -> 不动
  正例：enemi / spik / thay -> 非英语词 -> 可纠

再加一条「整句模糊匹配」通道（更安全的兜底）
------------------------------------------
整句与已知报点做编辑距离比对，够近就整句替换。
这条比逐词更保守也更有效："enemi in heaven" 直接对到
"enemy in heaven"，不需要逐词猜。

设计原则：宁可漏纠，不可误改。
用户听到一句莫名其妙的话，比听到一句原样英文糟糕得多。
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher

# ---------------------------------------------------------------------------
# 常见英文词保护表（闸门 B）
# ---------------------------------------------------------------------------
# 只收「在游戏语音里可能出现、但本身是正常英语」的词。
# 这些词即使辅音骨架与游戏词相撞也绝不动。
# 【v0.2.9 硬闸门】用真实英语常用词表，而不是手工维护停用词。
# 手工补停用词实测无法收敛（第1轮误伤9/12 -> 补 -> 3/15 -> 再补 -> 1/15
# -> 还会继续冒出来），所以改成「在英语常用词表里 = 一律不动」。
from .english_words import COMMON_EN as _COMMON_EN_BASE

# 规则而非手工补词：英语常用词表的屈折形式一并保护。
# 补 "lights"/"fades"/"sages" 这类是打地鼠；把 +s/+es/+ed/+ing
# 一次性派生出来才是根治（v0.2.10 实测踩到 "lights" 被改成 "ult"）。
_COMMON_EN = set(_COMMON_EN_BASE)
for _w in _COMMON_EN_BASE:
    _COMMON_EN.add(_w + "s")
    if _w.endswith("e"):
        _COMMON_EN.add(_w + "d")
        _COMMON_EN.add(_w[:-1] + "ing")
    else:
        _COMMON_EN.add(_w + "ed")
        _COMMON_EN.add(_w + "ing")

# 只在"上下文成立"时才允许纠错的词（闸门 A 的判定依据）
# 这些是确定无疑的游戏词
# ---------------------------------------------------------------------------
# 显式游戏词表（v0.2.9）
# ---------------------------------------------------------------------------
# 踩过的坑：靠抓 local_rules 各字典的键建词表，实测只得 121 词，
# 且最关键的游戏词全缺（enemy/they 被英语词表过滤、spike 只有多词键），
# 纠正率实测 0/6 —— 词表里根本没有要纠的词。
# 改成显式清单：可审查、可扩充、不受上游字典结构变化影响。
GAME_TERMS = set("""
    "ult", "ulti", "os", "ox",
    # --- 爆能器（最高频，也是最容易被听错的）---
    "spike", "plant", "planted", "defuse", "defusing", "defused", "ninja",
    "carry", "carrying", "drop", "dropped", "postplant",
    # --- 道具 ---
    "flash", "smoke", "molly", "boom", "nade", "util", "ult", "orb",
    "recon", "drone", "trap", "heal", "tp", "wall", "teleport",
    "decoy", "dog", "arrow", "beacon", "cannon", "stun",
    # --- 报点 / 位置 ---
    "heaven", "hell", "mid", "midway", "site", "spawn", "main", "long",
    "short", "link", "top", "bottom", "anchor", "tree", "garage", "hut",
    "tunnel", "boathouse", "window", "cubby", "pillar", "stair",
    "market", "tower", "sewer", "pit", "conduit", "vent",
    # --- 战术动作 ---
    "rotate", "rotating", "peek", "peeking", "trade", "flank", "lurk",
    "boost", "boosting", "stack", "rush", "contact", "default", "retake",
    "clutch", "eco", "push", "pushmid", "hold", "camp", "save",
    "entry", "drypeek", "swing", "doublepeek", "shoulderpeek",
    "widepeek", "jigglepeek", "wallbang", "prefire", "oneshot",
    "tap", "spam", "spray", "tapping", "covering", "tradekill",
    "getshot", "onelife", "onemore",
    # --- 沟通 ---
    "care", "clear", "gamble", "shuffle", "follow", "regroup",
    "help", "here", "first", "second", "third", "fourth", "fifth",
    "frag", "topfrag", "bottomfrag", "ace", "clutched", "tilt",
    "tilted", "winnable", "yolo", "gg", "ggwp", "glhf", "hf", "gj",
    "ty", "thx", "mb", "srry", "afk", "brb", "ggwp",
    "noob", "stfu", "hax", "cheater", "throw", "fill", "smurf",
    "boosting", "lurking", "saving", "trading", "flanking",
    "guarding", "reconning", "healing", "defusing", "planting",
    # --- 武器 ---
    "vandal", "phantom", "guardian", "operator", "marshal", "outlaw",
    "ghost", "classic", "sheriff", "frenzy", "shorty", "judge",
    "bucky", "stinger", "spectre", "bulldog", "odin", "ares",
    "knife", "melee",
    # --- 英雄（英文名，ASR 常听错）---
    "jet", "jets", "raze", "phoenix", "reyna", "yoru", "neon",
    "iso", "waylay", "sova", "breach", "skye", "kayo", "fade",
    "gekko", "tejo", "brim", "brimstone", "viper", "omen", "astra",
    "harbor", "clove", "miks", "cypher", "sage", "killjoy",
    "chamber", "deadlock", "vyse", "veto",
    # --- 高频主语/代词（ASR 极容易听错，且不在 GAME_TERMS 里导致漏纠）---
    "enemy", "enemies", "they", "them", "their", "player", "players",
    "guy", "teammate", "mate", "buddy", "bro", "dude",
    "one", "two", "three", "four", "five", "someone", "somebody",
""".split())

# 清洗：上面的 split 是对源码文本切分，会把引号和逗号一起带出来
# （实测把 heaven 变成带引号逗号的脏 token，纠错后句子多了 "heaven",）
GAME_TERMS = {w.strip("\"',;:. ") for w in GAME_TERMS if w.strip("\"',;:. ")}

_ANCHORS = {
    "spike", "spikes", "flash", "smokes", "smoke", "ult", "orbs", "orb",
    "plant", "planted", "defuse", "defusing", "defused",
    "rotate", "rotating", "peek", "peeking", "trade", "flank",
    "heaven", "hell", "mid", "midway", "recon", "drone", "trap",
    "clutch", "boost", "boosting", "ninja", "stack", "lurk",
    "rush", "contact", "default", "retake", "eco", "nade", "molly",
    "gun", "vandal", "phantom", "operator", "guardian", "sheriff",
    "judge", "bucky", "odin", "ares", "spectre", "stinger", "bulldog",
    "cyber", "cypher", "sage", "killjoy", "brimstone", "viper",
    "omen", "astra", "harbor", "neon", "jett", "raze", "reyna", "sova",
    "breach", "skye", "fade", "gekko", "yoru", "phoenix", "chamber",
    "main", "long", "short", "link", "top", "bottom", "anchor", "tree",
    "garage", "hut", "tunnel", "boathouse", "heaven", "dish",
}
# 锚点统一用显式游戏词表（比手工维护可靠）
_ANCHORS = set(GAME_TERMS)


# ---------------------------------------------------------------------------
# 辅音骨架
# ---------------------------------------------------------------------------
_VOWELS = "aeiouy"
_SIM = {
    "ph": "f", "gh": "", "ck": "k", "qu": "k", "wh": "w",
    "kn": "n", "wr": "r", "ps": "s", "ce": "s", "ci": "s",
    "x": "ks", "z": "s", "j": "y",
}
# v/f/w 归一（口音里互通：love 听起来像 low）
_CONS_CLASS = {"v": "f", "w": "f"}
# 词尾：先剥离再算骨架（spike/spicks、flash/flashed 靠这个对上）
# "in" 是为了英语 -ing 在快语速下丢掉尾部 g 的情况 —— 实测
# "they are stackin b" 本地没接住，一路走云端被译成「堆叠」，
# 而社区说的是「赌点」。加一条规则覆盖 stackin / rotatin /
# defusin / boostin / plantin 一整类，不用逐个补词。
# _strip_suffix 里有「剥完至少剩 3 个字母」的保护，
# 所以 in / sin / win / skin 这类短词不会被剥没。
_SUFFIXES = ("ing", "ed", "es", "in", "s")


def _strip_suffix(w: str) -> str:
    for suf in _SUFFIXES:
        if w.endswith(suf) and len(w) - len(suf) >= 3:
            return w[: -len(suf)]
    return w


def _skeleton(word: str, strip_suffix: bool = True) -> str:
    w = re.sub(r"[^a-z]", "", (word or "").lower())
    if not w:
        return ""
    if strip_suffix:
        w = _strip_suffix(w)
    for k, v in _SIM.items():
        w = w.replace(k, v.upper())
    out = []
    for ch in w:
        if ch.isalpha() and ch not in _VOWELS:
            c = ch.lower()
            out.append(_CONS_CLASS.get(c, c))
    return "".join(out)


def _ratio(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


# ---------------------------------------------------------------------------
# 词表
# ---------------------------------------------------------------------------
_VOCAB: dict | None = None
# v0.2.10：已知报点索引（_validates 用），只建一次
_PHRASE_IX: dict | None = None
# v0.2.10 性能：按首词骨架建索引，match_phrase 只比首词骨架相同的候选
_PHRASE_BY_SK: dict | None = None


def _build_vocab() -> dict:
    from .local_rules import (_GEAR, _PLACE, _ACT, _REPLY,
                              _TRANSLATE_FIRST, _V25)
    words: set = set()

    def _single_keys(d) -> set:
        """只取单词键。

        踩过的坑：多词键（如 "on me"）被 _skeleton 拼成 "onmy"，
        骨架恰好等于 "enemy" 的 "nmy"，于是 enemy 被替换成 "on my"
        —— 实测误伤 "the enemy team is here" -> "the on me team is here"。
        多词键交给整句匹配通道（match_phrase），不进词表。
        """
        return {str(k).lower() for k in d
                if str(k) and " " not in str(k)}

    for src in (_PLACE, _GEAR, _ACT):
        words |= _single_keys(src)
    words |= _single_keys(_REPLY)
    words |= _single_keys(_TRANSLATE_FIRST)
    words |= _single_keys(_V25)
    # GAME_TERMS 是主力（显式、可靠），字典键只作补充
    #
    # v0.2.10 修正确定性 bug
    # ----------------------
    # 原来直接遍历 set(candidates)，而 Python 的 set 迭代顺序受
    # PYTHONHASHSEED 随机化影响 —— 骨架冲突时胜出的词每次运行可能不同。
    # 实测就撞上了：vocab['nm'] 变成了 'enemies'（应为 'enemy'），
    # 于是长度差 2 被闸门挡掉，enemi mid 纠不了。
    # 对翻译工具来说结果不可复现是不可接受的：
    # 用户只会说「昨天还对今天不对」，日志里什么也看不出来。
    #
    # 现在遍历顺序完全确定，冲突优先级写成显式规则：
    #   a) 显式游戏词表 > 从字典抓来的
    #   b) 同为游戏词 -> 取更短的（enemy 比 enemies 喊得多）
    #   c) 仍相同 -> 取字典序（保证确定性）
    candidates = sorted(set(GAME_TERMS) | words)

    def _priority(w: str) -> tuple:
        # 越小越优先
        return (0 if w in GAME_TERMS else 1, len(w), w)

    vocab: dict = {}
    for w in candidates:
        if len(w) < 3:
            continue
        sk = _skeleton(w)
        if len(sk) < 2:
            continue
        # 英语常用词一律不收进游戏词表（硬闸门）
        # 但 GAME_TERMS 里的词即使与英语同形也要收 ——
        # 它们在游戏语音里是报点，语境由 _has_context 闸门保证。
        if w in _COMMON_EN and w not in GAME_TERMS:
            continue
        prev = vocab.get(sk)
        if prev is None or _priority(w) < _priority(prev):
            vocab[sk] = w
    return vocab


def _vocab() -> dict:
    global _VOCAB
    if _VOCAB is None:
        try:
            _VOCAB = _build_vocab()
        except Exception as e:
            import logging
            logging.getLogger("valtrans.accent").warning(
                "口音词表构建失败：%r", e)
            _VOCAB = {}
    return _VOCAB


def _has_context(text: str) -> bool:
    """闸门 A：整句里是否已有确定的游戏词。"""
    for w in re.findall(r"[a-z']+", (text or "").lower()):
        if w in _ANCHORS or w.rstrip("s") in _ANCHORS:
            return True
        if _skeleton(w) in _vocab() and w not in _COMMON_EN:
            return True
    return False


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------
_ACCEPT = 0.86


def _phrase_index() -> dict:
    """已知报点 -> 规范化形式，按长度倒序（长的先匹配）。只建一次。"""
    global _PHRASE_IX
    if _PHRASE_IX is None:
        ix: dict = {}
        for ph in _phrases():
            p = re.sub(r"[^a-z0-9 ]", " ", ph.lower())
            p = re.sub(r"\s+", " ", p).strip()
            # 只收多词短语：单词短语不能当证据
            # （任何含该词的句子都会"匹配"它，实测踩过）
            if len(p.split()) >= 2:
                ix[p] = ph
        _PHRASE_IX = dict(sorted(ix.items(), key=lambda kv: -len(kv[0])))
    return _PHRASE_IX


def _validates(sentence: str) -> bool:
    """纠错后的句子能否被独立信号验证 —— 即是否包含某条已知报点。

    这是词级通道的**自证闸门**。三轮打地鼠后换了判据：
    纠错不再靠「我觉得骨架像」，而靠「改完句子里真的出现了标准报点」。

    为什么是「包含」而不是「整句相似」
    ------------------------------
    句子常比报点长一截，整句相似度会被无关词稀释：
        "they are boosting heaven" vs "boosting heaven" 只有 0.79，
        明明含报点却过不了 0.80 的线。
    那是判据选错了，调阈值只会拆东墙补西墙。
    纠错改的是一个词，真正要看的正是「改完之后报点出现了没有」。

    误伤与真纠错在这一点上完全可分：
      "sage advice" -> "sage defusing"  不含任何报点 -> 回滚
      "he is wise"  -> "he is vyse"     不含任何报点 -> 回滚
      "enemi mid"   -> "enemy mid"      含 "enemy mid" -> 保留
    """
    core = re.sub(r"[^a-z0-9 ]", " ", (sentence or "").lower())
    core = re.sub(r"\s+", " ", core).strip()
    if len(core) < 4:
        return False
    for p in _phrase_index():
        if p in core:
            return True
    return False




# ---------------------------------------------------------------------------
# 词级音形纠错（自证式）
# ---------------------------------------------------------------------------
def correct_accent(text: str) -> tuple[str, int]:
    """口音误识纠正（自证式）。返回 (修正后, 改动数)。

    三道闸门缺一不可：
      A 上下文：句中已有游戏语境信号，否则不动
      B 非英语：待纠词不在英语常用词表（含屈折形式）里
      C 自证：  改完必须能落回某条已知报点，验证不过就整句回滚

    长度闸门有方向：真实 ASR 误识几乎都是「词变短或持平」
      spik -> spike(+1) / rotateing -> rotate(-3) / enemi -> enemy(0)
    凭空拉长 2 个字母以上基本是骨架碰撞而非误识
    （实测 advice(6) -> defusing(8) 就是这么被误改的）。

    宁可漏纠，不可误改 —— 用户听到一句被改坏的句子，
    比听到一句原样英文糟糕得多。
    """
    raw = (text or "").strip()
    if not raw:
        return raw, 0

    # 【显式映射 v0.2.11】ASR 常把 ULT 听成 os/ox——2 字母超短词进不了
    # 音形匹配（下方 len<3 跳过），且误听词本身无法建立游戏语境（闸门 A
    # 对它必然失效），所以放在所有闸门之前硬替换。
    # os/ox 在英语口语里几乎不单独出现，误替换风险极低。
    _hard, _n = re.subn(r"\b(os|ox)\b", "ult", raw, flags=re.I)
    if _n:
        raw = _hard

    if not _has_context(raw):            # 闸门 A
        return raw, 0

    vocab = _vocab()
    if not vocab:
        return raw, 0

    changed = 0
    out = raw
    for tk in re.findall(r"[A-Za-z']+", raw):
        low = tk.lower().strip("'")
        if len(low) < 3:
            continue
        if low in _COMMON_EN:             # 闸门 B（含 lights/fades/sages 屈折形）
            continue
        if low in _ANCHORS:
            continue

        sk = _skeleton(low)
        if len(sk) < 2:
            continue
        cand = vocab.get(sk)
        if not cand or cand == low:
            continue
        if len(cand) - len(low) > 1:
            continue
        if len(low) - len(cand) > 3:
            continue
        if cand not in GAME_TERMS:
            continue
        pat = re.compile(rf"\b{re.escape(tk)}\b", re.I)
        cand_sentence, n = pat.subn(cand, out)
        # 闸门 C：自证 —— 改完必须落回已知报点，否则回滚这一步
        if n and _validates(cand_sentence):
            out = cand_sentence
            changed += n

    return out, changed


# ---------------------------------------------------------------------------
# 整句模糊匹配（更保守的兜底通道）
# ---------------------------------------------------------------------------
_PHRASES: list = []


def _phrases_by_skeleton() -> dict:
    """首词骨架 -> 候选短语列表（长度倒序）。

    match_phrase 的闸门 3 本来就要求「首词辅音骨架必须一致」，
    所以按骨架建索引只是把那条判据提前到筛选阶段 —— 白捡的性能。
    短语表补了双词报点后有 500+ 条，全表线性扫编辑距离要 2.1ms/句；
    建索引后只比首词骨架相同的那一小撮。
    """
    global _PHRASE_BY_SK
    if _PHRASE_BY_SK is None:
        ix: dict = {}
        for ph in _phrases():
            p = re.sub(r"[^a-z0-9 ]", " ", ph.lower())
            p = re.sub(r"\s+", " ", p).strip()
            if not p:
                continue
            sk = _skeleton(p.split()[0])
            ix.setdefault(sk, []).append(p)
        _PHRASE_BY_SK = {k: sorted(v, key=len, reverse=True)
                         for k, v in ix.items()}
    return _PHRASE_BY_SK


def _phrases() -> list:
    global _PHRASES
    if not _PHRASES:
        from .local_rules import _V25
        keys = {str(k).lower() for k in _V25 if len(str(k)) >= 6}
        keys |= {"enemy in heaven", "enemy on heaven", "they planted spike",
                 "im rotating long", "ninja defuse", "can you flash me",
                 "give me orb", "spike dropped mid", "two mid one a",
                 "one flash one flash", "i have ult", "he is low",
                 "im low dont peek", "retake now", "boosting heaven"}

        # 高频双词报点（显式列出，不做全组合：236 词两两组合 2.7 万条
        # 太慢，而实际语音高频的就是「主语/数量 + 位置/动作」这一类）。
        # 补【已知报点】是有限可审查的；补【停用词】才是无底洞 ——
        # 本项目已在停用词上失败三轮，不再回头。
        for _subj in ("enemy", "enemies", "he", "she", "they", "we",
                      "one", "two", "three", "someone"):
            for _pl in ("mid", "heaven", "hell", "a main", "b main",
                        "a short", "b short", "a long", "b long",
                        "a site", "b site", "main", "long", "short",
                        "link", "garage", "boathouse", "window"):
                keys.add(f"{_subj} {_pl}")
        for _act in ("rotate", "flank", "stack", "lurk", "recon",
                     "defuse", "plant", "retake", "boost", "trade",
                     "save", "clutch", "default"):
            for _pl in ("mid", "heaven", "hell", "a main", "b main",
                        "a site", "b site", "long", "short"):
                keys.add(f"{_act} {_pl}")
            # 单字母点位：实战极常见，之前漏了这一档
            #（实测 "stack b" 不在表里 -> 自证不过 -> 走云端
            #   被译成「堆叠」，而社区说的是「赌点」）
            for _pl in ("a", "b", "c"):
                keys.add(f"{_act} {_pl}")
        for _act in ("stack", "gamble", "holding", "hold"):
            for _pl in ("a", "b", "c"):
                keys.add(f"{_act} {_pl}")
        keys |= {"enemy here", "enemy close", "enemy far", "enemy low",
                 "enemy dead", "enemy one", "enemy two", "two enemies",
                 "one enemy", "three enemies", "they are pushing",
                 "they are coming", "they are rotating", "he is pushing",
                 "no enemies", "no enemy", "any enemies", "spike dropped",
                 "spike planted", "spike on mid", "flash me", "flash me now",
                 "throw a flash", "throw me a flash", "give me flash",
                 "give me smoke", "i need ult", "need a flash",
                 "cover me", "cover my flash", "im one hp", "one hp left",
                 "he is one", "he is low", "he is dead", "she is low"}

        _PHRASES = sorted(keys, key=len, reverse=True)
    return _PHRASES


def match_phrase(text: str, threshold: float = 0.93) -> str | None:
    """整句与已知报点比对，够像就替换。返回标准写法或 None。

    v0.2.10：这条通道一度是整个纠错链里最危险的一环 ——
    它**绕过了 correct_accent 的两道闸门**（上下文 / 非英语词），
    实测把普通英语改坏：
        the lights fade away -> the ult fade away
        sage advice          -> sage defuse
        he is wise           -> he is vyse
    整串替换不可逆，误判的代价远大于漏判，所以现在有四道闸门：

      闸门 1  上下文：句中须有游戏语境信号，否则一律不碰
      闸门 2  长度：  只处理 <=5 词的短报点，长句交给逐词通道
      闸门 3  首词：  首词辅音骨架须与候选首词相同
             （he is wise / he is vyse 就是在这一步被挡掉的）
      闸门 4  相似度 0.93（原来 0.86 太松）
    """
    raw = (text or "").strip().lower()
    if not raw:
        return None

    # 闸门 1：上下文
    if not _has_context(text):
        return None

    core = re.sub(r"[^a-z0-9 ]", " ", raw)
    core = re.sub(r"\s+", " ", core).strip()
    if len(core) < 6:
        return None

    # 闸门 2：只处理短报点（长句风险远大于收益）
    words = core.split()
    if len(words) > 5:
        return None

    sk0 = _skeleton(words[0])

    # 索引：只看首词骨架相同的候选（闸门 3 的判据提前到筛选）
    cands = _phrases_by_skeleton().get(sk0, ())
    if not cands and sk0:
        cands = ()
    best, best_r = None, 0.0
    for p in cands:
        if abs(len(p) - len(core)) > max(3, len(core) // 3):
            continue
        # 闸门 2：候选也必须是短报点
        if len(p.split()) > 5:
            continue
        r = _ratio(core, p)
        if r > best_r:
            best, best_r = p, r
    if best and best_r >= threshold:
        return best
    return None





