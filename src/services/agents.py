# -*- coding: utf-8 -*-
# 作者: cing  ·  https://github.com/cingzz
# 许可: GPL-3.0 + 商业授权（闭源/商用需向作者申请授权），见 LICENSE 与 LICENSE-COMMERCIAL.md
#
"""《无畏契约》固定名词精确表：英雄 + 武器 + 定位 + 地图。

为什么单独建表
--------------
英雄名/武器名是**固定内容**，不是黑话，不能靠云端模型猜。
一旦翻错，玩家看到「零残局」根本不知道说的是谁。

实测已犯过的错（v0.2.5 修正）：
    Gekko   曾被映射成「奇乐」  ❌  奇乐 = Killjoy
    Gekko   正确译名            盖可
所以这里所有条目都对照官方国服译名逐条核过，并写进 verify_src 守护。

数据来源
--------
官方国服译名（29 位英雄，与官方「共有 29 位英雄登场」一致），
另收录社区常用昵称/音译，因为实际语音里喊的往往不是官方名。
"""

from __future__ import annotations

# v0.2.10：本文件原本只在函数内部 import re，但新增的 _SHOUT_FILLER
# 是模块级正则，必须提前导入（否则 NameError 直接让整个模块加载失败）。
import re

# ---------------------------------------------------------------------------
# 英雄：key=英文名, cn=官方国服译名, role=定位, nick=社区/音译别称
# ---------------------------------------------------------------------------
# 定位用官方四分类：决斗/先锋/控场/哨卫
# 社区口语里也常说 duelist/ini/smoke/sen（见 local_rules._ACT）
AGENTS: dict = {
    # ---- 决斗 Duelist ----
    "jett":       {"cn": "捷风",   "role": "决斗", "nick": ["jet", "捷风", "婕提"]},
    "raze":       {"cn": "雷兹",   "role": "决斗", "nick": ["raze", "雷兹", "芮茲", "炸弹"]},
    "phoenix":    {"cn": "不死鸟", "role": "决斗", "nick": ["phoenix", "不死鸟", "菲尼克斯", "火鸟", "凤凰", "火男"]},
    "reyna":      {"cn": "芮娜",   "role": "决斗", "nick": ["reyna", "芮娜", "蕾娜"]},
    "yoru":       {"cn": "夜露",   "role": "决斗", "nick": ["yoru", "夜露", "夜戮"]},
    "neon":       {"cn": "霓虹",   "role": "决斗", "nick": ["neon", "霓虹", "妮虹", "nn"]},
    "iso":        {"cn": "壹决",   "role": "决斗", "nick": ["iso", "壹决"]},
    "waylay":     {"cn": "幻棱",   "role": "决斗", "nick": ["waylay", "幻棱"]},

    # ---- 先锋 Initiator ----
    "sova":       {"cn": "猎枭",   "role": "先锋", "nick": ["sova", "猎枭", "苏法"]},
    "breach":     {"cn": "铁臂",   "role": "先锋", "nick": ["breach", "铁臂", "叛奇"]},
    "skye":       {"cn": "斯凯",   "role": "先锋", "nick": ["skye", "斯凯", "丝凯"]},
    "kayo":       {"cn": "K/O",    "role": "先锋", "nick": ["kayo", "k/o", "凯隐", "开yo"]},
    "fade":       {"cn": "黑梦",   "role": "先锋", "nick": ["fade", "黑梦", "菲德", "盲侠"]},
    "gekko":      {"cn": "盖可",   "role": "先锋", "nick": ["gekko", "盖可", "壁虎", "狗"]},
    "tejo":       {"cn": "钛狐",   "role": "先锋", "nick": ["tejo", "钛狐"]},

    # ---- 控场 Controller ----
    "brimstone":  {"cn": "炼狱",   "role": "控场", "nick": ["brim", "brimstone", "炼狱", "布史东", "烟叔"]},
    "omen":       {"cn": "幽影",   "role": "控场", "nick": ["omen", "幽影", "欧门", "暗影"]},
    "viper":      {"cn": "蝰蛇",   "role": "控场", "nick": ["viper", "蝰蛇", "薇腹", "毒蛇", "毒女"]},
    "astra":      {"cn": "星礈",   "role": "控场", "nick": ["astra", "星礈", "星坠", "亚星卓", "星星"]},
    "harbor":     {"cn": "海神",   "role": "控场", "nick": ["harbor", "海神", " Harbor", "水鬼"]},
    "clove":      {"cn": "暮蝶",   "role": "控场", "nick": ["clove", "暮蝶"]},
    "miks":       {"cn": "迷核",   "role": "控场", "nick": ["miks", "迷核", "miksgp"]},

    # ---- 哨卫 Sentinel ----
    "cypher":     {"cn": "零",     "role": "哨卫", "nick": ["cypher", "零", "瑟符", "赛芸", "情报局"]},
    "sage":       {"cn": "贤者",   "role": "哨卫", "nick": ["sage", "贤者", "圣祈", "奶妈", "圣母"]},
    "killjoy":    {"cn": "奇乐",   "role": "哨卫", "nick": ["killjoy", "奇乐", "恺宙", "凯尔乔", "圈圈"]},
    "chamber":    {"cn": "尚勃勒", "role": "哨卫", "nick": ["chamber", "尚勃勒", "沙朗"]},
    "deadlock":   {"cn": "钢锁",   "role": "哨卫", "nick": ["deadlock", "钢锁", "死锁"]},
    "vyse":       {"cn": "维斯",   "role": "哨卫", "nick": ["vyse", "维斯"]},
    "veto":       {"cn": "禁灭",   "role": "哨卫", "nick": ["veto", "禁灭"]},
}

# 定位别名（社区口语）
ROLES: dict = {
    "duelist":    "决斗",
    "fighter":    "决斗",
    "entry":      "突破手",
    "entry fragger": "突破手",
    "initiator":  "先锋",
    "ini":        "先锋",
    "controller": "控场",
    "sentinel":   "哨卫",
    "sen":        "哨卫",
    "senti":      "哨卫",
}

# 歧义词：smoke/smoker 既能指定位（烟位），也能指道具（烟）。
# 实测 "brimstone smoke" 曾被误判成「炼狱 控场」——
# 队友喊的是"炼狱丢了个烟"，不是"炼狱是控场"。
# 只有后面跟着选人/定位类词时才当定位讲。
# 短缩写白名单：这些 2 字母词在游戏语音里无歧义，
# 必须放行（"he has op" 是喊得最多的报点之一）。
# 不在表内的 2 字母昵称仍然跳过，避免误伤正常英文单词。
SHORT_SAFE = {"op", "pha", "vnd", "grd", "spc", "sge", "frz", "jge"}

AMBIGUOUS_ROLES = {"smoke": "控场", "smoker": "控场"}
ROLE_CONTEXT = (
    "player", "picking", "pick", "main", "playing", "on", "is", "my", "our",
    "who", "role", "选", "玩", "位置", "定位", "英雄", "哪个",
)

# ---------------------------------------------------------------------------
# 武器
# ---------------------------------------------------------------------------
WEAPONS: dict = {
    # ---- 步枪 ----
    # 注意 PHANTOM 国服官方名是「幻影」；「幻象」是台服/繁体译名。
    "vandal":     {"cn": "狂徒", "cls": "步枪",   "nick": ["vandal", "vnd", "狂徒"]},
    "phantom":    {"cn": "幻影", "cls": "步枪",   "nick": ["phantom", "pha", "幻影", "幻象"]},
    "guardian":   {"cn": "戍卫", "cls": "步枪",   "nick": ["guardian", "戍卫", "grd"]},
    "bulldog":    {"cn": "獠犬", "cls": "步枪",   "nick": ["bulldog", "獠犬", "布尔多格"]},
    "arcane":     {"cn": "悍狼", "cls": "步枪",   "nick": ["arcane", "悍狼"]},
    "spectre":    {"cn": "骇灵", "cls": "冲锋枪", "nick": ["spectre", "spc", "骇灵"]},
    # ---- 狙击 ----
    "operator":   {"cn": "冥驹", "cls": "狙击枪", "nick": ["operator", "op", "冥驹", "大狙"]},
    "marshal":    {"cn": "飞将", "cls": "狙击枪", "nick": ["marshal", "飞将", "鸟狙"]},
    "outlaw":     {"cn": "莽侠", "cls": "狙击枪", "nick": ["outlaw", "莽侠"]},
    # ---- 手枪 ----
    "ghost":      {"cn": "鬼魅", "cls": "手枪",   "nick": ["ghost", "鬼魅", "鬼"]},
    "classic":    {"cn": "标配", "cls": "手枪",   "nick": ["classic", "标配", "经典"]},
    "sheriff":    {"cn": "正义", "cls": "手枪",   "nick": ["sheriff", "正义", "沙鹰"]},
    "frenzy":     {"cn": "狂怒", "cls": "手枪",   "nick": ["frenzy", "狂怒"]},
    "shorty":     {"cn": "短炮", "cls": "手枪",   "nick": ["shorty", "短炮"]},
    # ---- 霰弹 / 机枪 ----
    "judge":      {"cn": "判官", "cls": "霰弹枪", "nick": ["judge", "判官"]},
    "bucky":      {"cn": "雄鹿", "cls": "霰弹枪", "nick": ["bucky", "雄鹿", "巴克"]},
    "stinger":    {"cn": "蜂刺", "cls": "冲锋枪", "nick": ["stinger", "蜂刺"]},
    "ares":       {"cn": "战神", "cls": "机枪",   "nick": ["ares", "战神"]},
    "odin":       {"cn": "奥丁", "cls": "机枪",   "nick": ["odin", "奥丁"]},
}

# ---------------------------------------------------------------------------
# 地图（国际服叫法 -> 国服/社区通用叫法）
# ---------------------------------------------------------------------------
MAPS: dict = {
    "ascent":     " ascent（亚海悬城）",
    "bind":       "bind（劫境之地）",
    "haven":      "haven（亚海悬城·防守）",
    "split":      "split（分裂）",
    "bind":       "bind（劫境之地）",
    "pearl":      "pearl（深海明珠）",
    "lotus":      "lotus（莲花古城）",
    "icebox":     "icebox（冰封之地）",
    "sunset":     "sunset（落日之城）",
    "abyss":      "abyss（深渊）",
    "corrode":    "corrode（腐蚀）",
}


# ---------------------------------------------------------------------------
# 查表
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# 英雄名与普通英文单词撞车（v0.2.6 审计发现）
# ---------------------------------------------------------------------------
# 实测：\bsage\b 会把 "sage advice"（睿智的建议）译成「贤者 advice」。
# 这批英雄名本身就是常用英文单词，裸整词匹配必然误伤：
#     sage     adj. 睿智的
#     chamber  n.   房间 / 议事厅
#     fade     v.   褪色、消失
#     harbor   v.   窝藏；避风港
#     breach   n/v. 违反、缺口、突破
#     veto     v.   否决
COLLIDING_AGENTS = {"sage", "chamber", "fade", "harbor", "breach", "veto",
                    "phoenix"}

# v0.2.10：单字母点位信号。必须与其他语境信号**同时**出现才算数，
# 单独出现不���（英文冠词 a 和 "a big breach" 撞车）。
_WEAK_CONTEXT = ("a", "b", "c")

# 游戏语境信号：句中见到任意一个，才认为说的是游戏里的英雄
GAME_CONTEXT = (
    # 技能/动作
    "ult", "ultimate", "ability", "abil", "skill", "heal", "healing", "res",
    "flash", "smoke", "wall", "molly", "boom", "boom boom", "recon", "drone",
    "trap", "camera", "tp", "teleport", "nade", "dog", "orb", "shard",
    "defuse", "plant", "spike", "peek", "trade", "save", "camp", "hold",
    "flank", "lurk", "entry", "recon arrow", "kit", "gun", "gunner",
    # 点位
    "site", "spawn", "main", "short", "long", "mid", "midway", "heaven",
    "hell", "top", "link", "window", "tunnel", "garage", "hut",
    # v0.2.10：a / b / c 已移到 _WEAK_CONTEXT —— 英文冠词/字母太常见，
    # 单独出现不能当游戏语境（实测 "a big breach" 被误判成铁臂）
    # 选人/状态
    "pick", "play", "playing", "main", "locked", "dead", "alive", "one",
    "two", "three", "is", "was", "has", "have", "on", "left", "right",
    "swapped", "picked", "selected",
    # 武器
    "vandal", "phantom", "guardian", "operator", "marshal", "ghost",
    "sheriff", "judge", "bucky", "odin", "ares", "spectre", "stinger",
    "outlaw", "bulldog", "frenzy", "shorty", "classic",
)


def _has_game_context(text: str) -> bool:
    """判断句中是否有游戏语境信号。

    v0.2.10 修正：单字母 a / b / c **单独出现不算**语境信号。
    实测 "that is a big breach" 因为含冠词 a 就被判成在说铁臂。
    游戏报点不会只喊一个孤零零的 a，所以要求它旁边还有别的信号。
    """
    low = " " + (text or "").lower() + " "
    strong = False
    weak_letter = False
    for w in GAME_CONTEXT:
        if w.isascii() and len(w) <= 2:
            # a / b / c 这类单字母点位：要求独立出现，且只能算弱信号
            if re.search(rf"\b{w}\b", low):
                weak_letter = True
        elif w in low:
            return True
    # 只有弱信号（孤零零一个 a）-> 不算语境，放行给云端
    # 但如果**同时**还有另一个非单字母信号，上面循环里已经 return True 了
    if weak_letter:
        return False
    # 其他英雄名同时出现也算语境（"sage and sova"）
    for en in AGENTS:
        if en in COLLIDING_AGENTS:
            continue
        if re.search(rf"\b{re.escape(en)}\b", low, re.I):
            return True
    return False


def _norm(s: str) -> str:
    return (s or "").strip().lower().replace(".", "").replace(" ", "")


def _collides(en: str, info: dict, text: str) -> bool:
    """这个名词是否需要走歧义保护。

    需要保护 = 它既是英雄名/别名，又是常用英文单词
    **且** 不是「整句只喊这一个名字」。

    v0.2.10：本函数是歧义保护的**唯一入口**。
    此前 translate_fixed 与 match_agent 各自复制了一份判断，
    导致只改一处时另一处失效（audit_agents_ambiguity 绿、
    audit_callouts 里 7 个英雄仍返回 None）。同一份逻辑只留一份。
    """
    if en not in COLLIDING_AGENTS:
        return False
    if _is_standalone_shout(text, en, info):
        return False
    return not _has_game_context(text)


# 喊话时常见的口头禅/语气词：剥掉后如果只剩英雄名，就算「单独喊」
_SHOUT_FILLER = re.compile(
    r"\b(hey|hi|yo|ok|okay|guys?|team|bro|come on|lets go|go go|"
    r"is|are|he|she|they|we|i|my|their|on|in|at|to|of|it|that|"
    r"please|now|one|two|three|1|2|3)\b", re.I)


def _is_standalone_shout(text: str, en: str, info: dict) -> bool:
    """整句去掉口头禅后是否【只剩】这个英雄名（或它的昵称）。

    True  -> 玩家就是在喊这个英雄，直接译（不再要求游戏语境）
    False -> 名字嵌在句子里（如 "sage advice"），走歧义保护

    剥掉的只是语气/人称/数字这类**不含信息**的词；
    "phoenix dead" 会留下 "phoenix dead" 两个词 -> False，走语境判断，
    而 "phoenix"、"hey phoenix"、"phoenix is dead"（剥掉 is）
    都能正确判为单独喊。
    """
    import re as _re
    s = (text or "").strip()
    if not s:
        return False
    # 先去掉所有非字母数字（标点、多余空格）
    s = _re.sub(r"[^\w\s]", " ", s, flags=_re.UNICODE)
    s = _SHOUT_FILLER.sub(" ", s)
    s = _re.sub(r"[\s']+", " ", s).strip().lower()
    if not s:
        return False
    # 允许的写法：英雄英文名，或任一非短昵称
    if s == en.lower():
        return True
    for nk in info.get("nick", []):
        nk = str(nk).strip().lower()
        if nk and s == nk:
            return True
    return False


def match_agent(text: str):
    """在文本里找英雄名。命中返回 (英雄英文名, 中文名)，否则 (None, None)。

    只做整词匹配（词边界），避免 "sage" 命中 "message"。
    但 sage/chamber/fade/harbor/breach/veto/phoenix 本身是常用英文单词，
    必须额外要求游戏语境信号，否则 "sage advice" 会被译成「贤者 advice」。

    v0.2.10 修正：歧义保护对「整句只有一个英雄名」过严了。
        实测 phoenix / breach / fade / harbor / sage / chamber / veto
        共 7 个英雄单独喊时全部返回 None —— 浮窗里会直接不显示译文。
    理由：这是《无畏契约》游戏语音，队友整句只喊一个词、
        没有其他语境时，说的就是这个英雄，不可能是普通英语。
        歧义保护只该作用于「嵌在长句里」的情况
        （"sage advice" 该放行给云端，"phoenix" 该译成「不死鸟」）。
    """
    import re
    low = " " + _norm_with_space(text) + " "
    ctx = None
    for en, info in AGENTS.items():
        # 英文名整词
        if re.search(rf"\b{re.escape(en)}\b", low, re.I):
            if _collides(en, info, text):
                continue          # 普通英文用法，放行给云端
            return en, info["cn"]
        # 音译/昵称
        # v0.2.10 修正：原来用 _norm() 去空格做子串匹配，
        # 于是 "a strange chamber" -> "astrangechamber" 里**包含** "astra"，
        # 被星礈误命中。ASCII 昵称必须走词边界；
        # 纯中文昵称（不死鸟/奶妈）没有词边界，仍走子串匹配。
        for nk in info["nick"]:
            nkl = _norm(nk)
            if not nkl or nkl.isascii() and len(nkl) < 3:
                continue
            if nkl.isascii():
                if re.search(rf"\b{re.escape(nkl)}\b", low):
                    return en, info["cn"]
            elif nkl in _norm(low):
                return en, info["cn"]
    return None, None


def _norm_with_space(s: str) -> str:
    return (s or "").strip().lower()


def match_weapon(text: str):
    """在文本里找武器名。命中返回 (英文名, 中文名)。"""
    import re
    low = " " + _norm_with_space(text) + " "
    for en, info in WEAPONS.items():
        if re.search(rf"\b{re.escape(en)}\b", low, re.I):
            return en, info["cn"]
    # 裸 nick（如 "op" / "大狙"）
    for en, info in WEAPONS.items():
        for nk in info["nick"]:
            nkl = _norm(nk)
            if not nkl:
                continue
            if re.search(rf"\b{re.escape(nkl)}\b", low, re.I):
                return en, info["cn"]
    return None, None


def match_role(text: str):
    """在文本里找定位。命中返回 (英文, 中文)。

    歧义词（smoke/smoker）必须满足 ROLE_CONTEXT 才算定位，
    否则一律留给道具层译成「烟」——见 AMBIGUOUS_ROLES 注释。
    """
    import re
    low = " " + _norm_with_space(text) + " "
    for en, cn in ROLES.items():
        if re.search(rf"\b{re.escape(en)}\b", low, re.I):
            return en, cn
    # 歧义词：看上下文
    for en, cn in AMBIGUOUS_ROLES.items():
        m = re.search(rf"\b{re.escape(en)}\b", low, re.I)
        if not m:
            continue
        around = low[max(0, m.start() - 30):m.end() + 30]
        if any(re.search(rf"\b{re.escape(c)}\b", around) for c in ROLE_CONTEXT):
            return en, cn
    return None, None


def translate_fixed(text: str, target: str = "zh"):
    """把句中的固定名词（英雄/武器/定位）翻成中文。

    - target=zh：英文 -> 官方中文名（+ 社区昵称里更常用的那个）
    - target!=zh：中文/英文 -> 英文（队友只认英文代号）

    只替换名词，不改句子结构。命中返回 (译文, 'local')，否则 (None, '')。
    """
    raw = (text or "").strip()
    if not raw:
        return None, ""
    out = raw
    hit = False

    import re

    if target == "zh":
        # 先主键（jett / vandal / operator …）
        ctx = None
        for table in (AGENTS, WEAPONS):
            for en, info in table.items():
                if re.search(rf"\b{re.escape(en)}\b", out, re.I):
                    # v0.2.10：与 match_agent 共用同一份歧义判定
                    if _collides(en, info, text):
                        continue
                    out = re.sub(rf"\b{re.escape(en)}\b", info["cn"], out,
                                 flags=re.I)
                    hit = True
        # 再社区/音译别名（op / 大狙 / 奇乐 / 奶妈 …）
        # 长度门槛 2：太短的别名（"nn"）容易误伤正常英文单词。
        for table in (WEAPONS, AGENTS):
            for en, info in table.items():
                for nk in info["nick"]:
                    nkl = nk.strip()
                    if not nkl:
                        continue
                    # 短缩写只放行白名单（op/pha/vnd…），其余仍跳，
                    # 防止 "nn" 这类昵称撞上正常英文单词。
                    if nkl.isascii() and len(nkl) < 3 \
                            and nkl.lower() not in SHORT_SAFE:
                        continue
                    if len(nkl) < 2:
                        continue
                    if nkl.lower() in ("cn", info["cn"]):
                        continue
                    # 撞车门槛：昵称循环也必须判语境，
                    # 否则 AGENTS["sage"]["nick"] 里的 "sage"
                    # 会绕过主键那层的保护再来一遍。
                    if _collides(en, info, text):
                        continue
                    pat = (rf"\b{re.escape(nkl)}\b" if nkl.isascii()
                           else re.escape(nkl))
                    if re.search(pat, out, re.I):
                        out = re.sub(pat, info["cn"], out, flags=re.I)
                        hit = True
        en, cn = match_role(raw)
        if en:
            out = re.sub(rf"\b{re.escape(en)}\b", cn, out, flags=re.I)
            hit = True
    else:
        # 反向：中文名 -> 英文（队友只认英文代号）
        import re
        for en, info in AGENTS.items():
            if info["cn"] in out:
                out = out.replace(info["cn"], en.capitalize())
                hit = True
        for en, info in WEAPONS.items():
            if info["cn"] in out:
                out = out.replace(info["cn"], en.capitalize())
                hit = True
        # ★ v0.2.17：中文昵称（奶妈/大狙…）也换成英文代号
        _sink: list = []
        out = _swap_zh_nicknames(out, _sink)
        if _sink:
            hit = True

    if not hit:
        return None, ""
    return out, "local"


def _swap_zh_nicknames(out: str, hit_sink: list) -> str:
    """★ v0.2.17（中译英方向）：中文**昵称**也换成英文代号。

    用户实测「奶妈别送」里 奶妈=贤者(Sage)——旧代码只认官方名「贤者」，
    昵称整组漏网。只换 2 字以上中文昵称（「零」这类单字会误伤数字/口语），
    长名优先防子串互踩。
    """
    import re  # noqa: F401  （与 translate_fixed 内的 import 保持一致的局部风格）
    for table in (AGENTS, WEAPONS):
        for en, info in table.items():
            nicks = sorted({str(nk).strip() for nk in info.get("nick", [])
                            if str(nk).strip() and not str(nk).strip().isascii()
                            and str(nk).strip() != info["cn"]},
                           key=len, reverse=True)
            for nkl in nicks:
                if len(nkl) >= 2 and nkl in out:
                    out = out.replace(nkl, en.capitalize())
                    hit_sink.append(True)
    return out


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    print(f"英雄 {len(AGENTS)} 位 / 武器 {len(WEAPONS)} 把")
    print()
    print("=== 英雄名 ===")
    for t in ["gekko", "killjoy", "cypher", "sage", "omen", "brimstone",
              "viper", "sova", "kayo", "jett", "chamber", "fade"]:
        en, cn = match_agent(t)
        print(f"  {t:<14} -> {cn}")
    print()
    print("=== 武器名 ===")
    for t in ["vandal", "op", "ghost", "sheriff", "judge", "odin"]:
        en, cn = match_weapon(t)
        print(f"  {t:<14} -> {cn}")
    print()
    print("=== 句内替换 ===")
    for t in ["gekko diff", "killjoy on A", "cypher ult", "sage heal me",
              "brimstone smoke", "he has vandal"]:
        print(f"  {t!r:22} -> {translate_fixed(t)[0]!r}")
    print()
    print("=== 反向（中译英，队友只认英文代号）===")
    for t in ["盖可 disparity", "奇乐去A", "零残局"]:
        print(f"  {t!r:22} -> {translate_fixed(t, 'en')[0]!r}")