# -*- coding: utf-8 -*-
# 作者: cing  ·  https://github.com/cingzz
# 许可: GPL-3.0 + 商业授权（闭源/商用需向作者申请授权），见 LICENSE 与 LICENSE-COMMERCIAL.md
#
"""《无畏契约》游戏术语库 —— 提升翻译准确度。

为什么需要
----------
通用翻译模型对游戏黑话理解很差，实测典型错误：
    "我的发"  →  "My hair"     （应为 "my spike / I'm dropping"）
    "打龙"    →  "hit dragon"  （应为 "defuse the spike"）
    "起枪"    →  "get a gun"   （应为 "full buy"）
术语注入后翻译模型会按游戏语义理解，而非字面直译。

术语条目结构
------------
    key: 触发词（英文小写，中译英时作为提示词，英文译中时用于匹配）
    zh  : 中文标准译法（团队内部沟通用语）
    en  : 英文标准说法
    ko  : 韩文标准说法（韩服/日服队友语音）
    ja  : 日文说法
    note: 歧义说明（多义词时必填，例：hair = 发型 vs spike 的谐音梗）
    alias: 常见变体/口语说法，匹配用

坐标约定
--------
    key / alias 用于**英文→中文**方向的关键词匹配（队友说英文时）
    zh / en / ko / ja 用于**注入 LLM 提示词**，指导目标语言输出

维护
----
新增术语只需在 TERMS 里追加一条；按 `al` 字段分组便于查阅。
数据来源：官方/社区通用叫法（Patch 13.04 地图池：Ascent / Split / Abyss /
Lotus / Sunset / Haven / Summit）。点位名用**跨图通用词**优先，
因为玩家语音里说的多是 "A site" "mid" 这类泛称而非地图专属命名。
"""

# ---------------------------------------------------------------------------
# 1. 核心玩法术语（最高频，必须全对）
# ---------------------------------------------------------------------------
TERMS = [
    # key,             zh,             en,                 ko,                 ja,                  note,                          alias
    dict(key="spike", zh="包", en="spike", ko="스파이크", ja="スパイク",
         note="包体本身；plant=下包，defuse=拆包。「我的发」是 spike 的谐音梗",
         alias=["the spike", "spike carrier"]),
    dict(key="plant", zh="下包", en="plant the spike", ko="스파이크 설치", ja="スパイク設置",
         note="把包安放并启动；不是植物 plant", alias=["planting", "plant it", "planting now"]),
    dict(key="defuse", zh="拆包", en="defuse", ko="스파이크 해제", ja="スパイク解除",
         note="拆除已安放的包；玩家常直接喊 defuse 不带宾语", alias=["defusing", "defuse it", "defusing now"]),
    dict(key="site", zh="点位", en="site", ko="거점", ja="サイト",
         note="炸弹点位；A site/B site/C site", alias=["a site", "b site", "c site", "a spot", "b spot"]),
    dict(key="rotate", zh="转点", en="rotate", ko="회전", ja="ローテ",
         note="从一路转去另一路；不是旋转", alias=["rotating", "rotate now", "rotation"]),
    dict(key="rush", zh="冲", en="rush", ko="돌파", ja="ラッシュ",
         note="全员快速推进", alias=["rushing", "rush them", "rush in"]),
    dict(key="push", zh="推进", en="push", ko="진입", ja="プッシュ",
         note="向某方向压进；区别于 rotate", alias=["pushing", "push mid"]),
    dict(key="hold", zh="架住", en="hold", ko="지키다", ja="ホルド",
         note="守住某点位", alias=["holding", "hold an angle", "hold site"]),
    dict(key="flank", zh="绕后", en="flank", ko="플랭크", ja="フランク",
         note="从侧翼包抄", alias=["flanking", "flank them"]),
    dict(key="peek", zh="拉枪线/探身", en="peek", ko="픽", ja="ピーク",
         note="从掩体后探身看；jiggle peek=抖枪探身", alias=["peeking", "peek it", "shoulder peek", "jiggle peek"]),
    dict(key="trade", zh="换血", en="trade", ko="트리드", ja="トレード",
         note="我死后队友补枪；不是交易", alias=["trading", "trade me", "trade kill"]),
    dict(key="recon", zh="侦察", en="recon", ko="정찰", ja="リコン",
         note="获取信息；Recon 也能指 agent", alias=["recon info", "need recon"]),
    dict(key="economy", zh="经济局", en="economy round", ko="이코노미 라운드", ja="エコノミー",
         note="省钱 buying 的一局", alias=["eco round", "on eco"]),
    dict(key="full buy", zh="起全枪", en="full buy", ko="풀바이", ja="フルバイ",
         note="这局全买枪", alias=["full buy round", "buying heavy"]),
    dict(key="eco", zh="经济局", en="eco", ko="이코", ja="エコ",
         note="省钱的打法", alias=[]),
    dict(key="force buy", zh="强起", en="force buy", ko="포스바이", ja="フォースバイ",
         note="钱不够也硬买", alias=["forcing"]),
    dict(key="save", zh="保枪", en="save", ko="절약", ja="セーブ",
         note="留钱下一局；save the spike = 保住包不丢",
         alias=["saving", "save it", "save the spike"]),
    dict(key="clutch", zh="残局", en="clutch", ko="클러치", ja="クラッチ",
         note="1vN 决胜局", alias=["clutching"]),

    # -----------------------------------------------------------------------
    # 2. 枪械与技能（"我的发"这类误译的高发区）
    # -----------------------------------------------------------------------
    dict(key="vandal", zh="幻锋", en="Vandal", ko="밴달", ja="バンダル",
         note="Vandal=幻锋（正式名）；玩家常说 the V、伤害枪",
         alias=["the v", "vandy", "vandil", "vandl"]),
    dict(key="phantom", zh="幻影", en="Phantom", ko="팬텀", ja="ファントム",
         note="Phantom=幻影；不发声，贴脸强", alias=["the phantom", "fanta", "fandango"]),
    dict(key="operator", zh="冥驹", en="Operator", ko="오퍼레이터", ja="オペレーター",
         note="Operator=冥驹（官方名，玩家多说 op/大狙/sniper/scope；单说「狙」有歧义——莽侠也是狙）",
         alias=["op", "the op", "sniper", "scope", "oneshot", "one shot", "o3"]),
    dict(key="sheriff", zh="警长", en="Sheriff", ko="셰리프", ja="シェリフ",
         note="Sheriff=警长；玩家问 sheriff? 表示能否打头",
         alias=["shef", "sherif"]),
    dict(key="ghost", zh="鬼魅", en="Ghost", ko="고스트", ja="ゴースト",
         note="Ghost=鬼魅；名字容易被译成'幽灵'", alias=[]),
    dict(key="judge", zh="审判", en="Judge", ko="저지", ja="ジャッジ",
         note="霰弹枪", alias=["the judge", "boom"]),
    dict(key="bucky", zh="雄鹿", en="Bucky", ko="버키", ja="バッキー",
         note="Bucky=雄鹿霰弹；常简称 bucky", alias=[]),
    dict(key="bullet", zh="重型", en="Bulldog", ko="불독", ja="ブルドッグ",
         note="Bulldog 重型霰弹，玩家简称 bulldog、the dog", alias=["bulldog", "the dog"]),
    dict(key="stinger", zh="蜂医", en="Stinger", ko="스티커", ja="スティンガー",
         note="Stinger 轻型机枪", alias=[]),
    dict(key="marshal", zh="校准者", en="Marshal", ko="마샬", ja="マーシャル",
         note="Marshal 手枪", alias=[]),
    dict(key="outlaw", zh="莽侠", en="Outlaw", ko="아웃로", ja="アウトロー",
         note="双管狙 Outlaw", alias=[]),
    dict(key="odin", zh="奥丁", en="Odin", ko="오딘", ja="オーディン",
         note="机枪 Odin", alias=[]),
    dict(key="ares", zh="战神", en="Ares", ko="아레스", ja="アレス",
         note="机枪 Ares", alias=[]),
    dict(key="flash", zh="闪光", en="flash", ko="플래시", ja="フラッシュ",
         note="闪光弹/致盲技能；flash for you = 我给你闪光",
         alias=["flash me", "flashed", "flashed"]),
    dict(key="smoke", zh="烟", en="smoke", ko="스모크", ja="スモーク",
         note="烟雾弹/烟墙", alias=["smokes", "smoked"]),
    dict(key="molly", zh="燃烧弹", en="molly", ko="몰리", ja="モリー",
         note="Molotov 燃烧弹，简称 molly", alias=["molotov", "fire"]),
    dict(key="ult", zh="大招", en="ultimate", ko="궁극기", ja="アルティメット",
         note="ultimate=大招，简称 ult", alias=["ult", "ults", "their ult"]),
    dict(key="ability", zh="技能", en="ability", ko="스킬", ja="アビリティ",
         note="agent 技能", alias=["abilities", "skill"]),

    # -----------------------------------------------------------------------
    # 3. 经济与枪械配件（"起枪"类误译）
    # -----------------------------------------------------------------------
    dict(key="buy", zh="买", en="buy", ko="구매", ja="買う",
         note="buy 枪械/技能", alias=["buying", "bought"]),
    dict(key="credits", zh="钱", en="credits", ko="크레딧", ja="クレジット",
         note="经济系统的钱", alias=["cred", "money"]),
    dict(key="armor", zh="护甲", en="armor", ko="방어막", ja="アーマー",
         note="轻甲/重甲 shields", alias=["shields", "shield", "light armor", "heavy armor"]),
    dict(key="light armor", zh="轻甲", en="light shields", ko="가벼운 방어막", ja="軽いシールド",
         note="= 25 护盾", alias=["light shield", "25 armor"]),
    dict(key="heavy armor", zh="重甲", en="heavy shields", ko="무거운 방어막", ja="重いシールド",
         note="= 50 护盾", alias=["heavy shield", "50 armor"]),
    dict(key="phantom under", zh="幻影压枪线", en="phantom recoil control", ko="팬텀 사격", ja="ファントム",
         note="压幻影弹道", alias=[]),
    dict(key="recoil", zh="后坐力/压枪", en="recoil", ko="반동", ja="反動",
         note="压枪线", alias=["recoil control", "spray", "spray control"]),

    # -----------------------------------------------------------------------
    # 4. 通用位置词（跨地图，玩家语音里说得最多）
    # -----------------------------------------------------------------------
    dict(key="mid", zh="中路", en="mid", ko="中路", ja="ミドル",
         note="中路；不是 middle", alias=["middle", "mids", "the mid"]),
    dict(key="top", zh="上方/上", en="top", ko="상단", ja="トップ",
         note="地图上方区域（相对各自出生点）", alias=["the top"]),
    dict(key="bottom", zh="下方/下", en="bottom", ko="하단", ja="ボトム",
         note="地图下方区域", alias=["the bottom", "bot"]),
    dict(key="spawn", zh="出生点", en="spawn", ko="스폰", ja="スポーン",
         note="attacker/defender spawn", alias=["att spawn", "def spawn", "defender spawn", "attacker spawn"]),
    dict(key="link", zh="连接道", en="link", ko="링크", ja="リンク",
         note="两路之间的连接通道", alias=[]),
    dict(key="window", zh="窗口/窗", en="window", ko="창문", ja="窓",
         note="破窗点位", alias=[]),
    dict(key="door", zh="门", en="door", ko="문", ja="ドア",
         note="门口/门后", alias=[]),
    dict(key="wall", zh="墙", en="wall", ko="벽", ja="壁",
         note="穿墙/架墙", alias=["wallbang", "wall bang"]),
    dict(key="hall", zh="走廊", en="hallway", ko="복도", ja="廊下",
         note="长廊通道", alias=["hall", "corridor"]),
    dict(key="corner", zh="角", en="corner", ko="모서리", ja="コーナー",
         note="卡角度", alias=["angles", "hold the angle"]),
    dict(key="back site", zh="点位深处/包点后", en="back of site", ko="거점 뒤", ja="サイト奥",
         note="点位最里面", alias=["back site", "deep site"]),
    dict(key="entry", zh="首杀位/突破点", en="entry", ko="진입로", ja="エントリー",
         note="进点位置；entry frag = 首杀", alias=["entry frag", "entry point"]),
    dict(key="lurk", zh="绕后伏击", en="lurk", ko="매복", ja="ラーク",
         note="绕后偷袭", alias=["lurking"]),

    # -----------------------------------------------------------------------
    # 5. 地图专属点位（补丁 13.04 地图池）
    #     玩家语音常混用英文原名，这里给出标准中文叫法
    # -----------------------------------------------------------------------
    # --- Ascent ---
    dict(key="market", zh="市场（Ascent 中路）", en="mid market", ko="마켓", ja="マーケット",
         note="Ascent 中路市场", alias=["mid market", "the market"]),
    dict(key="tree", zh="树（Ascent）", en="tree", ko="트리", ja="ツリー",
         note="Ascent 中路树位", alias=[]),
    dict(key="bathroom", zh="卫生间（Ascent）", en="bathroom", ko="욕실", ja="バスルーム",
         note="Ascent A 点后卫生间", alias=[]),
    dict(key="garage", zh="车库（Ascent）", en="garage", ko="차고", ja="ガレージ",
         note="Ascent A 大车库", alias=[]),
    dict(key="cubby", zh="小隔间（Ascent）", en="cubby", ko="커비", ja="カビー",
         note="Ascent 中路小凹角", alias=["cubbies", "the cubby"]),

    # --- Bind ---
    dict(key="a short", zh="A 大道（Bind）", en="A short", ko="에이 쇼트", ja="Aショート",
         note="Bind A 点短道；这是地图专属叫法", alias=["a short", "short a", "a-short"]),
    dict(key="truck", zh="卡车（Bind）", en="truck", ko="트럭", ja="トラック",
         note="Bind A 车斗位", alias=[]),
    dict(key="elbow", zh="弯角（Bind/Split）", en="elbow", ko="엘보", ja="エルボ",
         note="中路拐角", alias=["b elbow", "a elbow", "mid elbow"]),
    dict(key="hookah", zh="水烟房（Bind）", en="hookah", ko="후카", ja="フカ",
         note="Bind 防守方回防用水烟房区域", alias=["hookah", "the tube"]),
    dict(key="greenhouse", zh="温室（Bind）", en="greenhouse", ko="그린하우스", ja="グリーンハウス",
         note="Bind 温室", alias=[]),

    # --- Haven ---
    dict(key="c site", zh="C 点（Haven）", en="C site", ko="씨 거점", ja="Cサイト",
         note="Haven 三点位图的 C 点", alias=["c", "the c"]),
    dict(key="long", zh="长道", en="long", ko="롱", ja="ロング",
         note="Haven A 长 / Split A 长；玩家只说 long 表示 A 长",
         alias=["a long", "long a", "long corner"]),
    dict(key="garage haven", zh="车库（Haven）", en="garage", ko="차고", ja="ガレージ",
         note="Haven C 侧车库", alias=[]),
    dict(key="kitchen", zh="厨房（Haven）", en="kitchen", ko="키친", ja="キッチン",
         note="Haven C 厨房", alias=[]),

    # --- Split ---
    dict(key="heaven", zh="二楼", en="heaven", ko="헤이븐", ja="ヘブン",
         note="Split B 点上方；也可能指自家阵亡位（都存在）",
         alias=["b heaven", "heaven b", "the heaven"]),
    dict(key="ropes", zh="绳索（Split）", en="ropes", ko="로프", ja="ロープ",
         note="Split A 侧绳索通道", alias=[]),
    dict(key="vault", zh="金库（Split）", en="vault", ko="볼트", ja="ヴォルト",
         note="Split 中路金库通道", alias=[]),
    dict(key="sand yacht", zh="游艇（Split）", en="yacht", ko="요트", ja="ヨット",
         note="Split 海边游艇点位；常简称 yacht", alias=["yacht", "the yacht"]),

    # --- Lotus ---
    dict(key="waterfall", zh="瀑布（Lotus）", en="waterfall", ko="워터폴", ja="ウォーターフォール",
         note="Lotus C 侧瀑布通道", alias=[]),
    dict(key="rubber duck", zh="橡皮鸭（Lotus）", en="rubber duck", ko="러버덕", ja="ラバーダック",
         note="Lotus 橡皮鸭小道", alias=["duck", "the duck"]),
    dict(key="wheel", zh="水车（Lotus）", en="wheel", ko="휠", ja="ホイール",
         note="Lotus 转轮处", alias=["the wheel"]),
    dict(key="drop", zh="下坑（Lotus）", en="the drop", ko="드롭", ja="ドロップ",
         note="Lotus 中路下坑", alias=[]),
    dict(key="spike pit", zh="坑（Lotus）", en="pit", ko="pit", ja="ピット",
         note="Lotus 下包坑位", alias=["the pit", "pit"]),

    # --- Sunset ---
    dict(key="art", zh="艺术区（Sunset）", en="art", ko="아트", ja="アート",
         note="Sunset 中路艺术区；常简称 art", alias=["the art"]),
    dict(key="alley", zh="巷子（Sunset）", en="alley", ko="앨리", ja="路地",
         note="Sunset A 巷子", alias=[]),
    dict(key="chef", zh="厨师区（Sunset）", en="chef", ko="셰프", ja="シェフ",
         note="Sunset B 侧厨师房", alias=[]),
    dict(key="b main", zh="B 大道（Sunset）", en="B main", ko="비 메인", ja="Bメイン",
         note="Sunset B 大道", alias=["b main", "main b"]),

    # --- Abyss ---
    dict(key="well", zh="井（Abyss）", en="the well", ko="웰", ja="ウェル",
         note="Abyss 中路井道", alias=[]),
    dict(key="apex", zh="制高点（Abyss）", en="apex", ko="에이펙스", ja="アペックス",
         note="Abyss 高地", alias=[]),

    # --- Pearl ---
    dict(key="long doors", zh="长门（Pearl）", en="long doors", ko="롱 도어", ja="ロングドア",
         note="Pearl A 长门", alias=[]),
    dict(key="artillery", zh="炮击点（Pearl）", en="artillery", ko="아틸러리", ja="砲兵",
         note="Pearl A 炮击高地", alias=[]),
    dict(key="sea shells", zh="贝壳（Pearl）", en="sea shells", ko="조개껍데기", ja="貝殻",
         note="Pearl 中路贝壳区域", alias=["shells"]),

    # --- Icebox ---
    dict(key="boiler", zh="锅炉房（Icebox）", en="boiler", ko="보일러", ja="ボイラー",
         note="Icebox 锅炉房", alias=[]),
    dict(key="belt", zh="传送带（Icebox）", en="belt", ko="벨트", ja="ベルト",
         note="Icebox 传送带", alias=[]),
    dict(key="snow", zh="雪道（Icebox）", en="snow", ko="스노우", ja="スノウ",
         note="Icebox A 雪道", alias=[]),
    dict(key="screen door", zh="纱门（Icebox）", en="screen door", ko="스크린 도어", ja="スクリーンドア",
         note="Icebox B 侧纱门", alias=[]),

    # --- Fracture ---
    dict(key="rappel", zh="绳降点（Fracture）", en="rappel", ko="라펠", ja="ラペル",
         note="Fracture 绳降进入点", alias=[]),
    dict(key="cave", zh="洞穴（Fracture）", en="cave", ko="케이브", ja="洞窟",
         note="Fracture 地下洞穴通道", alias=[]),
    dict(key="sand", zh="沙地（Fracture）", en="sand", ko="샌드", ja="サンド",
         note="Fracture 沙地区域", alias=[]),

    # --- Breeze ---
    dict(key="golf", zh="高尔夫区（Breeze）", en="golf", ko="골프", ja="ゴルフ",
         note="Breeze A 侧高尔夫球洞区域；常简称 golf", alias=["the golf"]),
    dict(key="sandbar", zh="沙洲（Breeze）", en="sandbar", ko="샌드바", ja="サンドバー",
         note="Breeze 沙洲通道", alias=[]),
    dict(key="ledge", zh="悬崖边（Breeze）", en="ledge", ko=" ledge", ja="縁",
         note="Breeze 高地边缘", alias=[]),

    # --- Corrode / Summit ---
    dict(key="shrine", zh="神殿（Corrode）", en="shrine", ko="신사", ja="祠",
         note="Corrode 神殿区域", alias=[]),
    dict(key="bridge", zh="桥（Corrode）", en="bridge", ko="브리지", ja="橋",
         note="Corrode 桥道", alias=[]),
    dict(key="summit", zh="山顶（Summit）", en="summit", ko="서밋", ja="サミット",
         note="Summit 地图名本身", alias=[]),
    dict(key="bunker", zh="掩体（Summit）", en="bunker", ko="벙커", ja="バンカー",
         note="Summit 掩体通道", alias=[]),

    # -----------------------------------------------------------------------
    # 6. 冠军系统 / 特殊玩法
    # -----------------------------------------------------------------------
    # -----------------------------------------------------------------------
    # 5.5 高频战斗用语（社区实战口径，非官方术语表）
    #     来源：B站《超全面英文报点/名词术语/高频交流词汇》、虎扑术语帖、
    #           Reddit r/VALORANT 讨论、社区中英对照用法
    # -----------------------------------------------------------------------
    dict(key="dink", zh="爆头", en="dink", ko="딩크", ja="ディンク",
         note="headshot 谐音；社区也说 dinked / gushed", alias=["dinked", "gushed", "headshot", "hs"]),
    dict(key="pennable", zh="可穿透", en="pennable", ko="관통 가능", ja="貫通可能",
         note="penetrable 缩写，墙/箱体可打穿", alias=["pennable", "pennable wall"]),
    dict(key="wallbang", zh="穿点", en="wallbang", ko="월뱅", ja="壁越し",
         note="社区译作「穿点」，隔墙打", alias=["wall bang", "wallbanging", "wb"]),
    dict(key="rez", zh="复活", en="resurrection", ko="부활", ja="リザレクション",
         note="Sage 大招，简称 rez", alias=["rez", "rez me"]),
    dict(key="tele", zh="传送点", en="teleporter", ko="텔레포터", ja="テレポート",
         note="Bind 的传送门，简称 tele/tp", alias=["tele", "tp", "teleport"]),
    dict(key="stick", zh="强拆", en="stick", ko="스티크", ja="スティック",
         note="我掩护拆包，队友报「他强拆了」", alias=["sticking", "i stick", "sticking now"]),
    dict(key="prefire", zh="预瞄开火", en="prefire", ko="프리파이어", ja="プレファイア",
         note="穿墙预判射击", alias=["prefire", "pre firing", "prefiring"]),
    dict(key="one way", zh="单向视野", en="one way", ko="원웨이", ja="ワンウェイ",
         note="我能打你你打不到我；也可指单向烟", alias=["one way", "one-way", "one way smoke"]),
    # ── v0.2.11 社区语料补充（用户教程语料 + 港服实战视频）──
    dict(key="heaven", zh="高台", en="heaven",
         note="泛指各点位二楼/高处平台，Care heaven=小心高台"),
    dict(key="camper", zh="老六", en="camper",
         note="蹲坑阴人的人", alias=["camping", "camp"]),
    dict(key="spam", zh="穿射", en="spam", note="隔墙/隔烟扫射"),
    dict(key="lit", zh="点了一枪", en="lit",
         note="I lit him=我点了他一枪（打残）", alias=["i lit him"]),
    dict(key="one tap", zh="一枪爆头", en="one tap",
         note="一枪爆头秒杀", alias=["one tapped", "onetap"]),
    dict(key="tag", zh="点他一枪", en="tag", note="打中标记蹭血", alias=["tagged"]),
    dict(key="trade", zh="换血补枪", en="trade",
         note="队友倒了立刻补枪换回", alias=["trade kill", "trading"]),
    dict(key="entry", zh="突破", en="entry",
         note="entry fragger=第一个进点交火的突破手", alias=["entry fragger"]),
    dict(key="anti eco", zh="反经济局", en="anti-eco",
         note="明知对方经济局仍起枪对拼"),
    dict(key="half buy", zh="半起", en="half buy", note="预算≤1900 的半起"),
    dict(key="glass cannon", zh="脆皮大狙", en="glass cannon", note="大狙无甲"),
    dict(key="ult ready", zh="大招好了", en="ult ready",
         note="I got my ULT=我有大", alias=["i got my ult", "ult up"]),
    dict(key="i got money", zh="我有钱（可以发枪）", en="i got money",
         note="买阶段表示钱够可发枪", alias=["got money"]),
    dict(key="care flank", zh="小心绕后", en="care flank",
         note="提示队友注意侧翼绕后", alias=["care the flank"]),
    dict(key="care heaven", zh="小心高台", en="care heaven",
         note="提示注意二楼/高台方向"),
    dict(key="bottom frag", zh="击杀最少", en="bottom frag", note="全队击杀最少"),
    dict(key="top frag", zh="击杀最多", en="top frag", note="全队击杀最多"),
    dict(key="yolo", zh="残局莽出去", en="yolo", note="残局不守点莽上去找人对枪"),
    dict(key="drop", zh="发枪", en="drop",
         note="Drop me=发我一把枪", alias=["drop me", "buy me"]),
    dict(key="igl", zh="队伍指挥", en="igl", note="In-Game Leader"),
    dict(key="vest", zh="甲", en="vest", note="护甲", alias=["light vest", "heavy vest"]),
    dict(key="ninja defuse", zh="偷包", en="ninja defuse", ko="닌자 해제", ja="ニンジャ解除",
         note="敌人还在就开拆骗位置；tap=假拆", alias=["ninja defuse", "fake defuse", "tap"]),
    dict(key="exit frag", zh="收割", en="exit frag", ko="엑시트 프래그", ja="エグジットフラグ",
         note="包要爆了时在点位外补刀压经济", alias=["exit frag", "exit fragger", "exit kills"]),
    dict(key="entry frag", zh="首杀", en="entry frag", ko="엔트리 프래그", ja="エントリーフラッグ",
         note="突破首杀", alias=["entry frag", "entrying", "entry"]),
    dict(key="anchor", zh="守点", en="anchor", ko="앵커", ja="アンカー",
         note="蹲守的防守位", alias=["anchoring", "anchor player"]),
    dict(key="lurk", zh="走单断后", en="lurk", ko="러커", ja="ラーカー",
         note="单人游走绕后", alias=["lurking", "lurker"]),
    dict(key="aggro", zh="拉仇恨", en="aggro", ko="어그로", ja="アグロ",
         note="主动吸引火力", alias=["aggroing"]),
    dict(key="bait", zh="引诱", en="bait", ko="베이트", ja="ベイト",
         note="钓人出枪", alias=["baiting", "bait them"]),
    dict(key="utility", zh="技能道具", en="utility", ko="유틸", ja="ユーティリティ",
         note="泛指 agent 技能", alias=["util", "utils"]),
    dict(key="orb", zh="技能球", en="orb", ko="오브", ja="オーブ",
         note="地图上捡的大招充能球", alias=["orb", "orbs", "ult orb", "point"]),
    dict(key="split", zh="夹击", en="split", ko="분할", ja="スプリット",
         note="分头打两个点", alias=["splitting", "we split"]),
    dict(key="stack", zh="赌点", en="stack", ko="스택", ja="スタック",
         note="多人堆同一个点", alias=["stacking", "we stack"]),
    dict(key="default", zh="打默认", en="default", ko="디폴트", ja="デフォルト",
         note="无固定套路", alias=["playing default", "default"]),
    dict(key="post plant", zh="包已下", en="post plant", ko="설치 후", ja="設置後",
         note="包安放后的阶段", alias=["post plant", "post-plant", "after plant"]),
    dict(key="retake", zh="回防", en="retake", ko="리테이크", ja="リテイク",
         note="敌方下包后打回去", alias=["retaking", "we retake"]),
    dict(key="shift walk", zh="静步", en="shift walk", ko="시프트 워크", ja="シフトウォーク",
         note="社区也说 cut noise", alias=["shift walk", "cut noise", "walking"]),
    dict(key="thrifty", zh="捡枪翻盘", en="thrifty", ko="스리프티", ja="スリフティ",
         note="用敌人枪打赢", alias=["thrifty", "thrift"]),
    dict(key="force rotate", zh="逼转点", en="force a rotate", ko="강제 회전", ja="強制ローテ",
         note="施压逼对方转点", alias=["force rotate", "forcing a rotate"]),
    dict(key="ads", zh="开镜", en="aim down sights", ko="조준", ja="ADS",
         note="开镜瞄准", alias=["ads", "adsing", "aim down sights"]),
    dict(key="flick", zh="甩枪", en="flick shot", ko="플릭", ja="フリック",
         note="快速甩枪", alias=["flick", "flicking"]),
    dict(key="los", zh="视线内", en="line of sight", ko="시야", ja="시야",
         note="视野范围", alias=["los", "in los"]),
    dict(key="igl", zh="指挥", en="in-game leader", ko="IGL", ja="IGL",
         note="团队指挥", alias=["igl"]),
    dict(key="camp", zh="蹲点", en="camp", ko="캠프", ja="キャンプ",
         note="蹲角落不动", alias=["camping", "camped"]),
    dict(key="off angle", zh="冷枪线", en="off angle", ko="오프 앵글", ja="オフアングル",
         note="不常被搜的架枪位", alias=["off angle", "off-angle"]),
    dict(key="hit", zh="打中了", en="hit", ko="명중", ja="ヒット",
         note="打中；社区也常用 hurt 表示「打痛了」", alias=["hit", "hurt", "i hit him"]),
    dict(key="contact", zh="遇敌", en="contact", ko="접촉", ja="コンタクト",
         note="发现敌人，报「遇敌」", alias=["contact", "contact!"]),
    dict(key="finish", zh="补枪", en="finish", ko="피니시", ja="フィニッシュ",
         note="补掉残血", alias=["finish", "finishing"]),
    dict(key="cut off", zh="切断", en="cut off", ko="차단", ja="カットオフ",
         note="切断敌人退路", alias=["cut off", "cutting"]),
    dict(key="behind", zh="后路来人", en="behind", ko="뒤", ja="/",
         note="报点前缀：后面有人", alias=["behind", "behind you"]),
    dict(key="tap", zh="假拆", en="tap", ko="탭", ja="タップ",
         note="假拆包骗人再真拆", alias=["tapping", "tap the defuse"]),
    dict(key="crossfire", zh="交叉火力", en="crossfire", ko="교차 사격", ja="クロスファイア",
         note="两路夹击火力", alias=["crossfire", "cross fire"]),
    dict(key="swing", zh="拉枪", en="swing", ko="스윙", ja="スイング",
         note="双人同时拉出去", alias=["swinging", "double swing"]),
    dict(key="heal", zh="治疗", en="heal", ko="힐", ja="ヒール",
         note="队友报「需要治疗」", alias=["heal", "healing", "need heal"]),
    dict(key="drone", zh="无人机", en="drone", ko="드론", ja="ドローン",
         note="侦查无人机", alias=["drone", "drones"]),
    dict(key="blind", zh="闪白", en="blind", ko="블라인드", ja="ブライン",
         note="被闪了看不清", alias=["blinded", "blind", "im blind"]),
    dict(key="one hp", zh="残血", en="one hp", ko="체력 1", ja="HP1",
         note="一滴血/残血", alias=["one hp", "low", "one shot", "tech heavy"]),
    dict(key="fifty five", zh="打55血", en="fifty five", ko="55 체력", ja="55 体",
         note="报伤害：打了55血", alias=["55", "fifty five", "55 health"]),

    # -----------------------------------------------------------------------
    # 5.6 完整报点句式（社区高频短句，直接提升 ASR 后的翻译准确度）
    # -----------------------------------------------------------------------
    dict(key="report two mid", zh="中路两个", en="two mid", ko="中路 두 명", ja="ミドル2人",
         note="报已知人数和位置，别猜", alias=["two mid", "2 mid", "two on mid"]),
    dict(key="last one", zh="最后一个在", en="last one", ko="마지막 한 명", ja="残り1人",
         note="A clear = A点没人了", alias=["last one", "last one on a", "clear"]),
    dict(key="many on a", zh="A点很多人", en="many on A", ko="A에 많이", ja="Aに多数",
         note="A many = A点人很多", alias=["many on a", "a many", "they're on a", "on a"]),
    dict(key="spike down", zh="掉包了", en="spike down", ko="스파이크 떨어짐", ja="スパイク掉落",
         note="包掉地上了", alias=["spike down", "spike dropped", "dropped"]),
    dict(key="they planted", zh="他们下包了", en="they planted", ko="설치했어요", ja="設置された",
         note="包已安放", alias=["they planted", "planted", "its planted"]),
    dict(key="im defusing", zh="我在拆", en="im defusing", ko="해제 중", ja="解除中",
         note="报当前动作", alias=["im defusing", "defusing", "im planting"]),
    dict(key="cover me", zh="掩护我", en="cover me", ko="커버해줘", ja="カバーして",
         note="下包/拆包要掩护", alias=["cover me", "cover"]),
    dict(key="need flash", zh="需要闪光", en="need a flash", ko="플래시 필요", ja="フラッシュお願い",
         note="请求队友给闪", alias=["need flash", "need a flash", "flash me", "can you flash"]),
    dict(key="im flashing", zh="我给闪", en="im flashing", ko="플래시 줄게", ja="フラッシュ投げる",
         note="配合队友进点", alias=["im flashing", "flashing", "flashing for you"]),
    dict(key="i hear", zh="我听到", en="i hear", ko="들려", ja="聞こえる",
         note="区分听到和看到：I hear footsteps", alias=["i hear", "i hear footsteps", "hear something"]),
    dict(key="wait for me", zh="等我", en="wait for me", ko="기다려", ja="待って",
         note="请求队友同步", alias=["wait for me", "wait"]),
    dict(key="fall back", zh="先撤", en="fall back", ko="후퇴", ja="後退",
         note="提醒停止前压", alias=["fall back", "falling back", "reset"]),
    dict(key="regroup", zh=" regroup", en="regroup", ko="재집합", ja="再集結",
         note="重新集结", alias=["regroup", "regroup up"]),
    dict(key="lets rotate", zh="我们转点", en="lets rotate", ko="회전하자", ja="ローテしよう",
         note="提议换方向", alias=["lets rotate", "let's rotate", "rotate b", "rotate mid"]),
    dict(key="push with me", zh="跟我冲", en="push with me", ko="같이 가", ja="一緒に詰める",
         note="一起推进", alias=["push with me", "come with me", "lets push"]),
    dict(key="im back", zh="我回来了", en="im back", ko="복귀", ja="戻った",
         note="报位置回归", alias=["im back", "back", "im here"]),
    dict(key="need help", zh="需要帮忙", en="need help", ko="도움 필요", ja="助けて",
         note="残局请求支援", alias=["need help", "help", "im dying"]),
    dict(key="nice", zh="漂亮", en="nice", ko="좋아요", ja="ナイス",
         note="夸队友", alias=["nice", "nice shot", "ns"]),
    dict(key="thank you", zh="谢谢", en="thank you", ko="고마워", ja="サンキュー",
         note="致谢", alias=["ty", "thx", "thanks"]),
    dict(key="sorry", zh="抱歉", en="sorry", ko="미안", ja="ゴメン",
         note="失误道歉", alias=["sry", "sorry", "my bad", "mb"]),
    dict(key="good luck", zh="祝好运", en="good luck have fun", ko="좋은 판", ja="がんば",
         note="开局问候 GLHF", alias=["glhf", "good luck have fun", "gl"]),
    dict(key="lets go", zh="上", en="lets go", ko="가자", ja="いこう",
         note="进攻信号", alias=["lets go", "go go go", "execute", "let's hit"]),

    # -----------------------------------------------------------------------
    # 5.7 聊天缩写（语音/文字都高频，误译会非常尴尬）
    # -----------------------------------------------------------------------
    dict(key="glhf", zh="祝你好运", en="good luck have fun", ko="좋은 판", ja="がんば",
         note="开局问候", alias=["glhf", "gl"]),
    dict(key="gg", zh="打得好", en="good game", ko="gg", ja="おつかれ",
         note="回合结束", alias=["gg", "good game", "wp", "well played"]),
    dict(key="afk", zh="挂机", en="away from keyboard", ko="자리 비움", ja="離席",
         note="AFK", alias=["afk", "away from keyboard"]),
    dict(key="dc", zh="掉线", en="disconnect", ko="연결 끊김", ja="切断",
         note="DC", alias=["dc", "disconnect", "disconnected"]),
    dict(key="ks", zh="抢人头", en="kill steal", ko="킬 빼앗김", ja="キルスティール",
         note="抢人头", alias=["ks", "kill steal"]),
    dict(key="nt", zh="可惜", en="nice try", ko="아쉬워", ja="ナイストライ",
         note="安慰队友", alias=["nt", "nice try"]),
    dict(key="gj", zh="干得好", en="good job", ko="잘했어", ja="グッドジョブ",
         note="夸奖", alias=["gj", "good job"]),
    dict(key="nc", zh="漂亮", en="nice", ko="멋있다", ja="ナイス",
         note="夸操作", alias=["nc", "nice"]),
    dict(key="ez", zh="轻松拿下", en="easy", ko="간단", ja="イージー",
         note="嘲讽/垃圾话（GG EZ）", alias=["ez", "ezpz", "ggez", "lmao"]),
    dict(key="lmao", zh="笑死", en="laughing out loud", ko="ㅋㅋ", ja="ワロタ",
         note="喷人/嘲讽用语", alias=["lmao", "lol"]),
    dict(key="sus", zh="开挂了", en="suspicious", ko="의심", ja="怪しい",
         note="怀疑作弊", alias=["sus", "suspicious"]),
    dict(key="g2g", zh="我先走了", en="got to go", ko="갈게", ja="行きます",
         note="中途退出", alias=["g2g", "got to go", "brb"]),
    dict(key="good luck", zh="开局问候", en="glhf", ko="glhf", ja="glhf",
         note="同 glhf", alias=[]),

    # -----------------------------------------------------------------------
    # 5.8 地图专属点位（B站实战报点表，13 张图全覆盖）
    #     社区通用叫法，优先于官方译名
    # -----------------------------------------------------------------------
    # --- Ascent 义境空岛 ---
    dict(key="catwalk", zh="长径小道", en="catwalk", ko="캣워크", ja="キャットウォーク",
         note="Ascent/Breeze 共用通道，社区简称 cat", alias=["cat", "catwalk", "the cat"]),
    dict(key="garden", zh="花园", en="garden", ko="가든", ja="ガーデン",
         note="Ascent/Bind 花园", alias=["garden"]),
    dict(key="pizza", zh="披萨店", en="pizza", ko="피자", ja="ピザ",
         note="Ascent 中路披萨店，社区幽默叫法", alias=["pizza", "the pizza", "pizza place"]),
    dict(key="generator", zh="发电机", en="generator", ko="발전기", ja="発電機",
         note="全图通用点位，简称 gen", alias=["gen", "generator", "the gen", "gene"]),
    dict(key="wine", zh="酒窖", en="wine", ko="ワイン", ja="ワイン",
         note="Ascent/Pearl 酒窖", alias=["wine", "the wine"]),
    dict(key="pillar", zh="柱子", en="pillar", ko="필라", ja="柱",
         note="全图通用掩体", alias=["pillar", "the pillar"]),
    dict(key="arch", zh="拱门", en="arch", ko="아치", ja="アーチ",
         note="Ascent/Corrode 拱门", alias=["arch", "the arch"]),
    dict(key="shed", zh="棚屋", en="shed", ko="헛간", ja="小屋",
         note="Ascent 棚屋", alias=["shed"]),
    dict(key="boat", zh="船屋", en="boat", ko="보트", ja="ボート",
         note="Ascent 船屋点位", alias=["boat", "the boat"]),
    dict(key="log", zh="圆木", en="log", ko="로그", ja="丸太",
         note="Ascent/Haven 圆木掩体", alias=["log", "the log"]),
    dict(key="window", zh="窗口", en="window", ko="창문", ja="窓",
         note="全图通用", alias=["window", "the window"]),
    dict(key="green box", zh="绿箱", en="green box", ko="초록 상자", ja="緑箱",
         note="地图上的绿色掩体箱，社区统称", alias=["green box", "green crate"]),
    dict(key="wood box", zh="木箱", en="wood box", ko="나무 상자", ja="木箱",
         note="木质掩体箱", alias=["wood box", "wood crate"]),
    dict(key="dice", zh="方块箱", en="dice", ko="주사위 상자", ja="サイコロ箱",
         note="社区对某形状箱子的幽默叫法", alias=["dice", "dice box"]),
    dict(key="double box", zh="双箱", en="double box", ko="더블박스", ja="ダブルボックス",
         note="两个箱子叠放的点位", alias=["double box", "dbox"]),

    # --- Bind 劫境之地 ---
    dict(key="hookah", zh="B点窗房", en="hookah", ko="후카", ja="フカ",
         note="Bind B 侧窗房（社区直译叫法）", alias=["hookah", "the hookah"]),
    dict(key="showers", zh="淋浴间", en="showers", ko="샤워실", ja="シャワー",
         note="Bind 淋浴间", alias=["shower", "showers"]),
    dict(key="tower", zh="塔", en="tower", ko="타워", ja="タワー",
         note="全图通用塔楼点位", alias=["tower", "the tower"]),
    dict(key="fountain", zh="喷泉", en="fountain", ko="분수", ja="噴水",
         note="Bind 喷泉", alias=["fountain"]),
    dict(key="track", zh="卡车", en="truck", ko="트럭", ja="トラック",
         note="Bind A 卡车", alias=["truck", "track"]),
    dict(key="lamps", zh="灯区", en="lamps", ko="램프", ja="ランプ",
         note="Bind 灯区", alias=["lamps", "the lamps"]),
    dict(key="pallet", zh="木板角落", en="pallet", ko="팔레트", ja="パレット",
         note="Bind 木板角落", alias=["pallet"]),

    # --- Haven 遗落境地 ---
    dict(key="plat", zh="平台", en="plat", ko="플랫", ja="プラット",
         note="Haven 平台，简称 plat", alias=["plat", "platform"]),
    dict(key="fox", zh="中路凹槽", en="fox", ko="폭스", ja="フォックス",
         note="Haven 中路凹槽，社区叫 fox", alias=["fox", "the fox"]),
    dict(key="screen", zh="屏风", en="screen", ko="스크린", ja="スクリーン",
         note="Haven 屏风 / Icebox 屏幕台", alias=["screen", "the screen"]),
    dict(key="sewer", zh="下水道", en="sewer", ko="하수구", ja="下水道",
         note="Haven/Split 下水道", alias=["sewer", "sewers"]),
    dict(key="paint", zh="凹槽", en="paint", ko="페인트", ja="ペイント",
         note="Haven A 侧凹槽", alias=["paint"]),
    dict(key="gong", zh="屏风后", en="gong", ko="공", ja="ゴング",
         note="Haven B 屏风后点位", alias=["gong", "the gong"]),

    # --- Split 双塔迷城 ---
    dict(key="cloud", zh="云字箱", en="cloud", ko="클라우드", ja="クラウド",
         note="Split A 侧像云朵的箱子", alias=["cloud", "the cloud"]),
    dict(key="alley", zh="小巷", en="alley", ko="알리", ja="路地",
         note="Split 小巷", alias=["alley", "the alley"]),
    dict(key="vent", zh="绳房", en="vent", ko="벤트", ja="通気口",
         note="Split B 绳房", alias=["vent", "vents"]),
    dict(key="mail", zh="信箱", en="mail", ko="메일", ja="メール",
         note="Split 信箱", alias=["mail", "the mail"]),
    dict(key="ramen", zh="面馆", en="ramen", ko="라멘", ja="ラーメン",
         note="Split 面馆，社区幽默叫法", alias=["ramen", "the ramen"]),
    dict(key="shoe", zh="凹槽", en="shoe", ko="신발", ja="靴",
         note="Split 下水道凹槽", alias=["shoe", "the shoe"]),
    dict(key="cafe", zh="咖啡店", en="cafe", ko="카페", ja="カフェ",
         note="Split 咖啡店", alias=["cafe", "the cafe"]),
    dict(key="trash", zh="拐角", en="trash", ko="쓰레기", ja="ゴミ",
         note="Split 中路拐角", alias=["trash", "the trash"]),
    dict(key="maple", zh="枫树道", en="maple", ko="메이플", ja="メープル",
         note="Split 枫树道", alias=["maple"]),
    dict(key="rafters", zh="高台", en="rafters", ko="래프터", ja="屋根",
         note="Split 高台", alias=["rafters", "the rafters"]),

    # --- Lotus 莲华古城 ---
    dict(key="hut", zh="小屋", en="hut", ko="오두막", ja="小屋",
         note="Lotus A 小屋", alias=["hut", "the hut"]),
    dict(key="root", zh="树根", en="root", ko="뿌리", ja="根",
         note="Lotus A 大树根", alias=["root", "the root"]),
    dict(key="rubble", zh="石台", en="rubble", ko="잔해", ja="瓦礫",
         note="Lotus A 石台", alias=["rubble"]),
    dict(key="mound", zh="土堆", en="mound", ko="구릉", ja="土手",
         note="Lotus C 大土堆", alias=["mound", "the mound"]),
    dict(key="gravel", zh="碎石路", en="gravel", ko="자갈길", ja="砂利道",
         note="Lotus C 碎石路", alias=["gravel"]),
    dict(key="wheel", zh="水车", en="wheel", ko="휠", ja="ホイール",
         note="Lotus 转轮", alias=["wheel", "the wheel"]),
    dict(key="door", zh="旋转门", en="rotating door", ko="회전문", ja="回転ドア",
         note="Lotus 旋转门", alias=["rotating door", "the door"]),

    # --- Pearl 深海遗珠 ---
    dict(key="restaurant", zh="餐厅", en="restaurant", ko="식당", ja="レストラン",
         note="Pearl 餐厅", alias=["restaurant", "the restaurant"]),
    dict(key="crane", zh="起重机", en="crane", ko="크레인", ja="クレーン",
         note="Pearl/Corrode 起重机", alias=["crane", "the crane"]),
    dict(key="church", zh="教堂", en="church", ko="교회", ja="教会",
         note="Pearl 教堂", alias=["church"]),
    dict(key="soda", zh="默认下包点", en="soda", ko="소다", ja="ソーダ",
         note="Pearl A 默认下包点，社区叫 soda", alias=["soda", "the soda"]),
    dict(key="dugout", zh="死角", en="dugout", ko="더그아웃", ja="ダ “.out",
         note="Pearl A 死角", alias=["dugout", "the dugout"]),
    dict(key="secret", zh="密藏路", en="secret", ko="시크릿", ja="シークレット",
         note="Pearl A 密藏路 / Abyss 密道", alias=["secret", "the secret"]),
    dict(key="flower", zh="花店路", en="flower", ko="플라워", ja="フラワー",
         note="Pearl A 花店路", alias=["flower", "the flower"]),
    dict(key="plaza", zh="广场", en="plaza", ko="광장", ja="広場",
         note="Pearl 广场", alias=["plaza", "the plaza"]),
    dict(key="connector", zh="中路连接", en="connector", ko="커넥터", ja="コネクター",
         note="Pearl 中路连接道", alias=["connector", "the connector"]),
    dict(key="shops", zh="商店街", en="shops", ko="쇼핑몰", ja="商店街",
         note="Pearl 商店街", alias=["shops", "the shops"]),
    dict(key="club", zh="夜店", en="club", ko="클럽", ja="クラブ",
         note="Pearl 夜店", alias=["club", "the club"]),
    dict(key="tickets", zh="斜坡", en="tickets", ko="티켓", ja="チケット",
         note="Pearl B 大斜坡", alias=["tickets", "the tickets"]),
    dict(key="metro", zh="死点", en="metro", ko="메트로", ja="メトロ",
         note="Pearl B 大死点", alias=["metro", "the metro"]),

    # --- Abyss 深窟幽境 ---
    dict(key="security", zh="保安室", en="security", ko="보안실", ja="警備室",
         note="Abyss 保安室", alias=["security", "the security"]),
    dict(key="lobby", zh="大厅", en="lobby", ko="로비", ja="ロビー",
         note="全图通用：CT/T 大厅", alias=["lobby", "the lobby"]),
    dict(key="library", zh="图书馆", en="library", ko="도서관", ja="図書館",
         note="Abyss 图书馆", alias=["library", "the library"]),
    dict(key="danger", zh="悬崖", en="danger", ko="的危险", ja="",
         note="Abyss B 悬崖", alias=["danger", "the danger"]),

    # --- Sunset 日落之城 / Corrode 盐海矿镇 / 其他 ---
    dict(key="boba", zh="奶茶店", en="boba", ko="버블티", ja="ボバ",
         note="Sunset 奶茶店，社区幽默叫法", alias=["boba", "boba tea"]),
    dict(key="tiles", zh="红砖路", en="tiles", ko="타일", ja="タイル",
         note="Sunset 红砖路", alias=["tiles"]),
    dict(key="boba shop", zh="奶茶店", en="boba", ko="버블티", ja="ボバ",
         note="同 boba", alias=[]),
    dict(key="yard", zh="庭院", en="yard", ko="마당", ja="中庭",
         note="Corrode A 庭院", alias=["yard", "the yard"]),
    dict(key="pocket", zh="死点", en="pocket", ko="포켓", ja="ポケット",
         note="凹角死点，通用词", alias=["pocket", "dead pocket"]),
    dict(key="snow pile", zh="雪堆", en="snow pile", ko="눈더미", ja="雪の山",
         note="Icebox B 雪堆", alias=["snow pile", "snowpile"]),
    dict(key="snow man", zh="卷帘门", en="snow man", ko="스노우맨", ja="雪だるま",
         note="Icebox B 卷帘门，社区叫 snow man", alias=["snow man", "snowman"]),
    dict(key="tube", zh="管道", en="tube", ko="튜브", ja="チューブ",
         note="Icebox 管道", alias=["tube", "the tube"]),
    dict(key="pipe", zh="管道台", en="pipe", ko="파이프", ja="パイプ",
         note="Icebox A 点管道台", alias=["pipe", "the pipe"]),
    dict(key="kitchen", zh="厨房", en="kitchen", ko="키친", ja="キッチン",
         note="Icebox/Haven 厨房", alias=["kitchen", "the kitchen"]),
    dict(key="snake", zh="蛇道", en="snake", ko="스네이크", ja="スネーク",
         note="Breeze 蛇形通道", alias=["snake", "the snake"]),
    dict(key="cannon", zh="大炮", en="cannon", ko="캐논", ja="大砲",
         note="Breeze 大炮", alias=["cannon", "the cannon"]),
    dict(key="hall", zh="走廊", en="hall", ko="복도", ja="廊下",
         note="全图通用走廊", alias=["hall", "hallway", "the hall"]),
    dict(key="tunnel", zh="隧道", en="tunnel", ko="터널", ja="トンネル",
         note="全图通用", alias=["tunnel", "the tunnel"]),
    dict(key="ramp", zh="斜坡", en="ramp", ko="램프", ja="ランプ",
         note="全图通用", alias=["ramp", "the ramp"]),
    dict(key="stairs", zh="楼梯", en="stairs", ko="계단", ja="階段",
         note="全图通用", alias=["stairs", "the stairs", "stair"]),
    dict(key="roof", zh="屋顶", en="roof", ko="지붕", ja="屋上",
         note="全图通用", alias=["roof", "on roof", "on the roof"]),
    dict(key="alley", zh="巷子", en="alley", ko="골목", ja="路地",
         note="Sunset 巷子", alias=["alley", "the alley"]),
    dict(key="cave", zh="洞穴", en="cave", ko="동굴", ja="洞窟",
         note="Breeze/Fracture 洞穴", alias=["cave", "the cave"]),
    dict(key="rope", zh="绳索", en="rope", ko="로프", ja="ロープ",
         note="Breeze 绳索", alias=["rope", "ropes"]),
    dict(key="bridge", zh="桥", en="bridge", ko="다리", ja="橋",
         note="Breeze/Abyss/Corrode 桥", alias=["bridge", "the bridge"]),
    dict(key="nest", zh="巢室", en="nest", ko="둥지", ja="巣",
         note="全图通用架枪窝", alias=["nest", "the nest"]),
    dict(key="cubby", zh="凹槽", en="cubby", ko="커비", ja="カビー",
         note="小凹角，通用词", alias=["cubby", "pocket", "cubby hole"]),
    dict(key="market", zh="集市", en="market", ko="마켓", ja="マーケット",
         note="Ascent/Sunset 集市", alias=["market", "the market"]),
    dict(key="mid bottom", zh="中路近点", en="mid bottom", ko="中路 근처", ja="ミドル下",
         note="top/bottom mid = 远点/近点", alias=["bottom mid", "top mid", "mid bottom", "mid top"]),
    dict(key="ct spawn", zh="守方出生点", en="defender spawn", ko="수비측 스폰", ja="防衛側スポーン",
         note="CT spawn = defender spawn", alias=["ct spawn", "ct", "def spawn", "defender spawn"]),
    dict(key="t spawn", zh="攻方出生点", en="attacker spawn", ko="공격측 스폰", ja="攻撃側スポーン",
         note="T spawn = attacker spawn", alias=["t spawn", "t side", "att spawn"]),
    dict(key="a link", zh="A连接", en="A link", ko="A 연결", ja="Aリンク",
         note="两路之间的连接道", alias=["a link", "b link", "link"]),
    dict(key="front site", zh="包点前方", en="front site", ko="거점 앞", ja="サイト手前",
         note="包点入口处", alias=["front site", "back site"]),
    dict(key="one way through", zh="单向通道", en="one way", ko="원웨이", ja="ワンウェイ",
         note="单向通行的通道", alias=[]),

    # -----------------------------------------------------------------------
    # 9. 社区实战补充（用户实贴速查表：血量报数/道具代号/英雄定位/战术口令）
    # -----------------------------------------------------------------------
    # --- 血量报数（社区编码，最容易听不懂的一类）---
    dict(key="one hp", zh="一滴血", en="one hp", ko="체력 1", ja="HP1",
         note="残血；低于此伤害报数没意义", alias=["one hp", "one health", "1 hp", "low"]),
    dict(key="one twenty", zh="一百二血", en="one twenty", ko="120", ja="120",
         note="狂徒打满 120 血 = one twenty", alias=["one twenty", "120", "1 20"]),
    dict(key="one one O", zh="一百一血", en="one one O", ko="110", ja="110",
         note="正义两枪 = one one O；O 读作 ou", alias=["one one o", "110", "one ten"]),
    dict(key="one O O", zh="一百血", en="one O O", ko="100", ja="100",
         note="飞将打满 = one O O", alias=["one o o", "100", "one hundred"]),
    dict(key="eighty", zh="八十血", en="eighty", ko="80", ja="80",
         note="低于 80 的伤害报数意义不大", alias=["eighty", "80"]),
    dict(key="low", zh="大残", en="low", ko="체력 낮음", ja="残り少ない",
         note="大残血", alias=["low", "he is low", "he's low"]),

    # --- 道具代号（社区黑话，直接喊名字队友秒懂）---
    dict(key="blind", zh="黑闪", en="blind", ko="블라인드", ja="ブラインド",
         note="欧门/黑夜视野遮蔽技能，泛称盲；flash 也可", alias=["blind", "blinds", "nade"]),
    dict(key="boom boom", zh="轰boom", en="boom boom", ko="붐붐", ja="ブ-boom",
         note="范围杀伤技能的口头代号，队友秒懂", alias=["boom boom", "boomboom"]),
    dict(key="dog", zh="狗", en="dog", ko="개", ja="ドッグ",
         note="黑梦（赛芸）的侦查狗", alias=["dog", "the dog"]),
    dict(key="wall down", zh="墙要掉了", en="wall down", ko="벽 곧 사라짐", ja="壁消える",
         note="维普尔墙烟快没了，提前喊", alias=["wall down", "wall's down"]),
    dict(key="break trap", zh="拆陷阱", en="break trap", ko="함정 해제", ja="罠解除",
         note="让猎枭电道具拆", alias=["break trap", "trap broken"]),
    dict(key="trap", zh="花/陷阱", en="trap", ko="함정", ja="罠",
         note="赛芸的花/铁臂的震/钢索的花都叫 trap", alias=["trap", "flower", "the flower"]),
    dict(key="camera", zh="摄像头", en="camera", ko="카메라", ja="カメラ",
         note="赛芸的摄像头", alias=["camera", "the camera", "cyber cam"]),
    dict(key="fake tp", zh="假传送", en="fake tp", ko="가짜 텔레포트", ja="偽テレポート",
         note="欧门夜露假传送骗技能", alias=["fake tp", "fake teleport"]),
    dict(key="tp", zh="传送", en="teleport", ko="텔레포트", ja="テレポート",
         note="欧门夜露大招", alias=["tp", "teleport", "ult tp"]),
    dict(key="get orb", zh="捡技能球", en="get orb", ko="오브 줍기", ja="オーブ拾う",
         note="吸球攒大招", alias=["get orb", "orb", "take orb"]),
    dict(key="req", zh="要枪", en="request", ko="요청", ja="リクエスト",
         note="让队友给你发枪的指令", alias=["req", "request"]),
    dict(key="skin", zh="要皮肤", en="skin", ko="스킨", ja="スキン",
         note="找队友要皮肤（娱乐向）", alias=["skin"]),
    dict(key="heal", zh="奶", en="heal", ko="힐", ja="ヒール",
         note="要奶；蕾娜/暮蝶吸了也能说", alias=["heal me", "need heal", "heal"]),

    # --- 英雄定位（社区统称）---
    dict(key="duelist", zh="决斗", en="duelist", ko="듀얼리스트", ja="デュイリスト",
         note="决斗者/先锋/哨位统称 fighter", alias=["duelist", "fighter", "fight", "entry"]),
    dict(key="smoke", zh="烟位", en="smoke", ko="스모크", ja="スモーク",
         note="负责封烟图的特工", alias=["smoke", "smoker"]),
    dict(key="sentinel", zh="哨位", en="sentinel", ko="센티넬", ja="センチネル",
         note="防守/架枪位，简称 sen / senti", alias=["sentinel", "sen", "senti"]),
    dict(key="initiator", zh="先锋", en="initiator", ko="이니시에이터", ja="イニシエーター",
         note="开团位，简称 ini", alias=["initiator", "ini"]),
    dict(key="rank", zh="段位", en="rank", ko="랭크", ja="ランク",
         note="段位/分数", alias=["rank", "ranks"]),

    # --- 开局/报点口令 ---
    dict(key="a no sound", zh="A点没动静", en="A no sound", ko="A 소리 없음", ja="A 音なし",
         note="开局报点：A 点安静", alias=["a no sound", "a quiet"]),
    dict(key="care a", zh="小心A点", en="care A", ko="A 조심", ja="Aに気をつけて",
         note="care = 小心，常接地点", alias=["care a", "care b", "care mid", "watch a"]),
    dict(key="care flank", zh="小心绕后", en="care flank", ko=" flanks 조심", ja="フランク注意",
         note="担心被绕后偷屁股", alias=["care flank", "watch the flank"]),
    dict(key="two more", zh="两个以上", en="two more", ko="둘 이상", ja="2人以上",
         note="交战区域报数，不用重复报地点", alias=["two more", "three more", "two plus"]),
    dict(key="last seen", zh="最后出现", en="last seen", ko="마지막 목격", ja="最後に見た",
         note="残局报「捷特最后出现在中路」", alias=["last seen", "jett last seen"]),
    dict(key="no info", zh="没信息", en="no info", ko="정보 없음", ja="情報なし",
         note="提醒没见过这人（针对哨位）", alias=["no info", "no vision on"]),
    dict(key="close", zh="就在脸上", en="close", ko="가까이", ja="すぐそこ",
         note="人就在脸上", alias=["close", "right in front", "on me"]),
    dict(key="shoot", zh="打道具", en="shoot", ko="쏴", ja="撃って",
         note="让队友开枪打道具：shoot drone / shoot dog", alias=["shoot", "shoot it", "break it"]),
    dict(key="mid to a", zh="中路转A", en="mid to A", ko="중에서 A로", ja="ミドルからA",
         note="中路夹A", alias=["mid to a", "mid to b", "mid to c"]),
    dict(key="play slow", zh="打慢点", en="play slow", ko="천천히", ja="ゆっくり",
         note="时间不多，稳一点", alias=["play slow", "slow it down", "slow"]),
    dict(key="fake go", zh="假打", en="fake A go B", ko="가짜 A 진짜 B", ja="フェイク",
         note="假打A实则打B", alias=["fake a go b", "fake a, go b", "faking"]),
    dict(key="stack a", zh="赌A", en="stack A", ko="A에 몰린", ja="Aに賭ける",
         note="多人堆A", alias=["stack a", "stacking a", "stack b"]),
    dict(key="fight", zh="去对枪", en="fight", ko="교전", ja="交戦",
         note="主动开打", alias=["fight", "take the fight", "fight it"]),
    dict(key="double peek", zh="双拉", en="double peek", ko="더블 픽", ja="ダブルピーク",
         note="两人同时拉枪线", alias=["double peek", "double swing"]),
    dict(key="single tap", zh="点射", en="single tap", ko="단발", ja="シングルタップ",
         note="点射控枪", alias=["single tap", "tap"]),
    dict(key="spray", zh="扫射", en="spray", ko="스프레이", ja="Spray",
         note="扫射/泼水", alias=["spray", "spraying"]),
    dict(key="spam", zh="穿射", en="spam", ko="스팸", ja="スパム",
         note="穿射/火力覆盖", alias=["spam", "spamming"]),
    dict(key="open", zh="远视距下包", en="open", ko="열어", ja="オープン",
         note="远视距下包（减少近处被守）", alias=["open", "open it up"]),
    dict(key="buy time", zh="拖时间", en="buy time", ko="시간 벌기", ja="時間 bought",
         note="拖时间等技能 CD", alias=["buy time", "buying time"]),
    dict(key="bait", zh="卖队友", en="bait", ko="먹기", ja=" Bait",
         note="卖队友（负面）", alias=["bait", "baiting", "bait him"]),
    dict(key="tilted", zh="心态崩了", en="tilted", ko=" meltdown", ja="准则Break",
         note="他心态崩了", alias=["tilted", "he's tilted", "he is tilted"]),
    dict(key="top frag", zh="杀得最多", en="top frag", ko="최다 처치", ja="トップフラグ",
         note="本局击杀最多", alias=["top frag", "top frags"]),
    dict(key="bottom frag", zh="杀得最少", en="bottom frag", ko="최소 처치", ja="ボトムフラグ",
         note="本局击杀最少", alias=["bottom frag", "bottom frags"]),
    dict(key="yolo", zh="拼一把", en="yolo", ko="요로", ja="ヨロ",
         note="残局冲出去找人杀（要输了鼓励队友）", alias=["yolo", "let's yolo"]),
    dict(key="winnable", zh="能赢", en="winnable", ko="이길 수 있어", ja="勝てる",
         note="鼓励队友：还能赢", alias=["winnable", "it's winnable", "we can win"]),
    dict(key="noob", zh="菜鸟", en="noob", ko="새비", ja="ヌーブ",
         note="菜；也可调侃", alias=["noob", "noobs"]),
    dict(key="stfu", zh="别叫了", en="stfu", ko="닥쳐", ja="Shut up",
         note="别吵了（粗口）", alias=["stfu", "shut up"]),
    dict(key="hax", zh="开挂", en="hax", ko="핵", ja="ハック",
         note="开挂（怀疑）", alias=["hax", "hax on", "cheater", "hacker"]),
    dict(key="fill", zh="补位", en="fill", ko="필", ja="フィル",
         note="补位（队友换位时）", alias=["fill", "filling"]),
    dict(key="boost", zh="拉枪线", en="boost", ko="부스트", ja="ブースト",
         note="双人架点", alias=["boost", "boosting"]),
    dict(key="smurf", zh="炸鱼", en="smurf", ko="스머프", ja="Smurf",
         note="小号打高分段", alias=["smurf", "smurfing"]),
    dict(key="acc", zh="买号", en="acc buyer", ko="계정 구매", ja="アカウント購入",
         note="买号代打", alias=["acc", "acc buyer", "bought account"]),
    dict(key="ff", zh="投降", en="forfeit", ko="포기", ja="降参",
         note="队友心态爆炸想投降", alias=["ff", "forfeit", "give up"]),
    dict(key="jett diff", zh="捷特差距", en="jett diff", ko="제트 차이", ja="ジェット差",
         note="捷风技能差距（调侃）", alias=["jett diff", "no jett diff"]),
    dict(key="xd", zh="笑死", en="xd", ko="ㅋㅋ", ja="XD",
         note="表情符，语气用", alias=["xd", "xD", "lul"]),
    dict(key="np", zh="没事", en="no problem", ko="괜찮아", ja="大丈夫",
         note="没关系", alias=["np", "no problem"]),
    dict(key="srry", zh="抱歉", en="sorry", ko="미안", ja="すみません",
         note="抱歉", alias=["srry", "sry", "sorry"]),
    dict(key="hf", zh="玩得开心", en="have fun", ko="즐거운 게임", ja="楽しげに",
         note="开局礼貌用语（GLHF 简写）", alias=["hf", "have fun"]),
    dict(key="throw", zh="开摆", en="throw", ko="포기하고", ja="Ellipsis",
         note="开摆/摆烂", alias=["throw", "throwing"]),
    dict(key="spike rush", zh="Spike Rush 模式", en="Spike Rush", ko="스파이크 러시", ja="スパイクラッシュ",
         note="5v5 快速模式", alias=[]),
    dict(key="deathmatch", zh="死斗", en="deathmatch", ko="데스매치", ja="デスマッチ",
         note="死斗模式", alias=["dm", "deathmatch"]),
    dict(key="ace", zh="五杀", en="ace", ko="에이스", ja="エース",
         note="单人团灭", alias=["5k", "ace"]),
    dict(key="clutch ace", zh="残局五杀", en="clutch ace", ko="클러치 에이스", ja="クラッチエース",
         note="1v5 全灭", alias=["1v5", "ace clutch"]),
    dict(key="first blood", zh="首杀", en="first blood", ko="퍼스트 블러드", ja="ファーストブラッド",
         note="等价于 entry frag（首杀）", alias=["fb", "first blood frag"]),
]

# ---------------------------------------------------------------------------
# 目标语言 → 术语表字段映射
# ---------------------------------------------------------------------------
FIELD_FOR_TARGET = {
    "zh": "zh", "en": "en", "ko": "ko", "ja": "ja",
}


def _norm(s: str) -> str:
    """归一化：小写 + 去掉标点，供关键词匹配。"""
    import re
    return re.sub(r"[^\w\s+']", " ", (s or "").lower())


def match_english_terms(text: str) -> list:
    """英文→中文方向：找出文本中命中的术语条目。

    只做**包含匹配**且命中长度 >= 3 字符的关键词，避免 "c"、"a" 这类
    单字母误匹配（map 名 "Abyss" 里的 a 之类）。
    """
    t = " " + _norm(text) + " "
    hits = []
    for e in TERMS:
        keys = [e["key"]] + [a for a in e.get("alias", [])]
        for k in keys:
            k = _norm(k)
            if len(k.strip()) < 3:
                continue
            if f" {k} " in t:
                hits.append(e)
                break
    return hits


def build_prompt_glossary(target_lang: str, limit: int = 40) -> str:
    """为目标语言生成术语提示（注入 LLM system prompt 用）。"""
    field = FIELD_FOR_TARGET.get(target_lang, "en")
    src_field = {v: k for k, v in FIELD_FOR_TARGET.items()}
    # 目标是中文时，源语言是队友（英文）；其余情况源语言是我们（中文）
    if target_lang == "zh":
        src_field = {"zh": "en"}     # 显示 en=zh 对照
    lines = []
    for e in TERMS:
        en = e.get("en", "")
        val = e.get(field, "")
        if not en or not val:
            continue
        lines.append(f"{en}={val}")
        if len(lines) >= limit:
            break
    return "；".join(lines)


def stats() -> dict:
    by_map = {}
    for e in TERMS:
        for key in ("market", "tree", "bathroom", "garage", "cubby", "a short", "truck",
                    "elbow", "hookah", "greenhouse", "c site", "kitchen", "heaven",
                    "ropes", "vault", "yacht", "waterfall", "duck", "wheel", "drop",
                    "pit", "art", "alley", "chef", "b main", "well", "apex", "shells",
                    "artillery", "boiler", "belt", "snow", "screen door", "rappel",
                    "cave", "golf", "sandbar", "ledge", "shrine", "bridge", "bunker",
                    "long doors", "door"):
            if key in e["key"] or key in str(e.get("alias", "")):
                by_map[key] = by_map.get(key, 0) + 1
                break
        else:
            by_map["通用/玩法/枪械"] = by_map.get("通用/玩法/枪械", 0) + 1
    return {"total": len(TERMS), "by_group": by_map}


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    print(f"术语库共 {len(TERMS)} 条")
    for g, n in sorted(stats()["by_group"].items(), key=lambda x: -x[1]):
        print(f"  {g:20} {n}")
    print("\n英文匹配测试：")
    for t in ["enemy rotating to B site", "I will flash for you",
              "my hair is down", "they're planting spike",
              "let's full buy and push mid", "he's lurking garage"]:
        hits = match_english_terms(t)
        print(f"  {t!r:36} → {[h['zh'] for h in hits]}")
    print("\n中译英提示词片段：")
    print("  " + build_prompt_glossary("en")[:200])
    print("\n韩译中提示词片段：")
    print("  " + build_prompt_glossary("zh")[:200])
