# -*- coding: utf-8 -*-
# 作者: cing  ·  https://github.com/cingzz
# 许可: GPL-3.0 + 商业授权（闭源/商用需向作者申请授权），见 LICENSE 与 LICENSE-COMMERCIAL.md
#
"""本地游戏报点直译 —— 0 网络延迟，覆盖高频固定句式。

为什么需要这层
--------------
实测云端翻译的耗时与质量：
    "they planted spike on A" → 592ms → "他们在A点安放了炸弹"   ✓ 质量好但慢
    "go b"                    → 579ms → "去吧"                   ✗ 语义丢失
    "1 flash, 1 flash"        → 1284ms → 输出大段解释            ✗ 又慢又废

而游戏报点里**大量句子是固定结构**（报人数、报位置、报动作），
这些用规则匹配可以在**微秒级**给出准确译文，不该让模型去猜。

覆盖范围
--------
  · 报点数量：one/two/three + flash/smoke/heavy/light/shield/gun
  · 报点位置：A main / B short / mid / long / heaven / ladder ...
  · 常用动作：plant / defuse / rotate / peek / rush / stack ...
  · 极短指令：go B / rotate A / hold mid ...
命中即返回（text, 'local'），未命中返回 (None, '') 交由云端处理。
"""
from __future__ import annotations

import re

from . import provenance

# ---------------------------------------------------------------------------
# 报点数量（注意 ASR 常见误识别：one→won, two→to/too, three→tree/3）
# ---------------------------------------------------------------------------
_NUM = {
    "one": 1, "won": 1, "1": 1, "a": 1, "an": 1, "single": 1,
    "two": 2, "to": 2, "too": 2, "2": 2, "double": 2,
    "three": 3, "tree": 3, "3": 3, "triple": 3,
    "four": 4, "4": 4, "five": 5, "5": 5,
}
_NUM_CN = {1: "一", 2: "两", 3: "三", 4: "四", 5: "五"}

# ---------------------------------------------------------------------------
# 装备/技能报点
# ---------------------------------------------------------------------------
_GEAR = {
    "flash": "闪光", "flashes": "闪光", 
    "smoke": "烟", "smokes": "烟", "smoked": "烟",
    "heavy": "重甲", "heavy shield": "重甲", "heavy shields": "重甲", "heavy armor": "重甲",
    "light": "轻甲", "light shield": "轻甲", "light shields": "轻甲", "light armor": "轻甲",
    "shield": "护甲", "shields": "护甲", "armor": "护甲",
    # 「狙」是社区口头简写，只保留裸缩写（agents 表里 "op" 指向官方名
    # 冥驹；「1 op」这种报点说「一个狙」才自然，所以单独留这一条）。
    "gun": "枪", "guns": "枪", "weapon": "枪", "op": "冥驹",   # v0.2.19：原为「狙」。「狙」有歧义 ——
                      # 国服三把狙（冥驹/莽侠/飞将）口语是冥狙/莽狙/鸟狙，
                      # 单说「狙」玩家分不出是哪把（真机 纠正）。
                      # agents.WEAPONS["operator"]["cn"] 才是官方名的唯一来源。
    # 【v0.2.10 删除】sheriff / vandal / phantom / ghost 的重复条目
    # 原来这里写的是「警长 / 幻锋 / 幻影 / 鬼魅」——
    #   警长   不是国服官方名（官方=正义）
    #   幻锋   不是国服官方名（官方=狂徒）
    # 而 v0.2.10 新增的「整串精确查表」把 _GEAR 排在 agents 之前，
    # 于是这几个错名开始压过 agents.py 的正确官方名。
    # 已逐条核实国服官方译名（2026-10-03）：
    #   Vandal 狂徒 / Phantom 幻影 / Sheriff 正义 / Ghost 鬼魅
    #   Operator 冥驹 / Marshal 飞将 / Outlaw 莽侠 / Classic 标配
    #   Spectre 骇灵 / Shorty 短炮 / Judge 判官 / Bucky 雄鹿
    #   Stinger 蜂刺 / Ares 战神 / Odin 奥丁 / Bulldog 獠犬
    #   Guardian 戍卫
    # 英雄/武器名一律以 agents.py 为唯一来源，不在本表重复定义。
    # 本项目铁律：**固定名词单一来源**，任何表不得复制第二份。
    "ult": "大招", "ult ready": "大招好了", "ult online": "大招好了",
    "utility": "技能", "util": "技能", "recon": "侦查", "kit": "侦查",
    "drone": "无人机", "heal": "治疗", "wall": "墙",
}

# ---------------------------------------------------------------------------
# 位置（社区实战叫法，英文原名优先——国内玩家也直接说英文）
# ---------------------------------------------------------------------------
_PLACE = {
    # 通用
    "mid": "中路", "middle": "中路", "mids": "中路",
    "top mid": "中路远点", "bottom mid": "中路近点",
    "top": "上方", "bottom": "下方", "bot": "下方",
    # 社区简写（A小 / A大），不是书面语「A小道 / A大道」——
    #   需求背景（2026-10-03）：「a short，你就要立马知道是 A小」
    #   国内玩家口头就说「A小」「A大」，浮窗里写「A小道」反而看不懂
    "a main": "A大", "a long": "A大", "a short": "A小", "a link": "A连接",
    # v0.2.11 通顺度：'a short site' 逐词拼出「A点小道点位」，
    # 「点位」是多余的（site 本身在中文报点里就是「包点/点」）。
    "a short site": "A小包点", "a long site": "A大包点",
    # ★ v0.2.16：同表重复键清理——"b site"/"c site" 曾在下方重复定义
    #   为「B点/C点」，字典后者覆盖前者，A 却是「A包点」，口径不一。
    #   现各保留一份（生效值不变，仍是 B点/C点）。
    "a site": "A包点",
    "b main": "B大", "b long": "B大", "b short": "B小", "b link": "B连接",
    "c main": "C大", "c long": "C大", "c short": "C小",
    "b site": "B点", "c site": "C点",
    "a": "A点", "b": "B点", "c": "C点",
    "site": "包点", "spawn": "出生点", "lobby": "大厅",
    "att spawn": "攻方出生点", "def spawn": "守方出生点",
    "ct spawn": "守方出生点", "t spawn": "攻方出生点",
    # 常见地图点位
    # v0.2.11 全量修正（用户纠正：「拉枪线天堂」不通顺，必须是二楼）。
    # 依据：bilibili 国际服报点表 heaven=二楼 / hell=下层。
    # 「天堂/地狱」是硬翻，社区不这么叫。
    "heaven": "二楼", "hell": "下层", "long": "长道", "short": "小道",
    "garage": "车库", "market": "市场", "pizza": "披萨店", "cat": "长径小道",    "catwalk": "长径小道", "tree": "树位", "window": "窗口", "door": "门",
    "tower": "二楼", "screen": "屏风", "plat": "平台", "fox": "中路凹槽",
    "cubby": "凹槽", "pocket": "死角", "nest": "巢室", "hole": "洞",
    "generator": "发电机", "gen": "发电机", "wine": "酒窖", "pillar": "柱子",
    "tunnel": "隧道", "alley": "巷子", "ramp": "斜坡", "stairs": "楼梯",
    "vent": "通风口", "rope": "绳索", "ropes": "绳索", "hookah": "B点窗房",
    "tele": "传送点", "teleport": "传送点", "tp": "传送点",
    "roof": "屋顶", "bridge": "桥", "cave": "洞穴", "boiler": "锅炉房",
    "kitchen": "厨房", "bathroom": "浴室", "sewer": "下水道",    "fountain": "喷泉", "showers": "淋浴间", "crate": "木箱",
    "box": "箱子", "green box": "绿箱", "wood box": "木箱",
    "church": "教堂", "plaza": "广场", "ramen": "面馆", "cafe": "咖啡店",
    "trash": "拐角", "mail": "信箱", "cloud": "云字箱",
    "hut": "小屋", "root": "树根", "rubble": "石台", "mound": "土堆",
    "wheel": "水车", "waterfall": "瀑布", "crane": "起重机",
    "security": "保安室", "library": "图书馆", "yard": "庭院",
}

# ---------------------------------------------------------------------------
# 动作 / 状态
# ---------------------------------------------------------------------------
_ACT = {
    "planting": "在下包", "planted": "已下包", "plant": "下包",
    "defusing": "在拆包", "defuse": "拆包", "defused": "拆完了",
    "sticking": "在强拆", "stick": "强拆",
    "rotating": "在转点", "rotate": "转点",
    "flashing": "给闪", "flashed": "被闪了", "flash me": "给我闪个",     "smoking": "放烟", "nade": "雷", "molly": "燃烧弹", "fire": "火",    "rushing": "在冲", "rush": "冲", "pushing": "在压", "push": "推进",
    "holding": "在架", "hold": "架枪",
    "peeking": "在拉枪线", "peek": "拉枪线",
    "lurking": "在走单", "lurk": "走单",     "flanking": "在绕后", "flank": "绕后",
    # v0.2.11 通顺度：「stack b」逐词替换会拼成「赌点B点」（stack→赌点 +
    # b→B点）。这类「单字母点位」必须整串进表，否则多一个字读着就别扭。
    # （上次我把它加到了第 6 节的逐词累加区，那儿根本来不及命中。）
    "stacking": "在赌点", "stack": "赌点", "camp": "蹲点",
    "stack a": "赌点A", "stack b": "赌点B", "stack c": "赌点C",
    "stacking a": "赌点A", "stacking b": "赌点B", "stacking c": "赌点C",
    # 语序：中文地点在前 -> 「二楼赌点」不是「赌点二楼」
    # v0.2.11：语序 —— 中文地点在前，所以是「二楼赌点」不是「赌点二楼」。
    # （逐词拼装会拼成「赌点二楼」，所以这条必须整串命中）
    "stack mid": "赌点中路", "stack heaven": "二楼赌点",
    "camping": "蹲点", "camp site": "蹲点守",
    # v0.2.11：联网核实 trade = 人头互换 / 补枪。
    # 「换血」是误译（那是 HP 的事），玩家看到不知道该干嘛。
    # _ACT 里已有一条 "trade": "补枪"（_V25 里也有），同一键两个译文
    # 谁先被查到谁生效 —— 统一成同一个值，不要靠表的顺序决定。
    "trading": "在补枪", "trade": "补枪",
    "hitting": "在打", "hit": "打中了", "contacts": "遇敌", "contact": "遇敌",
    "one tapping": "一枪一个", "one tap": "一枪一个", "oneshot": "一枪一个",
    "tanking": "在抗压", "tank": "抗压",
    "reconing": "在侦查", "recon": "侦查",
    "healing": "在治疗", "revive": "在拉人", "rez": "在拉人",
    "jumping": "在跳", "dodging": "在闪避", "dodge": "闪避",
    "spotted": "看到了", "spotted him": "看到他了",
    "back": "我回来了", "regroup": "集合", "fallback": "后撤", "fall back": "后撤",
    "clutching": "在打残局", "clutch": "残局",
    "leaving": "我走了", "g2g": "我先走了",
}

# ---------------------------------------------------------------------------
# 回应 / 社交
# ---------------------------------------------------------------------------
_REPLY = {
    "nice": "漂亮", "nice shot": "好枪", "ns": "好枪",
    "thanks": "谢了", "ty": "谢了", "thx": "多谢", "thank you": "谢谢",
    "sorry": "抱歉", "sry": "抱歉", "my bad": "我的锅", "mb": "我的锅",
    "good try": "尽力了", "nt": "尽力了", "glhf": "祝好运", "gl": "祝好运",
    # v0.2.11 修正：上一轮误把 wp 也改成 GG。
    # WP = well played（玩得好），GG = good game（打得不错），
    # 联网核实：GJ=打得不错 / NS=好枪 / WP=玩得好 / TY=谢谢你。
    # 把 wp 也译成 GG 等于把两个缩写当同一个，玩家分不清。
    "gg": "GG", "wp": "玩得好", "ggwp": "GGWP",
    "ez": "轻松", "lmao": "笑死", "gg ez": "轻松拿下",
    "gj": "干得好", "good job": "干得好",
    "wait": "等等", "wait for me": "等我", "on me": "我来",
    "need help": "需要帮忙", "help": "帮忙", "im dead": "我死了",
    # v0.2.11：口径统一为「大残」（与 low / he is low 一致）。
    # 原来这里写「我残血」，_V25 写「我大残」—— 同一键两个译文，
    # 谁先被查到谁生效，于是主语在某些路径上还会整个丢掉。
    "im low": "我大残", "im one hp": "我一滴血",
}

# 无需翻译、直接透传的战术黑话
_PASSTHROUGH = {
    "go", "hit it", "execute", "watch out", "careful", "behind", "above", "below",
    "shoot", "left", "right", "swing", "cross",
    "jiggle peek", "wide peek", "shoulder peek", "wall bang", "wallbang",
    "prefire", "ninja defuse", "fake defuse", "tap", "one way",
    "igl", "default", "retake", "post plant", "eco", "force buy", "full buy",
}

# ---------------------------------------------------------------------------
# 透传前真译（v0.2.4）
# ---------------------------------------------------------------------------
# _PASSTHROUGH 是「原样弹英文」的黑名单，但它里混了不少
# 真正需要翻译的战术口令（retake / post plant / ninja defuse …）。
# 用户看不懂英文才装这个软件，透传等于没翻。
# 这张表在透传检查**之前**跑，保证翻译优先。
_TRANSLATE_FIRST = {
    # ★ v0.2.22：集合报点的字母喊话（需求「像这种 AAA，
    #   应该要翻成 a.a.a. 包点这种」）。
    #
    #   为什么单独立一组而不是靠 cloud 兜底：
    #     · 这是**最高频**的报点之一，每局喊几十次，丢云端就是几十次 400ms
    #     · 云端对 "aaa" 这种 3 字母输入的行为不可控（实测会当成乱码）
    #     · 译法在社区里是**唯一**的（A 就是 A 点），没有歧义 -> 可以登记
    #
    #   键形覆盖：ASR 常把长音写成 "aaa"/"aaaa"/"a a a"/"AAA."，
    #   带点的靠 normalize 前的原文匹配不到，故一并收录。
    "aaa": "A.A.A. 包点",
    "aaaa": "A.A.A. 包点",
    "a a a": "A.A.A. 包点",
    "aaa.": "A.A.A. 包点",
    "a.a.a": "A.A.A. 包点",
    "bb": "B.B. 包点",
    "bbb": "B.B.B. 包点",
    "bbbb": "B.B.B. 包点",
    "b b b": "B.B.B. 包点",
    "bbb.": "B.B.B. 包点",
    "b.b.b": "B.B.B. 包点",
    "cc": "C.C. 包点",
    "ccc": "C.C.C. 包点",
    "cccc": "C.C.C. 包点",
    "c c c": "C.C.C. 包点",
    "ccc.": "C.C.C. 包点",
    "c.c.c": "C.C.C. 包点",
    # v0.2.11：lets go / let's go 的真译（见 translate_local 里 0) 的说明）
    "lets go": "走", "let's go": "走",

    # 战术
    # ── 地图点位/战术口令 v0.2.11（缺口扫描补充，A short=A小 同源）──
    "pop flash": "瞬闪", "pop flash b main": "瞬闪B主",
    "one way smoke": "单向烟", "one way smoke a short": "A小单向烟",
    "wide swing": "大拉", "jiggle peek": "小拉", "dry peek": "干拉",
    "re peek": "补拉", "re-peek": "补拉", "wall bang": "穿墙",
    "clear corners": "清角落", "trade me": "补我",
    "entry fragger": "突破手", "mid diff": "中路碾压", "full save": "全保",
    "b short": "B小", "c main": "C大",     # ── 社区口令第二批（用户提供的教程语料，含视频实战句）──
    "crossfire": "交叉火力", "drop me": "发我一把", "drop me a gun": "发我一把",
    "lurk": "走单", "nice one": "好样的", "nice shot": "好枪",     "nice try": "尽力了", "nt": "尽力了", "bait him": "引诱",
    "camp": "蹲点", "camp them": "架住他们", "camper": "老六",    "clutch": "残局", "one way smoke a short": "A小单向烟",
    "behind": "后面", "vest": "护甲", "cool down": "冷却中",
    "feeding": "白给", "split up": "分开", "gamble a": "赌A",
    "gamble b": "赌B", "he is low": "他大残了", "trade kill": "换人补枪",    "push": "推进",     "a clear": "A点没人", "b clear": "B点没人",
    "i lit him": "点了他一枪", "bottom frag": "杀最少", "top frag": "杀最多",
    "flank": "绕后",
    "fullbuy": "全枪全弹", "full buy": "全枪全弹", "forcebuy": "强起",
    "i am so lagging": "我太卡了", "anti eco": "反经济局", "half buy": "半起",
    "one shot": "打残了能上", "glass cannon": "脆皮大狙",
    "play the bomb": "围着包打", "safe plant": "安全下包",
    "fake plant": "假下包", "play for time": "拖时间",
    "play for picks": "慢慢打抓失误", "igl": "队伍指挥",
    "care heaven": "小心二楼", "care flank": "小心绕后",
    "yeah im gonna care flank": "我去看绕后",
    "i got money": "我有钱，可以发",
    # v0.2.11 修正残缺译文：原来是「我有大」「大好了」——
    # 玩家看到「我有大」根本不知道是什么（大概率读成「我有个大…」）。
    # 直译偏差顶多是词不对，**残句是看不懂**，危害更大。
    # 口径与已正确的 "i have ult": "我有大招" / "ult": "大招" 统一。
    "i got my ult": "我有大招", "ult ready": "大招好了",
    "ult first and then we go": "先开大再进",
    "care they push": "小心他们前压", "one b": "B点一个",
    # v0.2.11：这条整句里硬编码着「跟我换血」。改 _ACT['trade'] 时漏了它，
    # 结果同一条报点两种译法 —— 「同一个判断只能有一份实现」的老问题。
    "trade me im entry": "补我，我是突破手", "im entry": "我是突破手",
    "wide swing him": "大拉他", "wide swing it": "大拉", "wide swing": "大拉",
    "jiggle peek first": "先小拉", "jiggle peek": "小拉",
    "wall bang him": "穿墙打他", "wall bang": "穿墙",
    "lets go push": "进点", "let's go push": "进点",
    "im so low im in 1hp": "我剩一滴血", "im so low": "我大残",
    "lobby": "大厅", "ladder": "梯子", "cubby": "凹槽",     "market": "市场", "bathroom": "浴室", "sewer": "下水道",
    "connector": "连接道", "underpass": "地道", "stairs": "楼梯",
    "ramp": "斜坡", "pillar": "柱子", "spawn": "出生点",
    "heaven": "二楼", "hell": "下层", "tower": "二楼",     "upper": "高处", "under": "低处",
    "glhf": "祝好运", "g2g": "我先走了", "ty": "谢谢",    "np": "没关系", "gh": "上半场打得不错",
    # v0.2.11：wp = well played = 玩得好（不是 GG）。
    # _REPLY 里已是「玩得好」，这里也要一样 —— 同一键两个译文，
    # 谁先被查到谁生效，玩家看到两个不同的中文会以为看错了。
    "wp": "玩得好", "ggez": "GG EZ",
    "sus": "像开挂", "noob": "菜", "afk": "挂机",
    "ninja defuse": "偷包",
    "ninja defusing": "偷包中",
    "fake defuse": "假拆包",
    "retake": "反清",
    "post plant": "下包后",     # v0.2.11：去掉「慢打」。默认购买（full buy）不叫慢打，
    # 「慢打」是另一个打法，玩家看到会误解战术意图。
    "default": "默认",
    "eco": "存钱局",
    "force buy": "强起",
    "full buy": "全枪全弹",
    "force": "强起",
    "igl": "指挥",
    "tap": "点射",
    "prefire": "预瞄",
    # v0.2.11 第11批：#55 one way smoke=单向烟。
    # 原值「单项烟」是错字（单**向**，不是单**项**）。
    "one way": "单向烟",
    "fake": "假打",
    "contact": "遇敌",     "slow": "打慢点",
    "recon": "侦查",
    "recon arrow": "侦查箭",
    "swing": "大拉",
    "cross": "交叉",
    "shoot": "打",
    "shoot him": "打他",
    "jiggle peek": "反复试探",
    "wide peek": "大拉身位",
    "shoulder peek": "假拉",
    "wall bang": "穿墙打",
    "wallbang": "穿点",
    "wall down": "墙要掉了",
    "one hp": "一滴血",
    "two more": "两个以上",
    "no info": "没信息",
    "last seen": "最后出现",
    "care": "小心",
    "clear": "包点清了",
    "winnable": "能赢",
    "yolo": "拼一把",
    "tilted": "心态崩了",
    "hax": "开挂",
    "noob": "菜鸟",
    "stfu": "闭嘴",
    "boost": "拉枪线",
    "smurf": "炸鱼",
    "acc": "买号",
    "ff": "投降",
    "throw": "开摆",
    "fill": "补位",
    # v0.2.11：社区就说 GG/GGWP，展开成「打得不错」是词典释义不是报点。
    # STRICT_RULES_ZH 第 7 条本来就要求「ggwp 直接输出 GGWP」，
    # 实现与自家规则不一致，这里对齐。
    "gg": "GG",
    "ggwp": "GGWP",
    "hf": "玩得开心",
    "mb": "我的锅",
    "ty": "谢了",     "thx": "多谢",     "afk": "挂机",
    "nice": "漂亮",
    "nt": "尽力了",
    "nc": "漂亮",
    "n1": "好样的",
    "ns": "好枪",     "top frag": "杀得最多",
    "bottom frag": "杀得最少",
    "spray": "扫射",
    "spam": "穿射",
    "jett diff": "捷特差距",
}


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())


# ---------------------------------------------------------------------------
# 多从句组合（v0.2.5）
# ---------------------------------------------------------------------------
# 「get the orb and stack A」这类整句表永远追不上：
# 30 个短句能组合出天文数量的句子。与其继续加词条，不如拆开逐段翻译再重组。
# ---------------------------------------------------------------------------
# 纯语气前缀（v0.2.5）
# ---------------------------------------------------------------------------
# 只收「剥掉不丢信息」的前缀。第三人称主语（they/he/she）不在此列——
# "他们下包了" 里的「他们」是有效信息，剥了反而更差。
_MOOD_PREFIX = re.compile(
    r"^(?:"
    r"please|pls|ok|okay|hey|yo|wait|"
    r"i'?m\b|i\s?am\b|am\b|"          # 纯主语，剥了不丢信息
    r"let'?s\b|lets\b|"
    r")\s+",
)


# ---------------------------------------------------------------------------
# 第三人称主语（v0.2.5）
# ---------------------------------------------------------------------------
# 剥主语后要补回译文，否则「他们下包了」会退化成「下包了」。
# 通用血量报点：`<位置> is/are 's low`。v0.2.11 新增，见 translate_local -0.45 处说明。
_LOW_REPORT = re.compile(r"^(?P<subj>[\w\s' ]{1,24}?)\s+(?:is|are|'s|was|were)\s+low$", re.I)

_SUBJ = re.compile(
    r"^(they(?:'re|\s+are|\s+r|\s+will)?|he(?:'s|\s+is|\s+will)?|"
    r"she(?:'s|\s+is|\s+will)?|"
    r"enemy|enemies|the\s+enemy|players?|someone|somebody|guys?)\s+",
    re.I,
)
_SUBJ_ZH = {
    "they": "他们", "they're": "他们", "they are": "他们", "they r": "他们",
    "they will": "他们",
    "he": "他", "he's": "他", "he is": "他", "he will": "他",
    "she": "她", "she's": "她", "she is": "她", "she will": "她",
    "enemy": "敌人", "enemies": "敌人", "the enemy": "敌人",
    "player": "有人", "players": "有人", "someone": "有人", "somebody": "有人",
    "guy": "有人", "guys": "有人",
}

_SPLIT_RE = re.compile(
    r"\s*(?:,|，|;|；|\band\b|\bthen\b|\bplus\b|"
    r"\+|/)\s*",
    re.I,
)


def _join_zh(parts: list) -> str:
    """中文并列连接：2 条用「，」，3 条以上用「，」但末条前用「、」减重。"""
    parts = [p for p in parts if p]
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    if len(parts) == 2:
        return f"{parts[0]}，{parts[1]}"
    return "，".join(parts)


def _compose_multi(raw: str, low: str, guard: int = 0):
    """尝试把多从句拆开逐段翻译。全部命中才返回，否则 (None, "")。

    guard 限制递归深度，防止 "a and b and c and ..." 无限展开。
    """
    if guard > 2:
        return None, ""
    pieces = [p.strip() for p in _SPLIT_RE.split(raw) if p and p.strip()]
    if len(pieces) < 2:
        return None, ""

    outs = []
    for p in pieces:
        pl = p.lower().strip(" .!?,")
        if not pl:
            return None, ""
        # 递归：子句自己可能还是多从句
        hit, _ = translate_local(p)
        if not hit:
            # 子句整句表未命中，尝试「去掉限定词」后重来一次
            # e.g. "I'm rotating long" -> "rotating long"
            stripped = re.sub(
                r"^(?:i'm|im|i am|we're|were|let's|lets|please|ok|okay|hey)\s+",
                "", pl, flags=re.I).strip()
            if stripped and stripped != pl:
                hit, _ = translate_local(stripped)
            if not hit:
                return None, ""
        outs.append(hit)

    if len(outs) < 2:
        return None, ""
    # v0.2.11：多从句拼装是英语层**唯一会混排**的出口。
    # 逐词替换只换认得出的词，认不出的原样留着：
    #     'they dropped the smoke on site' -> 'they dropped the 控场 on site'
    # 而本地命中会跳过云端和它后面所有清洗层，所以必须在这里拦。
    #
    # **只接这一个出口**，不接整串查表那些 —— 表里的值是权威数据，
    # 不存在拼接问题。第一版把守卫接到了所有出口，结果把
    # '1 flash' -> '一个闪光' 这类合法输出判死（audit 90/90 -> 87/90）。
    _joined = _join_zh(outs)
    if _mixed_language_output(_joined):
        return None, ""                     # 半匹配 -> 交云端整句翻
    return _joined, "local"


# ---------------------------------------------------------------------------
# v0.2.9：高频战术口令表（提到模块级）
# ---------------------------------------------------------------------------
# 原本定义在 translate_local 内部，导致 accent.py 无法 import ——
# 词表构建静默失败，口音纠错率 0/12。局部字典本就不该承载数据。
_V25 = {
    # ult / 技能球
    "i have ult": "我有大招",
    "i have ult wait for me": "我有大招，等我",
    "i have ult, wait for me": "我有大招，等我",
    "ult ready": "大招好了",
    "ult is up": "大招好了",
    "save ult": "留大招",
    "get the orb": "吸球",
    "get orb": "吸球",
    "take the orb": "吸球",
    "i need the orb": "我要吸球",
    # flash / smoke 的口语（Qwen 会把 flash 误当 smoke）
    "flash me": "给我闪个",
    "can you flash me": "给我闪个",
    "throw me a flash": "给我丢个闪",
    "smoke me": "给我丢个烟",
    "throw me a smoke": "给我丢个烟",
    "one way smoke": "单向烟",
    "drop a smoke": "丢个烟",
    "drop a flash": "丢个闪",
    # 血量 / 状态
    "i'm low": "我大残",
    "im low don't peek": "我大残别拉",     "im low dont peek": "我大残别拉",     "don't peek": "别拉",
    "don't push": "别前压",
    "dont push": "别前压",
    "he's one hp": "他一滴血",
    "hes one hp": "他一滴血",
    "he's low": "他大残了",
    "hes low": "他大残了",
    # v0.2.11：补「单说 low」并统一口径为「大残」。
    #
    # 实测（tests/diag_low.py）：
    #     low     -> '大残。' 649ms  [云端]   ← 游戏里最高频报点之一，
    #                                          却要打一次云端往返
    #     he is low -> '他大残' 1.0ms [本地]
    # 也就是说「带主语的能秒出、不带主语的反而慢几百毫秒」——
    # 而队友在语音里恰恰经常只喊一个 low。
    #
    # 口径统一：im low / low hp / low 全部出「大残」，
    # 原来 im low->'我残血'、low hp->'残血'，同一个意思三个说法。
    "low": "大残",
    "low hp": "大残",
    "im low": "我大残",
    # 转点 / 走位
    "rotate long": "转大",
    # v0.2.11：实测 going a short -> 云端「去A大道。」
    # **A短（a short）和A大（a long）是相反的位置**，翻反了玩家会往
    # 反方向跑，这是本轮危害最大的错译（不是用词不准，是方向错）。
    # 需求背景：「a short，你就要立马知道是『A小』而不是秀特」
    # v0.2.11 通顺度补强：以下几句实测落云端且译文是书面语
    #   they are setting up -> 「他们正在设立。」   ← 设立 是胡话
    #   clutch 1v3          -> 「1v3 残局。」      ← 英文残留
    #   throw nade          -> 「丢个投掷物。」      ← 不如「丢雷」直接
    #   rotating long       -> 「我转长道」        ← 已改为「转大」（社区说法）
    #   dont peek           -> 「别拉」            ← 拉 是歧义词
    "they are setting up": "他们在架枪",
    "they set up": "他们架枪了",
    "clutch 1v3": "1打3残局", "clutch 1v2": "1打2残局",
    "clutch 1v4": "1打4残局", "clutch 1v5": "1打5残局",
    "throw nade": "丢雷", "throw grenade": "丢雷",
    "nade": "雷", "grenade": "雷",
    "rotating long": "转大", "rotate long": "转大",
    "rotating short": "转小", "rotate short": "转小",
    "dont peek": "别探头", "do not peek": "别探头",
    # v0.2.11 补：以下实测落云端 400~630ms，而本地 0ms 就能答对。
    # 玩家报点最常说的就是这些，每多一句云端就多一次等待。
    "going b main": "去B大", "im going b main": "我去B大",
    "go back spawn": "回出生点", "im going back spawn": "我回出生点",
    "rotate now": "转点", "rotating now": "转点", "rotate": "转点",
    "watch the flank": "小心绕后", "watch flank": "小心绕后",
    "watch the back": "小心后面", "watch back": "小心后面",
    "kill him": "打掉他", "kill her": "打掉她", "kill it": "打掉",
    "get him": "打掉他", "finish him": "补掉他",
    "i'll flash": "我闪", "im flashing": "我闪",
    "one is low": "他大残", "one low": "他大残",
    "a short or long": "A小还是A大",
    "going a short": "去A小", "im going a short": "我去A小",
    "going a long": "去A大", "im going a long": "我去A大",
    "going b short": "去B小", "im going b short": "我去B小",
    "going b long": "去B大", "im going b long": "我去B大",
    "im going mid": "我去中路",
    "im going heaven": "我去天台",
    "i'm going a": "我去A",
    "im going a": "我去A",
    "i'm going b": "我去B",
    "im going b": "我去B",
    "going a": "去A",
    "going b": "去B",
    "going mid": "去中路",
    "going heaven": "去二楼",
    "cover me": "掩护我",
    "trade me": "补我",
    "follow me": "跟我",
    "regroup": "集合",
    "fall back": "后撤",     "push site": "压包点",
    "take site": "打包点",
    "hit the site": "打点",
    # boost / 站位
    # 「拉枪线天堂」不通顺：硬翻 + 中文语序错。改「二楼拉枪线」。
    "boosting heaven": "二楼拉枪线",
    "boosting": "拉枪线",
    "boost heaven": "二楼拉枪线",
    "boost a": "拉枪线A",
    "boost b": "拉枪线B",
    "double up": "双架",
    "on top": "在高处",
    "on heaven": "在二楼",
    "on hell": "在下层",
    "in heaven": "在二楼",
    "in hell": "在下层",
    # 包
    "spike dropped": "包掉了",
    "spike is down": "包掉了",
    "spike down": "包掉了",
    "they dropped": "他们掉包了",
    "planted": "已下包",     "they planted": "他们下包了",
    "defusing": "在拆包",    "defuse": "拆包",
    "get the defuse": "去拆包",
    # 击杀 / 交流
    "i got him": "我打到了",
    "got him": "打到了",
    "one shot": "一枪",
    "headshot": "爆头",
    "nice shot": "好枪",
    "nice try": "尽力了",
    "trade": "补枪",
    "save": "保枪",
    "save the gun": "保枪",
    "bait": "卖",
    "let's go": "走",
    "lets go": "走",
    "go go go": "走走走",
    "wait wait": "等等",
    "stop stop": "停",
    "on my way": "我来了",
    "help": "帮忙",     "help me": "救我",
    "im low hp": "我大残",

# ---- v0.2.5 补漏（AST 校验后补齐的漏键）----
    "i'm low don't peek": "我大残别拉",
    "don't peek": '别拉',
    "don't push": '别前压',
    'he is low': '他大残了',
    'he is one hp': '他一滴血',
    'he is dead': '他死了',
    'she is low': '她大残了',
    "i am low": "我大残",     'i am dead': '我死了',
    'spike dropped mid': '中路包掉了',
    'spike dropped long': '长道包掉了',
    'spike dropped a': 'A点包掉了',
    'spike dropped b': 'B点包掉了',
    'spike dropped heaven': '二楼包掉了',
    'spike dropped a main': 'A大包掉了',
    'spike dropped b main': 'B大包掉了',
    'a no sound': 'A点没动静',
    'b no sound': 'B点没动静',
    'a quiet': 'A点安静',
    'b quiet': 'B点安静',
    'care a': '小心A',
    'care b': '小心B',
    'care mid': '小心中路',
    'care heaven': '小心二楼',
    'care flank': '小心绕后',
    'care a main': '小心A大',
    'two more': '两个以上',
    'three more': '三个以上',
    'one more': '还有一个',
    'no info': '没信息',
    'no vision': '没视野',
    'last seen mid': '最后出现在中路',
    'last seen a': '最后出现在A',
    'last seen heaven': '最后出现在二楼',
    'i have ult ready': '我大招好了',
    'ult charging': '大招充能中',
    'need the orb': '要吸球',
    'take orb': '吸球',
    'rotating a': '转A',
    'rotating b': '转B',
    'rotating mid': '转中路',
    'im rotating long': '我转大',
    'im rotating a': '我转A',
    'im rotating b': '我转B',
    'im going mid': '我去中路',
    'im going heaven': '我去二楼',
    'im going a main': '我去A大',
    'im pushing a': '我压A',
    'im pushing b': '我压B',
    'we should rotate': '我们该转点',
    'lets rotate': '转点',
    'fall back a': '回防A',
    'fall back b': '回防B',
    'boosting a': '拉枪线A',
    'boosting b': '拉枪线B',
    'boosting mid': '拉枪线中路',
    'boosting site': '拉枪线包点',
    'im on heaven': '我在二楼',
    'im on hell': '我在下层',
    'im in heaven': '我在二楼',
    'enemy on heaven': '敌人在二楼',
    'enemy in heaven': '敌人在二楼',
    'enemy on hell': '敌人在下层',
    'they planted a': '他们下包了',
    'they planted b': '他们下包了',
    'spike is planted': '包下了',
    'they are defusing': '他们在拆包',
    'im defusing': '我在拆包',
    'defuse the spike': '拆包',
    'ninja defuse now': '现在偷包',
    'i killed him': '我杀了他',
    'one shot him': '我一枪秒了他',
    'he is one shot': '他一枪就死',
    'he is one twenty': '他一百二血',
    'he is eighty': '他八十血',
    'he is low hp': '他大残',
    'they are pushing': '他们压上来了',
    'they pushed': '他们压上来了',
    'they are here': '他们过来了',
    'recon arrow': '侦查箭',
    'shoot the drone': '打无人机',
    'shoot the dog': '打狗',
    'shoot the ult': '打技能',
    'break the trap': '拆陷阱',
    'heal me': '给我奶',
    'need heal': '要奶',
    'lets go a': '走A',
    'lets go b': '走B',
    'push now': '现在压',
    'fall back now': '现在回防',
    'hold the site': '守住包点',
    'play slow': '打慢点',
    'play fast': '快打',
    'i have info': '我有信息',
    'no enemies': '没人',
    'site clear': '包点清了',
    "a clear": "A点没人",     "b clear": "B点没人",     'mid clear': '中路清了',
    'heaven clear': '二楼清了',


# ---- v0.2.5 补漏 2：主语剥离后暴露的缺口 ----
    'planted spike on a': '下包了',
    'planted spike on b': '下包了',
    'planted spike': '下包了',
    'planted on a': '下包了',
    'planted on b': '下包了',
    'pushed a': '压A点',
    'pushed b': '压B点',
    'pushed mid': '压中路',
    'pushing a': '压A点',
    'pushing b': '压B点',
    'pushing mid': '压中路',
    'boosting heaven': '二楼拉枪线',
    'boosting': '拉枪线',
    "they're here": '他们过来了',
    'they are here': '他们过来了',
    'they are coming': '他们过来了',
    "i'm low": "我大残",
    "i'm dead": '我死了',
    "i'm one hp": '我一滴血',
    "i'm hit": '我被打中了',
    "i'm reloading": '我换弹',
    "i'm reloading!": '我换弹',
    'reloading': '换弹',
    'reloading!': '换弹',
    "don't have ult": '我没大招',
    "i don't have ult": '我没大招',
    'no ult': '没大招',
    'one shot': '一枪秒',
    'one tap him': '点射他',
    'tapping': '点射',


# ---- v0.2.5 补漏 3：going/rotating 带主语，避免丢信息 ----
    'going a': '我去A',
    'going b': '我去B',
    'going mid': '我去中路',
    'going heaven': '我去二楼',
    'going long': '我去长道',
    'rotating long': '转大',
    'rotating mid': '我转中路',
    'rotating a': '我转A',
    'rotating b': '我转B',
    # v0.2.11：ASR 常把 ult 听成 "my ult ready" 里的 my 被吞/或整句变形，
    # 原来缺 "my ult ready" 导致走云端出残句「我有大了。」
    'my ult ready': '我大招好了',
    'my ult': '我的大招',
    'giants': '大招',
}

# ---------------------------------------------------------------------------
# v0.2.11：同义归一化（不是复制词条）
# ---------------------------------------------------------------------------
# 社区大量玩家用 **giant** 指 ult（两个词同义，都指终极技能）。
# 实测漏掉时的惨状：
#     i have giant -> 云端翻成「我有巨人大树。」
#     giant ready  -> 云端翻成「巨兽就绪。」
#     no giant     -> 云端翻成「无巨人大军。」
# 三条全不可用。
#
# 为什么归一化而不是把 giant 的词条复制一份
# -----------------------------------------
# ult 一族有 30+ 条词条（ult ready / one ult / no ult / save ult …），
# 复制一份 giant 版就要维护 60 条，且**以后新增 ult 词条时一定会漏掉 giant 版**
# —— 这正是本项目反复踩的「固定名词单一来源」问题。
# 归一化只需一处：把独立的 giant 换成 ult，现有条目自动全部生效。
#
# 边界：`\b` 词边界，不会误伤 "giant" 作为其它含义的用法
# （游戏语音里 giant 就是 ult，没有别的用法）。
_ULT_SYNONYM = re.compile(r"\bgiant(s)?\b", re.I)


# 拼装结果的「源语言残渣」判据（v0.2.11）
# -----------------------------------------------------------------------
# 实测 bug（tests/eval_tm.py）：
#     'they dropped the smoke on site' -> 'they dropped the 控场 on site'
# 逐词累加把认得出的词换掉、认不出的原样留着，拼出中英混排后
# **当成合法本地命中返回**。后果比"翻错"严重：
#   · 本地命中就跳过云端 -> 0ms 输出纯噪声
#   · 云端之后的清洗层（clean_translation / 残留清洗 / 失败兜底）
#     **全都不会执行**，bug 绕过了所有防线
#
# 日韩层早有同源判据（整句覆盖 = 残留源语言 = 部分匹配 = 拒绝），
# 英语层一直没有 —— 同一个病两种待遇，这里补上。
_CJK_CH = re.compile(r"[\u4e00-\u9fff]")
_LATIN_CH = re.compile(r"[A-Za-z]")
# 合法保留的外文：枪名/英雄名/缩写，社区本来就这么说，不该翻
_KEEP_LATIN = re.compile(
    r"^(?:gg+wp|gg|wp|gg ez|ace|nb|oj|ow|nice|try|good|game|"
    r"odin|vandal|phantom|operator|sheriff|guardian|bulldog|"
    r"marshal|outlaw|shorty|classic|ghost|knife|"
    r"viper|reyna|jett|phoenix|raze|breach|sova|cypher|killjoy|"
    r"skye|chamber|neon|astra|harbor|deadlock|vyse|tejo|"
    r"\d+v\d+|[a-z])$", re.I)


def _mixed_language_output(out: str) -> bool:
    """拼出来的译文是否还是「源语言 + 零星汉字」的混排。

    True = 半匹配，不可信，必须落云端整句翻。

    判据是**绝对量 + 比例**双条件，不是纯比例。
    这是 v0.2.11 返工的原因 —— 第一版只写「汉字 < 拉丁字母 × 40%」，
    结果把合法输出判死了（实测 audit_callouts 90/90 -> 87/90）：

        '一个闪光'                      cjk 4 / latin 1   ← 合法（A/1 这类是代号）
        'they dropped the 控场 on site' cjk 2 / latin 20  ← 真混排

    真正的分界是**残留在里的量够不够大**：短输出里一两个字母是正常的
    （A小 / 1打3 / GGWP），长输出里留下 20 个字母才是失败。
    所以先卡绝对门槛（>= 8 个拉丁字母），再比比例。
    """
    s = (out or "").strip()
    if not s:
        return False
    cjk = len(_CJK_CH.findall(s))
    latin = len(_LATIN_CH.findall(s))
    if latin == 0:
        return False                        # 纯中文，正常
    if _KEEP_LATIN.fullmatch(s.replace(" ", "")):
        return False                        # 社区惯用外文，放行
    if latin < 8:
        return False                        # 残留量微不足道，放行
    return cjk < latin * 0.4


def _gv(tbl: str, d: dict, key, default=None):
    """读词表并**过担保闸门**：没担保的值一律当不存在。

    v0.2.11 第8批。`translate_local()` 里有 24 处读表，
    原来只有 6 处查了 `is_verified`，而且全在「整串查表」那几条主干上，
    后面的逐词/启发式分支一处都没查 —— 于是 151 条未担保词条照样出结果，
    闸门在英语侧形同虚设。

    收成一个口而不是逐处加 `if not is_verified(...)`：
    24 处逐个写 = 24 个能写漏的机会，以后新增分支还会再漏。
    """
    if not key:
        return default
    v = d.get(key)
    if v is None or not str(v).strip():
        return default
    if not provenance.is_verified(tbl, key):
        return default
    return v


_ALL_TABLES = None


def _routed_around(low: str) -> bool:
    """这个键在表里**有值但没担保** -> 禁止拼装路径绕过去。

    v0.2.11 第9批。实测 25 条「绕路」泄漏：

        rotating a      表里='我转A'        实际吐出='在转点A点'   ← 更差
        they planted a  表里='他们下包了'     实际吐出='他们已下包A点'
        he is one shot  表里='他一枪就死'     实际吐出='他打残了能上'

    成因：整串查表要求 `is_verified`，这条没担保 -> **跳过**；
    然后拼装路径拿**已担保的单词**（rotate / a / planted）重新拼一句，
    拼出来的话**比表里那个更不通顺**。

    关键判断：拼装的每个词都有出处，不代表**拼出来的那句**有出处。
    词有据 ≠ 句有据。所以只要表里明明有这个词条（不管有没有担保），
    就不许拿启发式绕过去 —— 要么用表里的值，要么落云端。
    """
    global _ALL_TABLES
    if _ALL_TABLES is None:
        _ALL_TABLES = {}
        for _t in ("_PLACE", "_ACT", "_GEAR", "_REPLY",
                   "_TRANSLATE_FIRST", "_V25"):
            _d = globals().get(_t)
            if isinstance(_d, dict):
                for _k, _v in _d.items():
                    if isinstance(_k, str) and isinstance(_v, str) \
                            and _v.strip():
                        _ALL_TABLES.setdefault(_k.strip().lower(), _t)
    _t = _ALL_TABLES.get(low)
    return bool(_t) and not provenance.is_verified(_t, low)


def translate_local(text: str) -> tuple:
    """本地直译。命中返回 (译文, 'local')；未命中返回 (None, '')。"""
    raw = _clean(text)
    if not raw:
        return None, ""
    low = raw.lower().strip(" .!?,")

    # v0.2.11：giant -> ult 同义归一（放在所有查表之前）。
    # 见 _ULT_SYNONYM 处的说明：复制词条会漏维护，归一化只需这一处。
    low = _ULT_SYNONYM.sub("ult", low)

    # -2) 【最高优先级·必须在所有剥前缀分支之前】整串精确查表
    #
    # v0.2.10 修过一次同类 bug（'a short' 被逐词累加成 'A点小道'），
    # 但当时只把查表挪到「三条主干分支」之前，**漏了更靠前的两个
    # 剥前缀分支**（_SUBJ / _MOOD_PREFIX）。实测 tests/diag_trace.py：
    #
    #     'lets go'   表里明明有 _V25['lets go'] = '走'
    #                 却返回 'go'  —— _MOOD_PREFIX 先剥掉 "lets "，
    #                 剩下的 "go" 落在 _PASSTHROUGH 里被原样透传
    #     'im low'    表里明明有 _V25['im low'] = '我大残'
    #                 却返回 '大残' —— "im " 被剥掉，主语丢了
    #                 （玩家会误读成敌方大残，方向都反了）
    #
    # 通则：**表里定义的键形 > 任何启发式拆解**。
    # 整串是键 = 写表的人认为它该整体译；剥前缀只是兜底启发式。
    # 两者冲突时永远以数据为准。
    # 注意守卫的例外：_TRANSLATE_FIRST 即使在 _PASSTHROUGH 里也要真译。
    # 它的定义就是「看着像该透传、但必须真译」（见该表上方注释）；
    # 若也套 `low not in _PASSTHROUGH`，这张表就永远命中不了 ——
    # 实测 lets go / let's go 三张表里都写着「走」，却被守卫一起挡掉，
    # 然后 _MOOD_PREFIX 先剥掉 "lets "，剩下的 "go" 单独命中
    # _PASSTHROUGH -> 原样返回裸英文 'go'（一个字都没翻）。
    #
    # 只放开守卫，**不动表的优先级顺序**：
    # 曾经把它挪到最前面，导致 _V25 的 'care heaven'='小心天堂'
    # 反过来压掉 _TRANSLATE_FIRST 的 '小心高台'，audit_comms 报红。
    # 同一个键散在多张表里时，先查哪张会改变输出 —— 这是隐患，
    # 但修它要逐条核实，不能顺手改顺序。
    # v0.2.11：**默认拒绝无担保词条**。
    #
    # 用户质问：「如果你本来就塞进一堆垃圾，但是它语法是正确的，
    # 你也检查不了」——对。本地词表的危害不是难看，是**会主动伤害产品**：
    # 本地层命中就跳过云端，一条错译 = 永远错且更快。
    # 而「重复键/空译文/编译」这类检查全是必要不充分的，
    # 对「语法正确但内容是垃圾」的条目一条都拦不住。
    #
    # 所以判据换成一个语义问题：**这个键有人担保吗？**
    # 担保人只有两个（见 provenance.py）：
    #   1) 在 provenance.VERIFIED 里手写登记，且写明了「凭什么」
    #   2) 被某个 tests/audit_*.py 用期望值钉死过（有测试证明它对）
    # 两者都没有 -> 不参与本地命中，放它去云端整句翻：
    # 慢 400~800ms，但**不会把错误钉成永久快速答案**。
    for _NAME, _EXACT in (("_PLACE", _PLACE), ("_ACT", _ACT),
                          ("_GEAR", _GEAR), ("_REPLY", _REPLY),
                          ("_TRANSLATE_FIRST", _TRANSLATE_FIRST),
                          ("_V25", _V25)):
        _ex = _EXACT.get(low)
        if not _ex:
            continue
        if low in _PASSTHROUGH and _NAME != "_TRANSLATE_FIRST":
            continue
        if not provenance.is_verified(_NAME, low):
            continue
        return _vt(_ex)
    # 多词键的逐级回退："a short!" / "a short?" 去掉尾标点再查一次
    _low_np = low.rstrip("!.?。！？~ ")
    if _low_np and _low_np != low:
        for _NAME, _EXACT in (("_PLACE", _PLACE), ("_ACT", _ACT),
                              ("_GEAR", _GEAR), ("_REPLY", _REPLY),
                              ("_TRANSLATE_FIRST", _TRANSLATE_FIRST),
                              ("_V25", _V25)):
            _ex = _EXACT.get(_low_np)
            if _ex and provenance.is_verified(_NAME, _low_np):
                return _vt(_ex)

    # -1) 多从句组合（v0.2.5）：放在整串查表之后，
    #     因为 "get the orb and stack A" 只有拆开才答得对。
    #     注意：不是所有整句都要拆 —— 下面 1)/2) 的整句表优先，
    #     这里只在「拆开后每段都命中且结果更完整」时才接管。
    if ("," in raw or " and " in low or "，" in raw or " then " in low
            or ";" in raw or "；" in raw):
        _mc = _compose_multi(raw, low)
        if _mc:
            return _mc

    # -0.6) 第三人称主语（v0.2.5）：剥主语 -> 查短句表 -> 把主语补回译文
    #      "they're boosting heaven" -> "boosting heaven" -> "二楼拉枪线" -> "他们二楼拉枪线"
    #      比直接排除 they 正确：既命中短句表，又不丢主语。
    _sub = _SUBJ.match(low)
    if _sub and _sub.end() < len(low):
        _who = _SUBJ_ZH.get(_sub.group(1).lower(), "")
        _rest = low[_sub.end():].strip()
        if _who and _rest:
            _hit, _ = translate_local(_rest)
            if _hit:
                return f"{_who}{_hit}", "local"

    # -0.45) 通用血量报点（v0.2.11）：`<位置> is/are low` -> `<位置>大残`
    #
    # 实测（tests/diag_low.py，补词条之前）：
    #     low        -> '大残。'   649ms [云端]
    #     mid is low -> '中路大残。' 696ms [云端]
    #     low health -> '大残。'   411ms [云端]
    #
    # 为什么用**一条通用规则**而不是逐条补词条：
    #   逐条补是无底洞（今天补 mid，明天有人喊 two / a site / heaven），
    #   和 giant->ult 是同一个道理 —— 派生优先于枚举。
    #
    # 主语只认 _PLACE 里的**已知位置**，刻意保守：
    #   "one is low" 里的 one（1号位）含义不唯一，放过让云端翻，
    #   比翻成「一号大残」这种没法验证的强译更安全。
    _m = _LOW_REPORT.match(low)
    if _m:
        _where = _gv("_PLACE", _PLACE, _m.group("subj").strip())
        if _where:
            return f"{_where}大残", "local"

    # -0.5) 纯语气前缀剥离（v0.2.5）
    #      "they're boosting heaven" / "please flash me" / "ok let's go"
    #      中文不需要这些主语与敬语，剥掉后走短句表即可（0ms）。
    #      刻意不剥 they/they're/we're —— "他们" 是有效信息，
    #      剥了会丢语义（"they planted" -> "他们下包了" 必须留着）。
    _pfx = _MOOD_PREFIX.match(low)
    if _pfx and _pfx.end() < len(low):
        _rest = low[_pfx.end():].strip()
        if _rest:
            _hit, _ = translate_local(_rest)
            if _hit:
                return _vt(_hit)

    # v0.2.11：lets go / let's go 必须在这里有真译。
    #
    # 实测 bug：返回裸英文 'go'（一个字都没翻）。
    # 链条是：lets go 同时在 _PASSTHROUGH（要原样弹）
    # 和 _V25['lets go']='走'（要真译）；
    # 精确查表的守卫 `low not in _PASSTHROUGH` 把 _V25 那条挡掉，
    # 之后 _MOOD_PREFIX 剥掉 "lets "，剩下的 "go" 单独命中
    # _PASSTHROUGH -> 原样返回。**表里写对了却走不到**。
    # 修法：给 _TRANSLATE_FIRST 补条目（它的判定在守卫之后，
    # 正是「透传前真译」这张表存在的意义）。
    if low in _TRANSLATE_FIRST and provenance.is_verified(
            "_TRANSLATE_FIRST", low):
        _tf0 = _gv("_TRANSLATE_FIRST", _TRANSLATE_FIRST, low)
        if _tf0:
            return _vt(_tf0)

    # 1) 纯透传黑话
    #
    # v0.2.11：两条硬规则，都是闸门装上后实测逼出来的。
    #
    # 规则 A：**`_TRANSLATE_FIRST` 有条目就绝不回弹原文**。
    #   实测 'ninja defuse' -> 'ninja defuse'、'default' -> 'default'
    #   都是「弹英文」。而 `_TRANSLATE_FIRST` 存在的意义就是
    #   「透传前真译」，有真译还回弹英文是自相矛盾。
    #
    # 规则 B：透传也要过担保闸门。
    #   没有担保的词宁可落云端整句翻，也不回弹原文 ——
    #   回弹等于把「没翻」摆到队友面前，落云端至少给一句能读懂的话。
    if low in _PASSTHROUGH:
        if low in _TRANSLATE_FIRST:
            _tf = _gv("_TRANSLATE_FIRST", _TRANSLATE_FIRST, low)
            if str(_tf).strip() and provenance.is_verified(
                    "_TRANSLATE_FIRST", low):
                return _vt(_tf)
            return None, ""          # 有真译但无担保 -> 交云端
        if provenance.is_verified("_PASSTHROUGH", low):
            return _vt(raw)
        return None, ""

    # 2) 整句是单个回应语
    if low in _REPLY:
        _rp = _gv("_REPLY", _REPLY, low)
        if _rp:
            return _vt(_rp)

    # v0.2.11 第9批：**禁止拿启发式绕开未担保的词条**。
    # 拼装路径的每个词都有出处，不代表拼出来的那**句**有出处。
    # 表里明明有这个词条 -> 要么用表里的值，要么落云端。
    if _routed_around(low):
        return None, ""

    # 2.5) 逗号分隔的多段报点："1 flash, 1 flash" / "two mid, one A"
    #     ★ v0.2.16：**每一段都必须命中**才允许拼句返回——旧实现把没命中的
    #     段原样留着（英文）和命中的段混排成「hello、闪光」当 local 结果，
    #     绕过了云端和全部清洗层（宁缺毋滥：混排不如落云端）。
    #     顺手修掉同条件写两遍的笔误（第二个本意是全角逗号）。
    if "," in raw or "\uff0c" in raw:
        parts = [p.strip() for p in re.split(r"[,\uff0c]", raw) if p.strip()]
        if len(parts) > 1:
            outs = []
            for pp in parts:
                zh_pp, _ = translate_local(pp)
                if not zh_pp:
                    outs = []
                    break
                outs.append(zh_pp)
            if outs:
                return "、".join(outs), "local"

    # 3) 报点数量 + 装备： "one flash" / "2 smokes" / "two mid"
    m = re.match(r"^(\d+|one|two|three|four|five|won|to|too|tree)\s+(.+)$", low)
    if m:
        n_raw, rest = m.group(1), _clean(m.group(2))
        n = _NUM.get(n_raw)
        if n:
            if rest in _GEAR:
                _g = _gv("_GEAR", _GEAR, rest)
                if not _g:
                    _g = _gv("_PLACE", _PLACE, rest)
                if _g:
                    return f"{_NUM_CN.get(n, n)}个{_g}", "local"
            if rest in _PLACE:
                _p1 = _gv("_PLACE", _PLACE, rest)
                if _p1:
                    return f"{_NUM_CN.get(n, n)}个在{_p1}", "local"
            # "one on A" / "two mid"
            m2 = re.match(r"^on\s+(.+)$", rest)
            if m2:
                _p2 = _gv("_PLACE", _PLACE, m2.group(1))
                if _p2:
                    return f"{_NUM_CN.get(n, n)}个在{_p2}", "local"

    # 4) "<place> 有 <n> 个" / "n <place>"
    #    ★ v0.2.16：`re.split()` 零参调用 = TypeError，"b 2"/"mid 3" 这类
    #    数字报点整句崩掉；n==0 时 _p3 未绑定还会 UnboundLocalError。
    m = re.match(r"^(.+?)\s+(?:has|have|got)?\s*(?:one|two|three|\d+)$", low)
    if m and m.group(1) in _PLACE:
        n = _NUM.get(low.split()[-1], 0)   # 句尾 token 必是数字/数量词
        _p3 = _gv("_PLACE", _PLACE, m.group(1)) if n else None
        if _p3:
            return f"{_p3}{_NUM_CN.get(n, n)}个", "local"

    # 5) 地点 + 动作： "go b" / "rotate a" / "hold mid"
    m = re.match(r"^(?:lets |let us )?(go|rotate|holding|hold|hit|fall back to|"
                 r"take|push|look|pick|check)(?: to| on| up)?\s+(.+)$", low)
    if m:
        verb, place = m.group(1), _clean(m.group(2))
        zh_place = _gv("_PLACE", _PLACE, place)
        if zh_place:
            verb_zh = {"go": "去", "rotate": "转", "holding": "架",
                       "hold": "架", "hit": "打", "take": "上",
                       "push": "压", "look": "看", "pick": "打",
                       "check": "看", "fall back to": "回防"}
            if verb.startswith("fall back"):
                return f"回防{zh_place}", "local"
            return f"{verb_zh.get(verb, verb)}{zh_place}", "local"

    # 6) 位置 + 状态："b heaven 有人" / "mid clear"
    words = low.split()
    if words:
        zh_parts, hit_place = [], False
        for w in words:
            # 每个分支都要**先过担保闸门再取值**（_gv），
            # 拿不到就整句放弃落云端——半成品比慢更糟（宁缺毋滥这一条）
            _hit = None
            if w in _PLACE:
                _hit = _gv("_PLACE", _PLACE, w)
                if _hit:
                    zh_parts.append(_hit); hit_place = True
            elif w in _ACT:
                _hit = _gv("_ACT", _ACT, w)
                if _hit:
                    zh_parts.append(_hit)
            elif w in _GEAR:
                _hit = _gv("_GEAR", _GEAR, w)
                if _hit:
                    zh_parts.append(_hit)
            elif w in _REPLY:
                _hit = _gv("_REPLY", _REPLY, w)
                if _hit:
                    zh_parts.append(_hit)
            else:
                _hit = None
            if not _hit:
                zh_parts = []
                break
        if hit_place and zh_parts and all(zh_parts):
            return _vt("".join(zh_parts))

    # 7) 单个动作词
    if low in _ACT:
        _a1 = _gv("_ACT", _ACT, low)
        if _a1:
            return _vt(_a1)

    # 8) 单个地点词
    if low in _PLACE:
        _p1b = _gv("_PLACE", _PLACE, low)
        if _p1b:
            return _vt(_p1b)

    # 8.5) 组合：「enemy/they + in/on + 地点」-> 敌人在XX
    m = re.match(r"^(enemy|enemies|they|he|she|someone|someone is)\s+"
                 r"(?:is\s+)?(?:in|on|at)\s+(.+)$", low)
    if m:
        who, place = m.group(1), _clean(m.group(2))
        zh_place = _gv("_PLACE", _PLACE, place)
        if zh_place:
            who_zh = {"enemy": "敌人", "enemies": "敌人", "they": "他们",
                      "he": "他", "she": "她", "someone": "有人"}
            return f"{who_zh.get(who, who)}在{zh_place}", "local"

    # 8.6) 组合：「X has/have N 个 Y」（报装备）
    m = re.match(r"^(.+?)\s+(?:has|have|got)\s+(\d+|one|two|three)\s+(.+)$", low)
    if m:
        who, cnt, gear = m.group(1), m.group(2), _clean(m.group(3))
        n = _NUM.get(cnt)
        zh_gear = _GEAR.get(gear) or _PLACE.get(gear)
        if n and zh_gear:
            who_zh = {"enemy": "敌人", "enemies": "敌人", "they": "他们",
                      "i": "我", "he": "他", "she": "她"}
            return f"{who_zh.get(who, who)}有{_NUM_CN.get(n, n)}个{zh_gear}", "local"

    # 8.8) 高频战术口令补充（ninja defuse / one and done / trade me …）
    _EXTRA2 = {
        "ninja defuse!": "偷包",
        "one and done": "秒一个",
        "lets go": "走",
        "let's go": "走",
        "im dead": "我死了",
        "he's dead": "他死了",
        "hes dead": "他死了",
        "trade me": "补我",
        "trade": "补枪",
        "give me": "给我",
        "rotate": "转点",
        "retake": "反清",
        "default": "默认",
        # v0.2.11 通顺度：逐词替换会拼出「赌点B点」（stack+b 点）。
    }
    for _k2, _v2 in _EXTRA2.items():
        if low != _k2:
            continue
        # v0.2.11：这张表在**函数体内**，以前是直接 return 的，
        # 完全绕过了担保闸门 -> 20 多条**没登记过的**词条能直接进浮窗
        # （实测 'slow'/'give me'/'nice try'/'regroup' 都走到了输出）。
        # 与 v0.2.10 的 `match_phrase` 开后门是同一类，只是藏得更深。
        if not provenance.is_verified("_EXTRA2", _k2):
            continue
        return _vt(_v2)


    # -----------------------------------------------------------------------
    # 10. v0.2.5 实测补漏（来源：云端/Qwen 对拍里仍翻不好的句子）
    #     这些本地 0ms 就能答对，不该浪费云端往返
    # -----------------------------------------------------------------------
    # v0.2.9：_V25 已提到模块级（见文件上方）。
    # 这里必须【完全】不出现 `_V25 = ...` 赋值 —— 一旦有赋值，Python 就会把
    # _V25 当成函数局部变量，读模块级那份就会抛
    # UnboundLocalError: cannot access local variable '_V25'
    # （v0.2.10 实测踩到，本地翻译器在多从句路径直接崩）
    for _k3, _v3 in _V25.items():
        # v0.2.11 第9批：这个循环原来**完全没有闸门**，
        # 是英语侧剩下的漏网主因（95 条）。我上一版脚本在 write() **之后**
        # 才改它，于是那段补丁根本没落盘 —— **脚本打印了「改了 17/18」，
        # 但这一处不在那 17 处里，谁都没发现**。
        if not provenance.is_verified("_V25", _k3):
            continue
        if low == _k3:
            return _vt(_v3)
        # 容忍句尾逗号/句号（ASR 常带）
        _k4 = _k3.replace(",", "")
        if low.replace(",", "").replace(".", "") == _k4:
            return _vt(_v3)

    # 9) 拼写纠错容错：ASR 常见误识别
    fuzzy = {
        "b main": "b main", "bmain": "b main",
        "a main": "a main", "amain": "a main",
        "flash flash": "flash", "flash light": "flash",
    }
    if low in fuzzy:
        _fz = _gv("_PLACE", _PLACE, fuzzy.get(low, ""))
        if _fz:
            return _fz, "local"

    return None, ""


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    cases = [
        "1 flash, 1 flash", "one flash", "two smokes", "2 mid",
        "go b", "go a main", "rotate mid", "hold b",
        "they planted spike on A", "im defusing", "im rotating long",
        "enemy in heaven", "flash me", "nice shot", "gg", "ty",
        "one on A", "two on mid", "mid clear", "heaven",
        "my hair", "f a go b", "enemy rotating to B site",
    ]
    hit = 0
    print("本地直译测试：")
    for c in cases:
        zh, how = translate_local(c)
        mark = "命中" if zh else "未命中"
        if zh:
            hit += 1
        print(f"  {c!r:30} {mark:6} {zh or '(交云端)'}")
    print(f"\n命中率 {hit}/{len(cases)}")


def _vt(out):
    """translate_local 的统一出口：半匹配的中英混排一律拒绝。

    存在的原因：逐词累加/整句拼装分支会产生「源语言 + 零星汉字」的混排，
    而本地命中会**跳过云端和它后面所有清洗层**，所以必须在最外层拦。
    """
    if _mixed_language_output(out):
        return None, ""
    return out, "local"
