# -*- coding: utf-8 -*-
"""场景就绪度检查：开会/通话 同传要满足哪些条件。

★ 为什么要单开一个模块，而不是把判断塞进 api.py
------------------------------------------------
api.py 是 WebView 桥接层，里面每个方法都要起窗口才测得到。
而这一段全是**纯判断**（配置对不对、声卡在不在、Key 有没有），
放在这里就能离线跑测试 —— 「检查逻辑对不对」和「界面点得动不对」
是两个独立的失败模式，混在一起就只能靠真点一遍才知道。

★ 场景差异到底在哪
------------------
打游戏：语音从**游戏进程**出来 -> 虚拟声卡 CABLE Input
开会  ：语音从**会议软件**出来 -> 会议软件里把麦克风选成 CABLE Output

所以同一根线（CABLE），两侧接的东西不一样。现有向导只讲了游戏那一侧，
用户拿它配会议时会漏掉「会议软件里要改麦克风」这一步 ——
而这一步**不做就完全没声音**，现象是「软件启动了但不出字」，
用户大概率会以为是软件坏了。

★ 检查项为什么是这六条
----------------------
每一条都对应一个「不满足时的现象」，不是凑数：

    cable      缺 -> 根本收不到对方声音（虚拟声卡缺失）
    asr_key    缺 -> 「ASR 未配置」抛错，字幕不出
    mt_key     缺 -> 同上，翻译链断
    capture    缺 -> 采集模式不是 cable/loopback，采的是麦克风（会把自己的声音翻出去）
    running    缺 -> 没点开始
    level      缺 -> 前面都对但电平一直为 0 -> 会议软件麦克风没改成 CABLE Output

最后一条是本模块存在的核心理由：前面五项都是**配置**，
只有它是**事实** —— 配置全对但电平为 0，说明线没接上，
而这是会议场景下最高频的失败原因。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable

_log = logging.getLogger("valtrans.scenario")


@dataclass
class Step:
    key: str
    title: str
    ok: bool
    detail: str = ""
    #: 这一条不满足时，用户要做的**具体动作**（可为空 = 无需操作）
    action: str = ""
    #: 动作由前端触发哪个 API（install_driver / 无）
    action_api: str = ""

    def as_dict(self) -> dict:
        return {"key": self.key, "title": self.title, "ok": self.ok,
                "detail": self.detail, "action": self.action,
                "action_api": self.action_api}


@dataclass
class Readiness:
    steps: list[Step] = field(default_factory=list)
    #: 汇总提示，前端顶部显示
    headline: str = ""
    ready: bool = False

    def as_dict(self) -> dict:
        return {"steps": [s.as_dict() for s in self.steps],
                "headline": self.headline, "ready": self.ready}


def meeting_readiness(cfg, *,
                      find_cable: Callable[[], object] | None = None,
                      running: bool = False,
                      level: int = 0) -> Readiness:
    """开会/通话场景的就绪度。

    参数刻意做成可注入（find_cable / running / level），
    这样测试不需要真装虚拟声卡、不需要真跑管线。

    `level` 是 0~100 的电平；传 -1 表示「还没开始监听，不知道」。
    """
    if find_cable is None:
        # ★ 模块名是 audio_capture，不是 audio。
        #   我第一版写成 `from .audio import ...`，而测试一直注入
        #   find_cable、从不走这条默认路径 —— 于是那个错模块名
        #   在 37 项测试里一次都没被触发，直到真机冒烟调
        #   meeting_readiness 才 ModuleNotFoundError。
        #   教训：**依赖可注入的代码要有一条不注入的冒烟路径**，
        #   否则测试全绿而生产必炸。
        from .audio_capture import find_cable_devices as find_cable  # type: ignore

    steps: list[Step] = []

    # ── 1. 虚拟声卡 ───────────────────────────────────────────
    try:
        _cin, cout = find_cable()
        has_cable = cout is not None
    except Exception as e:
        has_cable = False
        _log.warning("会议就绪检查：探测虚拟声卡失败 %r", e)
    steps.append(Step(
        "cable", "虚拟声卡（VB-CABLE）", has_cable,
        "已就绪，会议软件可以把麦克风指向它" if has_cable else
        "未检测到。会议场景必须装 —— 免驱动模式在会议里会把你自己"
        "的声音也采进去",
        "" if has_cable else "安装官方免费驱动（约 30 秒，会弹 UAC）",
        "" if has_cable else "install_driver",
    ))

    # ── 2. 采集模式 ───────────────────────────────────────────
    mode = getattr(cfg, "capture_mode", "")
    mode_ok = mode in ("cable", "loopback")
    steps.append(Step(
        "capture", "采集方式", mode_ok,
        {"cable": "虚拟声卡（推荐 · 只采对方声音）",
         "loopback": "免驱动（会混入电脑全部声音）"}.get(mode, f"当前：{mode or '未设置'}"),
        "" if mode_ok else "把采集方式改成「虚拟声卡」或「免驱动」",
    ))

    # ── 3. ASR Key ────────────────────────────────────────────
    try:
        asr_ok = bool(cfg.asr_key()) and bool(cfg.asr_endpoint()[0])
    except Exception:
        asr_ok = False
    steps.append(Step(
        "asr", "语音识别 Key", asr_ok,
        "已配置" if asr_ok else "未配置 —— 缺它会直接抛「ASR 未配置」，字幕不出",
        "" if asr_ok else "到「设置 → 识别」填一个服务商 Key（免费档即可）",
    ))

    # ── 4. 翻译 Key ───────────────────────────────────────────
    try:
        mt_ok = bool(cfg.mt_key()) and bool(cfg.mt_endpoint()[0])
    except Exception:
        mt_ok = False
    steps.append(Step(
        "mt", "翻译 Key", mt_ok,
        "已配置" if mt_ok else "未配置 —— 缺它翻译链会断",
        "" if mt_ok else "到「设置 → 翻译」填 Key",
    ))

    # ── 5. 管线 ───────────────────────────────────────────────
    steps.append(Step(
        "running", "翻译已启动", running,
        "正在运行" if running else "未启动",
        "" if running else "回主页点「开始翻译」",
    ))

    # ── 6. 电平（唯一一条「事实」而非「配置」）──────────────────
    #   level=-1 = 还没监听，不知道。这与「电平为 0」不是一回事，
    #   必须分开 —— 否则「还没开始」会被显示成「线没接上」。
    if level < 0:
        lv_ok, lv_detail = None, "未监听 —— 点「开始翻译」后自动检测"
        lv_action = "开始翻译后自动检测"
    elif level > 3:
        lv_ok, lv_detail = True, "已收到声音（电平 %d）" % level
        lv_action = ""
    else:
        lv_ok, lv_detail = False, (
            "电平一直是 0 —— 配置都对但没收到声音。"
            "最常见的原因：会议软件里的麦克风没改成 CABLE Output")
        lv_action = ("在会议软件的「音频设置」里，把麦克风从"
                     "你真实的麦克风改成 CABLE Output")
    steps.append(Step(
        "level", "声音真的进来了吗", bool(lv_ok), lv_detail or "",
        lv_action,
    ))

    blocking = [s for s in steps if not s.ok]
    ready = not blocking
    if ready:
        head = "全部就绪 —— 会议里对方说外语，会直接出中文字幕。"
    elif lv_ok is False and not [s for s in blocking if s.key != "level"]:
        head = "配置都对，但**没收到声音**。看最后一条。"
    else:
        head = "还差 %d 项：" % len(blocking)
    return Readiness(steps=steps, headline=head, ready=ready)


# ---------------------------------------------------------------------------
# 各家会议软件的位置
# ---------------------------------------------------------------------------
# 为什么要逐个列名字而不是笼统写「在设置里改麦克风」
# ------------------------------------------------------
# 笼统说法必然失败：用户看到「改麦克风」不知道去哪改。
# 每家的菜单文案差异很大，写出来才能照着点。
# 名称按 2026 年各客户端的实际菜单写的；不同版本文案可能有出入，
# 所以每条都给了「找不到时的通用找法」。
MEETING_APPS = [
    {"name": "Zoom", "path": "右下角「…」→ 音频 → 麦克风"},
    {"name": "腾讯会议", "path": "会前「设置」→ 音频 → 麦克风"},
    {"name": "Microsoft Teams", "path": "右上「…」→「设置」→「音频和视频」"},
    {"name": "Google Meet", "path": "点「…」→「设备设置」→「音频」"},
    {"name": "Discord", "path": "左下齿轮 → 语音和视频 → 输入设备"},
    {"name": "Slack", "path": "右上头像 → 设置 → 音频"},
]

CABLE_MIC_NAMES = ["CABLE Output", "CABLE-Output", "VB-Audio Virtual Cable",
                   "VB-Audio CABLE Output"]