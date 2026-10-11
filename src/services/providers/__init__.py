# -*- coding: utf-8 -*-
"""provider 注册表：预设名 → provider 实现。

★ 这一层存在的意义：让「加一家服务商」变成加一行注册 + 一个类，
而不是改 engine 的方法体。0.2.x 每加一家就是往 `_post`/`_chat`
里塞 `if`，那正是本项目反复吃亏的形状。

★ 为什么要有 fallback 而不是直接 KeyError
---------------------------------------
`ValTrans-OpenSource` 的 `src` 是从工作目录**白名单拷贝**生成的，
少一个模块时整个 provider 子包会缺。
引擎在处理用户语音的关键路径上，一个 import 失败不该炸掉整个识别 ——
所以查不到就退回默认形状（transcriptions / chat），
退回时**如实打一条 warning**，不静默（AGENTS.md 铁律：
同一份数据散在多处 = 改对了也不生效）。
"""
from __future__ import annotations

import logging
from typing import Type

from .base import (ASRProvider, ASRResult, ASRRequest, ASR_TERM_PROMPT,
                   MTProvider, MTRequest, MTResult, terms_for)
from .asr_transcriptions import TranscriptionsASR
from .asr_chat_audio import (AliyunQwenASR, ChatAudioASR, DashScopeASR,
                             XiaomiMiMoASR, audio_data_url)
from .mt_chat import ApiKeyChatMT, ChatMT, TencentTokenHubMT
from .tts import (ChatAudioTTS, SpeechEndpointTTS, TTS_PROVIDERS,
                  get_tts_provider)

_log = logging.getLogger("valtrans.providers")

__all__ = [
    "ASRProvider", "ASRResult", "ASRRequest", "ASR_TERM_PROMPT",
    "MTProvider", "MTRequest", "MTResult", "terms_for",
    "TTSProvider", "TTSRequest",
    "TranscriptionsASR", "ChatAudioASR", "AliyunQwenASR", "DashScopeASR",
    "XiaomiMiMoASR", "audio_data_url",
    "ChatMT", "TencentTokenHubMT", "ApiKeyChatMT",
    "SpeechEndpointTTS", "ChatAudioTTS", "TTS_PROVIDERS", "get_tts_provider",
    "ASR_PROVIDERS", "MT_PROVIDERS",
    "get_asr_provider", "get_mt_provider", "describe_asr",
]

# ---------------------------------------------------------------------------
# 注册表
# ---------------------------------------------------------------------------
# 值是**类**不是实例：provider 全是无状态纯函数，用类省掉每次 new。
# key 必须与 src/core/config.py 里 ASR_PRESETS / MT_PRESETS 的键一致 ——
# 这一致性由 tests/verify_src.py 守护（两边不同步直接失败），
# 因为「预设表里有、注册表里没有」的表现是运行时才炸。
ASR_PROVIDERS: dict[str, Type[ASRProvider]] = {
    # —— 0.2.x 已有，形状不变 ——
    "siliconflow": TranscriptionsASR,
    "siliconflow_sensevoice": TranscriptionsASR,
    "groq": TranscriptionsASR,
    "openai": TranscriptionsASR,
    "custom": TranscriptionsASR,
    # —— 0.3.0 新增 ——
    "aliyun_qwen": AliyunQwenASR,          # 兼容端点，最省事
    "aliyun_dashscope": DashScopeASR,      # 原生端点，唯一能带术语
    # 小米 ASR **故意不注册**：实测 ko 0.286 / ja 0.858，
    # 且 V2.5 系列 2026-10-21 下线。代码留着备用，不给用户选。
}

MT_PROVIDERS: dict[str, Type[MTProvider]] = {
    "qwen": ChatMT,
    "siliconflow": ChatMT,
    "zhipu": ChatMT,
    # `custom` 不在 MT_PRESETS 表里，但 mt_endpoint() 确实处理
    # mt_preset == "custom"（读 custom_mt_url/custom_mt_model）——
    # 也就是说它是**代码可达但 UI 不暴露**的值（前端下拉框遍历
    # MT_PRESETS，见 src/uiweb/api.py；v0.3.0 起前端只剩这一处，
    # 原来还并列提到的 src/ui/pages.py 是已删的 Qt 界面）。
    # 注册表覆盖它是防御，不是在表里凭空多出一个选项。
    "custom": ChatMT,
    "tencent_hunyuan": TencentTokenHubMT,
    # ★ 没有 `xiaomi`：小米没做翻译服务，注册了也没有任何配置能选到它。
    #   「注册了但不可达」比「不注册」更糟 —— 它会让
    #   「注册表 ⊇ 预设表」这条不变量的检查失去意义。
}

_INSTANCES: dict[tuple[str, str], object] = {}


def get_asr_provider(key: str) -> ASRProvider:
    """取 provider 实例。查不到退回 transcriptions 形状。"""
    cls = ASR_PROVIDERS.get(key)
    if cls is None:
        base = ASR_PROVIDERS.get("custom")
        if base is None:      # 连默认形状都没了 = 模块不全
            return TranscriptionsASR()
        _log.warning("provider: 未知 ASR 预设 %r，退回默认形状", key)
        return base()
    k = ("asr", key)
    if k not in _INSTANCES:
        _INSTANCES[k] = cls()
    return _INSTANCES[k]      # type: ignore[return-value]


def get_mt_provider(key: str) -> MTProvider:
    cls = MT_PROVIDERS.get(key)
    if cls is None:
        base = MT_PROVIDERS.get("custom")
        if base is None:
            return ChatMT()
        _log.warning("provider: 未知 MT 预设 %r，退回默认形状", key)
        return base()
    k = ("mt", key)
    if k not in _INSTANCES:
        _INSTANCES[k] = cls()
    return _INSTANCES[k]      # type: ignore[return-value]


def describe_asr() -> list[dict]:
    """给设置页用：每个 ASR 预设的形状与能力，供 UI 显示与禁用。"""
    out = []
    for k, cls in ASR_PROVIDERS.items():
        inst = cls()
        out.append({
            "preset": k,
            "shape": inst.shape,
            "supports_language": inst.supports_language,
            "supports_terms": inst.supports_terms,
            "terms_default": inst.terms_default,
        })
    return out