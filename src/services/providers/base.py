# -*- coding: utf-8 -*-
"""云服务 provider 抽象层：请求构造 + 响应解析。

★ 为什么要有这一层
------------------
0.2.x 的 `CloudASR._post()` 把 `/audio/transcriptions` 硬编码在方法里，
`Translator._chat()` 把 `/chat/completions` 和 `Bearer` 鉴权也写死了。
于是每加一家协议不同的服务商，就只能往方法体里塞 `if`：

    阿里千问  /chat/completions + base64 input_audio，术语走 system 消息
    小米 MiMo 同样形状，但**鉴权头是 api-key**，且**只允许 user 角色**
    腾讯 TMT  TC3 签名，完全另一套

塞三家之后就是「同一个调用四份实现」——这正是本项目吃过亏的模式
（`local_rules` 七张表同键不同译文、`looks_chinese` 与 `should_translate`
结论相反）。所以要在加第二家**之前**把接口立起来。

★ 分工：provider 只做「纯翻译」，不做网络
------------------------------------------
    provider：把 (音频, 选项) 变成 请求体，再把 响应体 变回 结果对象
    engine：  重试、超时递增、换模型兜底、缓存、口音纠错

这样切分的好处是 provider **不需要联网就能测** —— build/parse 都是纯函数，
单测喂一个假响应就能验解析，不用真的花钱调 API。

★ 一条被实测推翻的设计
----------------------
最初设想 `inject_terms` 是「各家方式不同」：prompt / system 消息 / 不支持。
2026-10-10 实测（8 个带真值样本）结论相反：

    阿里·无术语   均分 0.997  达标 8/8
    阿里·带术语   均分 0.966  达标 7/8   ← 粤语从 1.000 掉到 0.750
                    带术语后语种判定还从 yue 变成了 zh

1866 条术语塞进 system 上下文稀释了对语音本身的注意力。
所以 `terms_default` 必须**逐 provider 声明**，默认 False；
只有已实测有益的那条（硅基 transcriptions 的 prompt）才默认开。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ASRResult:
    """一次识别的结果。

    `language` / `emotion` 是**可选**信息：只有千问、小米这类
    会在 annotations 里回传的才有，其余 provider 留空。
    现在这些信息在旧实现里是直接丢掉的，接进来是白捡的。
    """

    text: str
    language: str = ""
    emotion: str = ""
    audio_seconds: float = 0.0


@dataclass
class ASRRequest:
    """构造好的请求，四选一填。

    `json_body` 与 `files`/`data` 互斥：
      · chat/completions 家族 → json_body
      · audio/transcriptions 家族 → files + data
    """

    url: str
    headers: dict = field(default_factory=dict)
    json_body: dict | None = None
    files: dict | None = None
    data: dict | None = None


class ASRProvider:
    """语音识别 provider 基类。

    子类只需实现 build() 和 parse()，两者都是纯函数。
    """

    # 预设名（与 ASR_PRESETS 的键对应）
    key: str = ""
    # 展示用：请求形状说明
    shape: str = ""
    # 是否接受显式语种。硅基实测**接受但不影响输出**（走自动检测），
    # 塞进去反而可能干扰，所以硅基那两个预设是 False。
    supports_language: bool = False
    # 是否支持注入游戏术语上下文
    supports_terms: bool = False
    # 是否**默认**注入。
    # ★ 这一项是实测定的，不是拍脑袋：阿里带术语反而掉分，所以默认关。
    terms_default: bool = False
    # 鉴权头。小米是 api-key，不是 Authorization: Bearer
    auth_header: str = "Authorization"
    auth_prefix: str = "Bearer "

    def auth_headers(self, key: str) -> dict:
        return {self.auth_header: self.auth_prefix + key}

    def build(self, *, base_url: str, key: str, model: str, wav: bytes,
              mime: str, language: str | None,
              terms: str | None) -> ASRRequest:
        raise NotImplementedError

    def parse(self, payload: dict) -> ASRResult:
        raise NotImplementedError


@dataclass
class MTResult:
    text: str
    raw: dict = field(default_factory=dict)


@dataclass
class MTRequest:
    url: str
    headers: dict = field(default_factory=dict)
    json_body: dict = field(default_factory=dict)


class MTProvider:
    """翻译 provider 基类（目前都是 OpenAI 兼容 /chat/completions）。"""

    key: str = ""
    shape: str = ""
    auth_header: str = "Authorization"
    auth_prefix: str = "Bearer "

    def auth_headers(self, key: str) -> dict:
        return {self.auth_header: self.auth_prefix + key}

    def build(self, *, base_url: str, key: str, model: str,
              messages: list, max_tokens: int = 160) -> MTRequest:
        raise NotImplementedError

    def parse(self, payload: dict) -> MTResult:
        raise NotImplementedError


# ---------------------------------------------------------------------------
# TTS
# ---------------------------------------------------------------------------
@dataclass
class TTSRequest:
    url: str
    headers: dict = field(default_factory=dict)
    json_body: dict = field(default_factory=dict)


class TTSProvider:
    """语音合成 provider 基类。

    与 ASR/MT 不同，TTS 的「响应」不是 JSON —— 有的是直接二进制，
    有的裹在 base64 字段里。所以 `parse()` 直接收 `httpx.Response`
    而不是 dict，由各自决定怎么取字节。

    分成两步（build / parse）而不是一个 `synthesize()`，
    是为了让「构造请求」这一步能离线测 —— 音色名怎么拼、
    语速怎么映射、鉴权头是什么，这些都不该靠真调 API 才验证得了。
    """

    key: str = ""
    shape: str = ""
    auth_header: str = "Authorization"
    auth_prefix: str = "Bearer "

    def auth_headers(self, key: str) -> dict:
        return {self.auth_header: self.auth_prefix + key}

    def build(self, *, base_url: str, key: str, model: str, text: str,
              voice: str, speed: float = 1.0,
              sample_rate: int = 44100) -> TTSRequest:
        raise NotImplementedError

    def parse(self, resp) -> bytes:
        raise NotImplementedError


# ---------------------------------------------------------------------------
# 游戏术语上下文
# ---------------------------------------------------------------------------
# 与 0.2.22 硬编码在 engine._post() 里的那段**逐字一致** ——
# 迁移必须行为等价，所以这里一个字都不能改。改了就等于换了识别行为，
# 而「迁移前后结果逐条比对」是验证迁移正确性的判据。
#
# 拼写错误「Saber」照抄：它是 0.2.22 就有的，写成正确拼写等于
# 悄悄改了识别输入。留着并在下方标注。
ASR_TERM_PROMPT = (
    "Valorant in-game voice comms. "
    "Frequent terms: Sage, Vandal, Phantom, Operator, Marshal, Sheriff, "
    "Ice Wall, wall, smoke, molly, flash, ult, spike, plant, defuse, "
    "site A, site B, site C, mid, main, heaven, hell, rotate, peek, "
    "trade, lurk, rush, retake, GG, GGWP, NT, nice try. "
    "Mixed Chinese/English/Japanese/Korean common. "
    "Prioritize correct game-specific terms."
)


def terms_for(provider: ASRProvider, terms: str | None) -> str | None:
    """决定这一次请求到底带不带术语。

    优先级：调用方显式给了就用调用方的；没给就用 provider 自己的默认值。
    这样既能让用户手动开/关，也不会破坏已验证的硅基行为
    （硅基 terms_default=True，等价于 0.2.22 的硬编码）。
    """
    if not provider.supports_terms:
        return None
    if terms is not None:
        return terms or None
    return ASR_TERM_PROMPT if provider.terms_default else None