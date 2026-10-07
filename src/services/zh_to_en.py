# -*- coding: utf-8 -*-
# 作者: cing  ·  https://github.com/cingzz
# 许可: GPL-3.0 + 商业授权（闭源/商用需向作者申请授权），见 LICENSE 与 LICENSE-COMMERCIAL.md
#
"""中译英游戏黑话表 —— 反向翻译（PTT）的核心。

问题背景
--------
用户说中文"我的发"，系统直译成 "my hair"（我的头发），完全错。
原因：**"我的发" 是 "my spike" 的谐音**，同类的还有"我的fuck" = "wtf"。
中文玩家的黑话大量依赖**谐音**和**俗称**，直译必然出错。

设计原则（用户明确要求）
------------------------
1. **要俗不要官方**：用玩家之间实际会说的话，不用官方书面语。
   ✗ "The spike carrier is dropping down"   ✓ "he's dropping, spike is down"
   ✗ "Initiating a full buy purchase"      ✓ "full buy"
2. **保留粗俗语气**：脏话就是脏话，不要美化成书面语。
3. **谐音要还原**：中文谐音 → 英文原词。
4. **短**：游戏语音要快，短词优先（"go B" 不是 "We are now rotating to site B"）。

用法
----
    from zh_to_en import translate_zh_to_en
    en, how = translate_zh_to_en("我的发")
    # -> ("spike down", "黑话表")
"""
from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# A. 中文谐音黑话 → 英文游戏术语
#    谐音类：中文发音接近英文游戏词
# ---------------------------------------------------------------------------
_HOMOPHONE = {
    # ★ 谐音脏话（用户实测确认）："我的发" = "我的 wtf" = what the fuck
    #   这类谐音在中文玩家圈很常见，直译成 "my hair" 就完全废了。
    "我的发": "wtf", "我发": "wtf", "我滴发": "wtf", "我的法": "wtf",
    "我的fuck": "wtf", "我fuck": "wtf", "我的服": "wtf", "我服了": "wtf",
    # 包相关（真的在说包时）
    "埋发": "spike down", "买发": "spike down", "我的包": "spike down",
    "埋了": "spike down", "我的包": "spike down", "我包": "spike down",
    "包掉了": "spike down", "包已下": "spike is down",
    # 下包 / 拆包（直译会变成"种植尖刺"，必须纠正）
    "下包": "plant the spike", "安包": "plant the spike", "放包": "plant the spike",
    "种包": "plant the spike", "插包": "plant the spike",
    "拆包": "defuse", "拆雷": "defuse", "拆弹": "defuse",
    "偷包": "ninja defuse", "假拆": "fake defuse", "强拆": "sticking",
    "打龙": "defuse the spike", "拆龙": "defuse the spike",
    "瞬闪": "pop flash", "单向烟": "one-way smoke",
    "交叉火力": "crossfire", "发枪": "drop me a gun", "发我一把": "drop me one",
    "断后": "lurk", "残局": "clutch", "白给": "feeding",
    "架人": "camp them", "大残": "one shot", "换人": "trade",
    "补枪": "trade kill", "大身位拉": "wide peek", "小身位骗": "shoulder peek",
    "穿射": "spam", "点了他": "i lit him", "杀最多": "top frag",
    "杀最少": "bottom frag", "假打": "fake", "绕屁股": "flank",
    "全枪全弹": "full buy", "太卡了": "im lagging", "高台": "heaven",
    "我有钱": "i got money", "我有米": "i got money", "我有大": "i got my ult",
    "进点": "push in", "一枪死": "one shot me", "老六": "camper",
    "大拉": "wide swing", "小拉": "jiggle peek", "老六": "lurker",
    "爆龙": "spike will explode", "龙爆了": "spike is ticking",
    # 经济
    "起枪": "full buy", "全起": "full buy", "满枪": "full buy",
    "半起": "half buy", "强起": "force buy", "穷起": "eco buy",
    "省钱": "saving", "存枪": "saving", "保枪": "saving", "留钱": "saving",
    "没钱": "no credits", "给钱": "buy me", "发枪": "drop me a gun",
    # 战术动作
    "干拉": "dry push", "干点": "dry push", "硬拉": "dry push",
    "转点": "rotate", "转B": "rotate B", "转A": "rotate A",
    "支援": "rotate to help", "增援": "rotating in", "帮忙": "help",
    "架枪": "hold the angle", "架住": "hold", "守点": "hold site",
    "守住": "hold", "守": "hold",
    "拉枪线": "peek", "探身": "peek", "拉出来": "peek",
    "摸点": "scout the site", "侦查": "recon", "探点": "recon",
    "补枪": "finish him", "收人头": "finish", "收割": "exit frag",
    "穿点": "wallbang", "穿墙": "wallbang", "穿点打": "wallbang",
    "冲": "rush", "rush他们": "rush them", "冲点": "rush the site",
    "冲了": "going in", "莽": "rush in", "莽了": "rush in",
    "绕后": "flank", "包抄": "flank", "绕后他们": "flank them",
    "走单": "lurk", "断后": "lurk", "蹲后": "lurk",
    "压": "push", "压上去": "push up", "压点": "push site",
    "溜": "flank quietly", "偷": "ninja", "摸": "scout",
    "卡点": "hold site", "卡枪": "prefire", "预瞄": "prefire",
    "架狙": "hold the op angle", "架狙位": "op angle",
    "一枪一个": "one tap", "秒了": "one shot", "秒掉": "one tap",
    "爆头": "dink", "打头": "dink", "爆了": "dinked",
    "换血": "trade", "换人": "trade", "补我": "trade me",
    "抗压": "tank", "抗": "hold off",
    "堆点": "stack site", "赌点": "stack site",
    "夹击": "split", "分两路": "split", "两头": "split",
    "假打": "fake", "骗点": "fake",
    # 装备/技能
    "给我闪": "flash me", "给我闪光": "flash me", "来个闪": "flash me",
    "闪我": "flash me", "我给闪": "flashing", "我闪": "flashing",
    "闪了": "flashed", "被闪": "flashed",
    "烟": "smoke", "放烟": "smoke", "烟雾": "smoke", "封烟": "smoke",
    "火": "molly", "燃烧弹": "molly", "放火": "molly", "烧": "molly",
    "大招": "ult", "开大": "ult", "大招好了": "ult ready", "大有了": "ult up",
    "侦查技能": "recon", "侦查器": "recon", "无人机": "drone",
    "盾": "shield", "护甲": "shield", "重甲": "heavy shield",
    "轻甲": "light shield", "枪": "gun", "狙": "op", "_operator_": "op",
    "警长": "sheriff", "幻影": "phantom", "幻锋": "vandal", "暴徒": "vandal",
    "技能": "utility", "道具": "utility", "道具好了": "utility ready",
    # 位置
    "中路": "mid", "中": "mid", "中路远点": "top mid", "中路近点": "bottom mid",
    "A点": "A site", "B点": "B site", "C点": "C site", "包点": "site",
    "A大": "A main", "A小": "A short", "A长": "A long",
    "B大": "B main", "B小": "B short", "B长": "B long",
    "长道": "long", "小道": "short", "连接道": "link", "链接": "link",
    # v0.2.11：英文端译「二楼/下层」了，反查必须认这两个词。
    # 保留「天堂/地狱」做兼容 —— 玩家自己打这两个词时也认。
    "二楼": "heaven", "下层": "hell",
    "天堂": "heaven", "地狱": "hell", "second floor": "heaven",
    "出生点": "spawn", "攻方出生点": "attacker spawn", "守方出生点": "defender spawn",
    "高台": "high ground", "楼上": "up top", "楼下": "down below",
    "后台": "back", "前线": "front", "角落": "corner", "凹槽": "pocket",
    "门后": "behind the door", "复活点": "respawn",
    "出生": "spawn", "回防": "retake", "回防A": "retake A", "回防B": "retake B",
    "包已下": "post plant", "包没下": "no plant",
}

# ---------------------------------------------------------------------------
# B. 中文粗口/情绪 → 英文粗口（用户明确要求：不要美化成书面语）
# ---------------------------------------------------------------------------
_PROFANITY = {
    "操": "fuck", "卧槽": "what the fuck", "我操": "fuck",
    "靠": "damn", "我靠": "oh my god", "靠北": "wtf",
    "他妈": "fucking", "他妈个": "fucking", "你他妈": "you fucking",
    "什么鬼": "wtf", "什么玩意": "what the hell", "啥玩意": "what the hell",
    "有病": "are you fucking serious", "有病吧": "are you fucking insane",
    "傻逼": "idiot", "傻B": "idiot", "煞笔": "retard", "沙比": "idiot",
    "废物": "trash", "垃圾": "garbage", "辣鸡": "garbage", "垃圾游戏": "this game is trash",
    "坑货": "troll", "坑": "troll", "坑人": "trolling",
    "滚": "get lost", "滚蛋": "get fucked", "去死": "go die",
    "神经病": "psycho", "疯子": "crazy", "白痴": "moron",
    "烂": "bad", "烂透了": "this is garbage", "恶心": "disgusting",
    "sb": "asshole", "傻x": "asshole", "二逼": "idiot",
    "废物一个": "useless", "没用": "useless", "菜": "noob", "太菜": "so bad",
    "手残": "my aim is bad", "瞄不准": "bad aim",
    "wtf": "wtf", "what": "wtf",
}

# ---------------------------------------------------------------------------
# C. 短语黑话（多词）
# ---------------------------------------------------------------------------
_PHRASES = {
    "别浪": "don't overpush", "别送": "don't feed", "别冲": "don't rush in",
    # ★ v0.2.17：真机 实测——「猎枭别去打了」此前整句没人认领。
    #   黑话祈使句直接收进表；配合引擎先换好英雄名，本地 0ms 拼出整句
    #   （"Sova don't push"），拼不完整落云端。
    "别去打了": "don't push", "别打了": "don't fight", "别单摸": "don't lurk",
    # 「钱包」= 尚勃勒(Chamber) 的哨位/传送点（真机 定义）。
    # 只收整句：片段替换会拆坏语序（"Chamber tp play lurk"），整句才安全。
    "钱包别单摸了": "don't push chamber tp solo",
    "钱包别单摸": "don't push chamber tp solo",
    "别急": "wait", "别动": "hold position", "稳住": "hold steady",
    "等我": "wait for me", "跟紧": "stick with me", "跟上": "follow me",
    "一起": "together", "上": "go", "上了": "going in",
    "快点": "hurry up", "快": "fast", "赶紧": "hurry",
    "小心": "watch out", "注意": "watch out", "背后有人": "they're behind you",
    "身后": "behind", "头顶": "above", "脚下": "below",
    "过来": "come here", "来": "come", "走了": "leaving", "我走了": "g2g",
    "好的": "good", "行": "ok", "可以": "ok", "没问题": "no problem",
    "漂亮": "nice", "好枪": "nice shot", "干得好": "good job", "厉害": "well played",
    "打得好": "gg", "谢谢": "thanks", "抱歉": "sorry", "我的锅": "my bad",
    "尽力了": "nice try", "可惜": "nt", "再试": "gg try again",
    "冲鸭": "let's go", "开干": "let's go", "干了": "let's go",
    "稳住别浪": "hold steady don't overpush", "听我指挥": "follow my call",
    "我在前": "I'm on point", "我断后": "I'm lurking", "我先走": "I'll trade",
    "拿枪": "I got it", "给我": "I need one", "需要": "I need",
    "听到": "I hear", "看到": "I see", "看到了": "spotted", "看到人了": "spotted him",
    "有人": "contact", "遇敌": "contact", "一个人": "one", "两个": "two", "三个": "three",
    "四个": "four", "五个": "five", "很多人": "many", "一堆": "many",
    "包掉了": "spike down", "没包": "no spike",
    # --- 社区实战补充（用户实贴速查表）---
    "点没动静": "no sound", "A没动静": "A no sound", "B没动静": "B no sound",
    "没动静": "no sound",
    "小心A": "care A", "小心B": "care B", "小心中路": "care mid",
    "小心绕后": "care flank", "注意绕后": "watch the flank",
    "两个": "two", "两个以上": "two more", "三个以上": "three more",
    "两个点": "two",

    # --- v0.2.5 实测补漏（中译英，对应上面的英译中）---
    "我残了": "im low", "我残血": "im low", "我快没了": "im low",
    "别拉": "dont peek", "别拉枪线": "dont peek", "别前压": "dont push",
    "我有一滴血": "im one hp", "他一滴血": "hes one hp",
    "我有大招": "i have ult", "大招好了": "ult ready", "留大招": "save ult",
    "吸球": "get orb", "捡球": "get orb", "我要球": "get orb",
    "给我闪": "flash me", "给我闪个": "flash me", "丢个闪": "throw a flash",
    "给我烟": "smoke me", "丢个烟": "throw a smoke", "单向烟": "one-way smoke",
    "掩护我": "cover me", "补我": "trade me", "跟我": "follow me",
    "集合": "regroup", "回防": "fall back", "压点": "push site", "打点": "hit the site",
    "双架": "boost", "二楼拉枪线": "boosting heaven",
    "双架天堂": "boosting heaven", "双架A": "boost A",
    "在二楼": "in heaven", "在下层": "in hell", "在天堂": "in heaven",
    "在地狱": "in hell", "在高处": "on top",
    "包掉了": "spike down", "掉包了": "spike down", "他们掉包了": "they dropped",
    "他们下包了": "they planted", "拆包中": "defusing", "去拆包": "get the defuse",
    "打到了": "got him", "一枪": "one shot", "爆头": "headshot",
    "走走走": "go go go", "等等": "wait", "我来了": "on my way", "救我": "help me",
    "墙要掉了": "wall down", "墙没了": "wall down", "单项烟": "one-way smoke",
    "单向烟": "one-way smoke", "拆陷阱": "break trap", "拆花": "break trap",
    "打无人机": "shoot drone", "两个点": "two", "开我了": "hax on",
    "最后出现在": "last seen", "最后看到": "last seen",
    "没信息": "no info", "没见过他": "no info",
    "就在脸上": "close", "脸上了": "close",
    "残血": "low", "大残": "low", "一滴血": "one hp",
    "一百二": "one twenty", "一百一": "one one O", "一百": "one O O",
    "八十": "eighty", "别拉了": "dont peek", "别对枪": "dont peek",
    "别前压": "dont push", "别动": "hold position",
    "打狗": "shoot dog", "打无人机": "shoot drone", "打道具": "shoot it",
    "拖时间": "buy time", "卖他": "bait him", "卖队友": "bait",
    "去对枪": "fight", "开打": "fight", "双拉": "double peek",
    "点射": "single tap", "扫射": "spray", "穿射": "spam",
    "远视距下包": "open", "打开下包": "open",
    "赌A": "stack A", "赌B": "stack B",
    "假打": "fake", "吸球": "get orb", "捡球": "get orb",
    "要枪": "req", "要皮肤": "skin", "要奶": "heal me",
    "单摸": "play lurk", "潜伏": "lurk", "打慢点": "play slow",
    "他心态崩了": "he's tilted", "他大残": "he's low",
    "杀得最多": "top frag", "杀的最少": "bottom frag",
    "拼一把": "yolo", "还能赢": "winnable",
    "菜鸟": "noob", "别叫了": "stfu", "开挂了": "hax",
    "补位": "fill", "拉枪线": "boost", "双架": "boost",
    "炸鱼": "smurf",
    "买号": "acc", "投降": "ff", "开摆": "throw",
    "架枪": "hold", "架住": "hold",
    "蹲点": "camp", "走单": "lurk",
    "游走": "lurk", "架人": "camp", "超屁股": "flank",
    "静音接触": "contact", "提速": "rush", "放点": "open",
    "反清": "retake", "中路夹A": "mid to A", "跟进": "follow me",
    "还有一个": "one more", "有枪": "got gun", "包点空": "clear",


    "包点了": "spike down",
    "我大残": "I'm low",
    "压A点": "push A",
    "换人补枪": "trade",
    "走": "go",
    "快走": "let's go",
    "停": "stop",
    "我来": "on me",
    "我来处理": "on me",
    "退": "fall back",
    "撤退": "fall back",
    "推": "push",
    "推进": "push",
    "给闪": "flash me",
    "给个闪": "flash me",
    "给烟": "smoke me",
    "给个烟": "smoke me",
    "给侦查": "recon me",
    "我死了": "I'm dead",
    "A点没人": "A clear",
    "B点没人": "B clear",
    "中路没人": "mid clear",
    "他们在二楼": "enemy heaven",
    "敌人在二楼": "enemy heaven",
    "还有5秒": "5 seconds",
    "先手": "initiate",
    "对枪": "duel",
    "报点": "calling",
    "小心二楼": "watch heaven",
    "我闪了": "I'm flashing",
    "二楼没人": "heaven clear",}

# ---------------------------------------------------------------------------
# 匹配用的口语化归一（去掉语气词、标点、空格）
# ---------------------------------------------------------------------------
_FILLER = re.compile(r"[的地得啊呀吧呢吗嘛哦噢喔哈嗯阿诶]+")
# 只剥中文标点与结构噪声。
# 【v0.2.4 修复】这里原本含 ASCII ' 和 "，_strip_cn() 会把英文缩写
# 一并吞掉："he's low" -> "he s low"、"don't overpush" -> "don t overpush"。
# ASCII 引号/撇号是合法英文，必须保留。
# 只剥中文标点与结构噪声。
# 【v0.2.4 修复】这里原本含 ASCII ' 和 "，_strip_cn() 会把英文缩写一并吞掉：
#   "he's low" -> "he s low"、"don't overpush" -> "don t overpush"
# ASCII 引号/撇号是合法英文，必须保留。
_PUNCT = re.compile(r"[\s,，。?!！？;；:：~～\-—_/\\|]+")

# 长词优先（避免"包"先于"包点"匹配）
_ALL_TERMS = sorted(
    {**{k: v for k, v in _HOMOPHONE.items()},
     **{k: v for k, v in _PROFANITY.items()},
     **{k: v for k, v in _PHRASES.items()}}.items(),
    key=lambda kv: -len(kv[0]),
)


def _norm(s: str) -> str:
    return _PUNCT.sub("", (s or "").lower())


def translate_zh_to_en(text: str):
    """中文游戏黑话 → 英文。命中返回 (英文, 来源)；未命中返回 (None, '')。

    支持：
      1. 整句精确匹配（如"他们下包了" -> "they planted spike"）
      2. 片段替换（长词优先，如"他们在B点下包" -> "they planted on B"）
      3. 位置字母大小写保留（A/B/C 点）
    """
    raw = (text or "").strip()
    if not raw:
        return None, ""

    low = raw.lower()
    n = _norm(raw)

    # --- 1. 整句/整词精确匹配 ---
    for k, v in _ALL_TERMS:
        if n == _norm(k):
            return _preserve_sites(v, raw), "黑话表"

    # --- 2. 片段替换（长词优先，可多处命中）---
    out = raw
    hits = 0
    for k, v in _ALL_TERMS:
        kk = _norm(k)
        if len(kk) < 1:
            continue
        # 在归一串里找，找到后映射回原文下标较复杂；
        # 这里用「逐段扫描原文」的方式保证大小写与字母点位正确
        if kk in n:
            # 用正则在原文上定位（容忍中间的语气词差异）
            pat = _fuzzy_pattern(k)
            # 替换值前后补空格，避免 site+plant 粘成 siteplant
            rep = ' ' + v.replace("\\", "\\\\") + ' '
            new_out, cnt = pat.subn(rep, out)
            if cnt:
                out = new_out
                hits += cnt

    # --- 3. 去掉多余语气词 ---
    cleaned = _FILLER.sub("", out).strip()
    cleaned = re.sub(r"\s{2,}", " ", cleaned)

    if hits and cleaned:
        # 先补中英之间的空格（此时中文还在，是"插入"而非"删除"），
        # 再剥中文 —— 顺序反了会导致 holdmid / siteplant 这种粘连。
        cleaned = re.sub(r"([A-Za-z0-9])([\u4e00-\u9fff])", r"\1 \2", cleaned)
        cleaned = re.sub(r"([\u4e00-\u9fff])([A-Za-z0-9])", r"\1 \2", cleaned)
        # 【覆盖判据】残留中文占比过高 = 片段替换没吃干净
        # （如「集合打大龙」只命中「集合」-> regroup，丢掉「打大龙」），
        # 交回云端整句翻译更稳。
        _cn_src = len(re.findall(r"[\u4e00-\u9fff]", raw))
        _cn_left = len(re.findall(r"[\u4e00-\u9fff]", cleaned))
        if _cn_src and _cn_left / _cn_src > 0.35:
            return None, ""
        cleaned = _strip_cn(cleaned)
        cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()
        if cleaned:
            return _preserve_sites(cleaned, raw), "黑话表"
    return None, ""


def _strip_cn(s: str) -> str:
    """剥掉残留中文。

    片段替换后可能留下未收录的中文虚词（他们/我在/别走 之类）。
    这些不影响语义，去掉即可；若剥完还剩中文，说明匹配质量差，
    交回云端处理更稳妥。
    """
    return _PUNCT.sub(" ", re.sub(r"[\u4e00-\u9fff]+", " ", s))


def _fuzzy_pattern(term: str) -> re.Pattern:
    """把黑话词编成容忍语气词的正则：包点 -> 包[的]?点，允许中间夹语气词。"""
    chars = [re.escape(ch) for ch in term if not re.match(r"[\s\u4e00-\u9fffA-Za-z0-9]", ch)]
    # 允许最多 2 个任意中文字符插在词内（覆盖"我的发"这种）
    core = term[0] + "".join(
        (re.escape(ch) + "[的地得啊呀吧呢吗嘛哦噢哈嗯阿诶]{0,2}")
        for ch in term[1:])
    return re.compile(core)


def _preserve_sites(english: str, original: str) -> str:
    """修正点位字母大小写：中文输入里通常是 "a点"/"B点" 大小写不一致，
    英文输出必须统一成 A/B/C。"""
    def fix(m):
        return m.group(0).upper()
    english = re.sub(r"\b(a|b|c)(?=\s*(?:site|main|short|long|link|spawn))\b", fix, english,
                     flags=re.I)
    english = re.sub(r"\brotate\s+([abc])\b", lambda m: "rotate " + m.group(1).upper(), english,
                     flags=re.I)
    return english


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    cases = [
        ("我的发", "spike down"),
        ("我发", "spike down"),
        ("我他妈", "fucking"),
        ("什么鬼", "wtf"),
        ("你他妈有病吧", "you fucking are you fucking insane"),
        ("他们下包了", None),
        ("打龙", "defuse the spike"),
        ("起枪", "full buy"),
        ("干拉", "dry push"),
        ("转B", "rotate B"),
        ("给我闪光", "flash me"),
        ("守住中路", None),
        ("他们在B点下包了", None),
        ("别浪", "don't overpush"),
        ("漂亮", "nice"),
        ("ggwp", None),
        ("wtf", "wtf"),
    ]
    hit = 0
    print("中译英黑话表测试：")
    for src, _exp in cases:
        en, how = translate_zh_to_en(src)
        mark = "命中" if en else "未命中"
        if en:
            hit += 1
        print(f"  {src!r:16} {mark:6} {en or '(交云端)'}")
    print(f"\n命中率 {hit}/{len(cases)}")