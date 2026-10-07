# -*- coding: utf-8 -*-
# 作者: cing  ·  https://github.com/cingzz
# 许可: GPL-3.0 + 商业授权（闭源/商用需向作者申请授权），见 LICENSE 与 LICENSE-COMMERCIAL.md
#
"""译文清洗：强制「只输出译文」。

为什么需要
----------
实测踩过的坑（都是模型**解释**而非翻译）：

    "亮路"           → "照亮前行的道路。"        ← 解释，不是翻译
    "1 flash, 1 flash" → "可以理解为：用一个闪光弹…所以这句话可能表示…"  ← 大段废话
    "f a go b"       → "f a go b。意思是你想快速移动到B点…"      ← 废话 + 漏译

用户的原话：**「翻译就是翻译，不是解释」**。
翻译软件弹出的字幕必须是**队友/队友能直接照着执行的一句话**，
不是词典释义，更不是模型的自言自语。

清洗规则（按顺序执行，任何一步命中即停）
--------------------------------------
1. 剥壳：去掉「译文:」「翻译:」「意思：」「意思是」等标签
2. 砍解释：识别并截断「可以理解为」「也就是说」「即」「例如」「所以这句话」
   「这句话的意思」等解释性从句（保留前半的译文部分）
3. 压行：模型爱把一句话拆成多行说明，只保留第一行有效译文
4. 去客套：剥掉「好的」「没问题」「以下是翻译」这类应答前缀
5. 兜底：清洗后为空则回退到原文，绝不留空
"""
from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# 1) 标签前缀
# ---------------------------------------------------------------------------
_LABEL = re.compile(
    r"^\s*(译文|翻译|中文翻译|英文翻译|译|translation|translated)\s*[:：]\s*",
    re.I,
)

# ---------------------------------------------------------------------------
# 2) 解释性从句的触发词 —— 出现即截断
#    这些词一出现，说明模型开始「讲课」而不是「翻译」了
# ---------------------------------------------------------------------------
_EXPLAIN_MARKERS = [
    "可以理解为", "可以解释为", "也就是说", "也就是说，", "换句话说",
    "意思是", "这句话的意思", "这句话可以", "这句话表示",
    "指的是", "代表的是", "具体来说", "具体是指",
    "（注", "(注", "例如：", "比如：",
    "所以这句话", "因此这句话", "该句",
    "在《无畏契约》", "在游戏中", "在瓦罗兰特", "在VALORANT",
    "通常指的是", "通常称为", "指的是", "玩家常用", "是游戏",
    "这个词", "该词", "在这种游戏", "这个术语",
    "也可能指", "也可以理解为", "可理解为", "可能是指", "或许指",
    "翻译成", "译为", "可译为", "对应的是", "在这里指",
    "在这个游戏", "这个术语",
    "这里是", "这是对", "这是在解释",
    "translated as", "which means", "that means", "this means",
    "in this context", "in valorant", "in the game",
]

# 「说明：」「解释：」这类段落标题
_SECTION = re.compile(r"^\s*(说明|解释|备注|Note|Explanation)\s*[:：]\s*", re.I)

# ---------------------------------------------------------------------------
# 3) 无意义的应答前缀
# ---------------------------------------------------------------------------
_POLITE_PREFIX = re.compile(
    r"^\s*(好的|好|当然|没问题|以下是?\s*(翻译|译文)?|这是\s*(翻译|译文)"
    r"|Here\s+(is|are)\s+the\s+translation\s*[:：]?|"
    r"Sure[,.!]?|Of\s+course[,.!]?|Certainly[,.!]?)\s*[:：,，]?\s*",
    re.I,
)

# ---------------------------------------------------------------------------
# 4) 引用符号（模型爱加书名号/引号包整句）
# ---------------------------------------------------------------------------
_QUOTES = "「」『』\"“”''《》【】"


def clean_translation(raw: str, fallback: str = "") -> str:
    """把模型输出压成一句干净译文。失败时回退 fallback 或原文。

    清洗顺序：剥标签 -> 砍解释 -> 逐句筛有效译文 -> 去客套 -> 去包裹 -> 定标点
    """
    if not raw or not raw.strip():
        return strip_decoration(fallback) if fallback else ""

    # v0.2.11（真机 实测）：
    # 「翻译结果带有表情包，要把表情包全部去掉」
    #
    # **必须放在最入口**，不能只放在 `_finish()` 里 —— 这函数有好几条
    # 提前 return 的路径（剥包装失败、砍解释砍空、筛完没剩内容…），
    # 那些路径根本走不到 `_finish()`，表情包就漏出去了。
    # 教训：**清洗要卡在入口，不卡在出口**
    text = strip_decoration(raw.strip())
    text = re.sub(r"^```.*?```\s*", "", text, flags=re.S)     # 去代码块
    text = re.sub(r"^\s*#{1,6}\s*", "", text)                   # 去 markdown 标题号

    # -- 第 0 步：剥「原词 + 元评论」包装 --
    # 模型有时先复述原词再解释：
    #   '"enemy in heaven"在游戏中通常指的是敌人在天堂位置。'
    # 译文在「指的是/即/是」之后，必须先把它摘出来，
    # 否则后面的"砍解释"会把整行砍空，只能回退原文。
    _tail = re.search(
        r"(?:指的是|指的是|通常指|即为|即|意思是|是说)\s*"
        r"([\u4e00-\u9fff][^。！!？?]{1,28})",
        text)
    if _tail:
        cand = _tail.group(1).strip()
        # 剥掉可能粘上来的助词残留（"的是敌人" -> "敌人"）
        cand = re.sub(r"^(的是|就是|那是|这表示|表示|意思是)\s*", "", cand).strip()
        # 只有当前面确实有元评论残留时才用（避免误伤正常译文）
        head = text[:_tail.start()]
        if any(k in head for k in ("在游戏", "在VALORANT", "在VALORANT", "在无畏契约",
                                   "术语", "这个", "该词", "通常")):
            return _finish(cand, fallback)

    # 逐行处理，保留"至少有一条干净译文"的结果
    kept: list = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        line = _LABEL.sub("", line)                 # 剥标签（允许多层）
        line = _LABEL.sub("", line)
        # 砍解释从句：出现解释触发词就截断之前的内容
        for marker in _EXPLAIN_MARKERS:
            idx = line.find(marker)
            if idx >= 0:
                line = line[:idx]
        # 「说明：」可能出现在句中（如"闪。说明：这是致盲技能"），砍掉其后全部
        line = re.split(r"(?:说明|解释|备注|Note|Explanation)\s*[:：]", line)[0].strip()
        if not line:
            continue
        # 这一整行是不是纯解释？判断：没有译文特征且触发词吃掉了大半
        kept.append(line)
        if len(kept) >= 3:
            break

    if not kept:
        # 全是解释 -> 宁可回退原文，也绝不把解释当译文弹给用户
        return strip_decoration(fallback.strip()) or strip_decoration(raw.strip())

    # -- 剥「原词+元评论」前缀 --
    # 典型：'"enemy in heaven"在游戏中通常指敌人在天堂'
    #      译文其实在最后，取最后一个「在/指/是 + 内容」作为译文。
    if kept:
        joined_all = "".join(kept)
        m2 = re.search(r"(?:指的是|指的是|即|是|指)\s*([\u4e00-\u9fff][^。！!]{0,30})", joined_all)
        if m2 and len(m2.group(1).strip()) >= 2:
            cand = m2.group(1).strip()
            return _finish(cand, fallback)

    # -- 防御：整段其实是「用目标语言解释原文」而非翻译 --
    # 典型：'"GGWP" is a common phrase used in VALORANT to express gratitude'
    # 触发词没命中，但整段明显是在解释而不是在翻译。
    joined = " ".join(kept)
    en_explain = re.compile(
        r"\b(is|was|are|were|means?|refers? to|stands? for|used in|"
        r"common phrase|it is often|this is a|express(es)?)\b")
    if en_explain.search(joined) and len(joined) > 40:
        return strip_decoration(fallback.strip()) or strip_decoration(raw.strip())

    # 取第一行有效译文；多行模型里，第一行通常就是真正的翻译
    s = kept[0]

    # 去客套前缀
    for _ in range(3):
        s2 = _POLITE_PREFIX.sub("", s)
        if s2 == s:
            break
        s = s2
    s = _SECTION.sub("", s).strip()

    # 去包裹引号（成对才处理）
    for q in _QUOTES:
        if len(s) >= 2 and s.count(q) == 2 and s.startswith(q) and s.endswith(q):
            s = s[1:-1].strip()
            break

    # 去尾部括号注释与"等等"
    # 去掉句中的英文/拼音冗余括号："包（spike）安放" -> "包安放"
    s = re.sub(r"\s*[(（]\s*[A-Za-z][A-Za-z0-9 ._/-]{0,24}\s*[)）]", "", s)
    s = re.sub(r"\s*[(（][^)）]{0,40}[)）]\s*$", "", s)
    s = re.sub(r"\s*[,，]?\s*(等等|等)\s*[.。!！]?$", "", s)
    s = s.rstrip()

    if not s:
        return strip_decoration(fallback.strip()) or strip_decoration(raw.strip())

    # 超长 = 大概率在解释，按句号截断
    if len(s) > 60:
        m = re.search(r"[。！？!?]", s)
        if m and m.end() <= 60:
            s = s[:m.end()]

    if s and s[-1] not in "。！？!?.,，、…":
        s += "。"
    s = re.sub(r"。{2,}", "。", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s or fallback.strip()

# ---------------------------------------------------------------------------
# 表情包 / 冗余符号（v0.2.11，真机 实测）
# ---------------------------------------------------------------------------
# 需求背景：
#   「翻译出来的都是错的…冗余符号：翻译结果带有表情包，要把表情包全部去掉」
#   「队友说话识别得不准，而且时常带有句号、括号、表情包等冗余符号」
#
# 浮窗是一闪而过的东西，一个 emoji 就能占掉半行的视觉空间，
# 而它**不携带任何战术信息** —— 打一局的人只要看意思。
# 所以浮窗上出现的一切非战术字符一律清掉。
#
# 剥的范围要**比想象的大**，实测踩到的：
#   · emoji 表情（😄🔥💀）与文字表情（:D / :v / (╯°□°）╯︵ ┻━┻）
#   · **装饰性符号**（★ ☆ ✿ ❤ ✓ ← ↑ → ※ ▶ ♪）—— 不是 emoji 的一部分，
#     但同样占地方、同样没信息
#   · ASR 常带的括号内容：（笑）（英文）（翻译）
#   · 云端偶尔加的方括号补充：【注：…】
#
# **不做的事**：不剥汉字、不动数字（55 血）、不删玩家自己打的空格。
# 只清「不承载战术信息的装饰字符」。

_EMOJI = re.compile(
    "["
    "\U0001F000-\U0001FAFF"      # 彩色 emoji 全段
    "\U00002600-\U000027BF"      # ☀-➿ 杂项符号与箭头
    "\U00002190-\U000021FF"      # ←-⇿ 箭头
    "\U00002B00-\U00002BFF"      # ⭐-⯿
    "\U0000FE00-\U0000FE0F"      # 变体选择符（肤色/ZWJ）
    "\U0001F1E6-\U0001F1FF"      # 国旗
    "\U0000200D"                 # ZWJ
    "\U000024C2"                 # Ⓜ️
    "]"
)
_TEXTT_EMOJI = re.compile(
    r"(?<!\w):[DdPpSsXxVv]\)?[\s~_-]*|(?<!\w):\)?(?=\s|$)"  # :D :) ^^ :v
    r"|;\)|\(:"
    r"|\^_\^"                            # ^_^
    r"|\(╯°□°\)╯︵"                     # (╯°□°)╯︵
    r"|┻━┻"                             # ┻━┻
    r"|[QAQqwq]{2,}"# QAQ qwqq
    r"|orz|OTZ"                          # orz OTZ
    r"|\(°△°rrr\)"                      # (°△°rrr)
)
_DECOR = re.compile(r"[★☆✿❀❤♡♥♪♫※▶◀▲▼]+")


def strip_decoration(s: str) -> str:
    """剥掉表情包与装饰符号（浮窗专用）。

    单独抽出来是因为**ASR 原文也要过一遍**：
    用户说「队友说话识别得不准，而且时常带有表情包」——
    那是云端模型在 ASR 输出里加的，光洗译文不够。
    """
    if not s:
        return s
    s = _TEXTT_EMOJI.sub("", s)
    s = _EMOJI.sub("", s)
    s = _DECOR.sub("", s)
    # ASR 常带：「(笑)」「(英文)」「(翻译)」这类整体括注
    s = re.sub(r"[(（]\s*(笑|英文|中文|翻译|原文|注|备注)\s*[)）]", "", s)
    # **整句被一对括号包住**：「（他们下包了）」-> 「他们下包了」
    # 只剥首尾各一层，中间的不动（避免吃掉「A(点)」这种正常用法）
    s = re.sub(r"^\s*[(（]\s*(.+?)\s*[)）]\s*$", r"\1", s)
    # 剥完残留的空括号/方括号（最多两层，避免吃掉正常的括号用法）
    for _ in range(2):
        s = re.sub(r"[(（]\s*[)）]", "", s)
        s = re.sub(r"【\s*】", "", s)
    # 【…】整块是模型自己加的补充说明，**不是正文** -> 整块去掉，
    # 不做「只去标签留内容」那种半吊子（会留下「已确认】他们下包了」）
    s = re.sub(r"【[^】]{0,60}】", "", s)
    # 连续空白压成一个（剥完常留下空隙）
    s = re.sub(r"[ \t]{2,}", " ", s)
    return s.strip()


def _finish(s: str, fallback: str = "") -> str:
    """收尾：剥表情包 → 压标点 → 去尾部注释 → 超长截断。"""
    s = strip_decoration(s)
    if not s:
        return strip_decoration(fallback) if fallback else ""
    s = re.sub(r"\s*[(（][^)）]{0,40}[)）]\s*$", "", s)
    s = re.sub(r"\s*[,，]?\s*(等等|等)\s*[.。!！]?$", "", s).rstrip()
    if not s:
        return strip_decoration(fallback.strip())
    if len(s) > 60:
        m = re.search(r"[。！？!?]", s)
        if m and m.end() <= 60:
            s = s[:m.end()]
    if s and s[-1] not in "。！？!?.,，、…":
        s += "。"
    s = re.sub(r"。{2,}", "。", s)
    return re.sub(r"\s+", " ", s).strip()


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# 社区语言对照（v0.2.5）
# ---------------------------------------------------------------------------
# 注入 prompt 用的「英文游戏口语 -> 中文玩家真实说法」。
# 每一对都是实测踩出来的：左边是云端会译错的样子，右边是社区实际在说的。
#
# 不做硬替换，只进 prompt。硬替换会误伤：
#   "执行" -> "打"  会把「执行任务」也改掉，且违背「翻译不是解释」的原意。
COMMUNITY_GLOSS = """
社区对照（务必采用右列说法，不要用左列的书面译法）：
spike/包体 -> 包（不是「尖刺装置」「爆能器」）
plant -> 下包（不是「安放」「放置」）
defuse -> 拆包（不是「解除」「拆除装置」）
ninja defuse -> 偷包（不是「忍者式解包」）
he is low -> 大残（不是「血量很低」）one hp -> 一滴血
flash -> 闪（不是「闪光弹照明」）；flash me -> 给我闪个
smoke -> 烟（不是「烟雾弹」）；smoke me -> 给我丢个烟
rotate -> 转点（不是「轮换」「交替」）
heaven -> 二楼；hell -> 下层
orb -> 球（不是「技能球道具」）ult -> 大招
peek -> 拉枪线（不是「窥视」）dry peek -> 干拉
hold -> 架住；camp -> 架人；boost -> 拉枪线
flank -> 绕后（不是「侧翼包抄」）
trade -> 补枪（不是「交换」）；bait -> 卖他
clutch -> 残局；eco -> 存钱局；force buy -> 强起；full buy -> 起全
boosting heaven -> 二楼拉枪线（中文语序：地点在前）（不是「在天上获得优势」）
spike dropped -> 包掉了（不是「尖刺装置掉落」）
they planted -> 他们下包了
going A / going B -> 去A / 去B（不要写成「前往A点」）
""".strip()

# 负面清单：模型最容易掉进去的书面语/解释腔
FORBIDDEN_ZH = """
禁用词（出现即视为译错，改用社区口语）：
尖刺装置、爆能器、安放、放置装置、植入、携带者、
窥视、侧翼包抄、战术性、执行行动、策略性地、
通常、意思是、指的是、也就是说、该术语、这个术语
""".strip()

STRICT_RULES_ZH = (
    "输出要求（必须严格遵守）：\n"
    "1. 只输出译文本身，一句话，不超过 30 字。\n"
    "2. 禁止任何解释、说明、注释、括号补充、语气词。\n"
    "3. 禁止出现「译文：」「意思是」「可以理解为」「在游戏中」等标记。\n"
    "4. 禁止把原文复述一遍当成译文。\n"
    "5. 译文要让队友听完能立刻照着做，不是词典释义。\n"
    "6. 保留原句的语气与粗口：中文脏话要译成对应的英文脏话(fuck/shit/damn/bastard)，"
    "不要美化成书面语；反之英文脏话也要译出中文的粗话感。"
    "7. 游戏黑话按社区习惯翻译（如 ggwp 直接输出 GGWP，不要展开解释）。"
)

# v0.2.5：把社区对照与禁用词并入 STRICT_RULES_ZH，否则它们只是定义了没人用
STRICT_RULES_ZH = (STRICT_RULES_ZH + "\n"
                   + "8. 你的任务是翻译，不是解释。不回答对方的问题、不反问、不复述原文、不补充说明。\n"
                   + "\n"
                   + COMMUNITY_GLOSS + "\n"
                   + FORBIDDEN_ZH + "\n")


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    bad_cases = [
        ("照亮前行的道路。", "照亮前行的道路。", "干净译文，原样保留"),
        ("可以理解为：用一个闪光弹。", "", "剥掉解释前缀"),
        ("1 flash, 1 flash。可以理解为：用闪光弹，再用一个闪光弹。"
         "所以这句话可能表示玩家打算连续使用两次闪光弹。", "", "砍掉解释从句"),
        ("译文：他们下包了", "", "剥标签"),
        ("好的，以下是翻译：他们在A点下包了", "", "去客套前缀"),
        ("闪。说明：这是致盲技能", "", "去说明段"),
        ("他们下包了（这是游戏术语）", "", "去尾部括号"),
        ("\", \"他们下包了。\"", "", "去包裹引号"),
        ("a very long explanation that keeps going on and on without any"
         " actual translation content here", "", "超长截断"),
    ]
    print("译文清洗测试：")
    ok = 0
    for raw, _exp, desc in bad_cases:
        out = clean_translation(raw, fallback="原文")
        print(f"  {desc:16} -> {out!r}")
        ok += 1
    print(f"\n{ok}/{len(bad_cases)} 条已处理")
    print("\n空输入回退：", repr(clean_translation("", fallback="原文X")))
