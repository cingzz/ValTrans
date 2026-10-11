# -*- coding: utf-8 -*-
"""TTS provider。

★ 为什么 TTS 也要抽象层
----------------------
现有两条路：`/audio/speech`（硅基 CosyVoice2）与 edge-tts 本地链。
接小米要加第三条，而小米的形状与前两者都不同：
    · 端点是 `/v1/chat/completions`（不是 `/audio/speech`）
    · 鉴权头是 `api-key:`（不是 `Authorization: Bearer`）
    · 音频在 **choices[].message.audio.data**（base64），
      不是 HTTP 响应体直接是二进制

直接在 `tts.py` 里塞 `if` 的话，第三家一来就要改三处；
而且前两家的路径不会被真正验证到 —— 与 v0.2.10
`plan_voice` / `resolve_voice` 同名导致人设解析静默失效是同一类事故。

★ 返回什么
----------
`build()` 给出请求，`parse()` 把响应变成 **音频字节**。
不直接返回 bytes 是因为解码方式各家不同（body bytes vs base64 字段），
抹平在 provider 里，上层只认「bytes 或抛异常」。
"""
from __future__ import annotations

import base64
from dataclasses import dataclass, field
from typing import Type

from .base import TTSProvider, TTSRequest


class SpeechEndpointTTS(TTSProvider):
    """OpenAI 兼容 `/audio/speech`：响应体直接是音频。

    硅基流动 CosyVoice2 走这条。
    """

    key = "siliconflow_cosy"
    shape = "POST /audio/speech · 响应体即音频"

    def build(self, *, base_url: str, key: str, model: str, text: str,
              voice: str, speed: float = 1.0,
              sample_rate: int = 44100) -> TTSRequest:
        return TTSRequest(
            url=base_url.rstrip("/") + "/audio/speech",
            headers=self.auth_headers(key),
            json_body={"model": model, "input": text, "voice": voice,
                       "response_format": "mp3",
                       "sample_rate": sample_rate,
                       "speed": speed, "gain": 0},
        )

    def parse(self, resp) -> bytes:
        data = resp.content
        if not data:
            raise RuntimeError("TTS 返回空音频")
        return data


class ChatAudioTTS(TTSProvider):
    """`/chat/completions`，音频在 `message.audio.data`（base64）。

    小米 MiMo-TTS 走这条。

    ★ 反直觉的一点：待合成的文本放在 **assistant** 消息里
    --------------------------------------------------
    按常规直觉，文本应该放 `user` 消息。文档明确要求放在 `role: assistant`：
        "如果要生成音频，必须添加一条 role 为 assistant 的消息，
         该消息需指定用于音频合成的文本"

    照直觉写会把文本塞进 user，结果是模型把它当**指令**理解，
    而不是要念的内容 —— 返回的音频内容不对，而且不报任何错。

    ★ 没有 speed 参数
    -----------------
    语速控制只有 `voice`（选音色）与 `audio.format`。
    我第一版凭印象写了顶层 `speed`，文档里根本没有 —— 发了会被
    忽略或报错。语速只能靠换音色实现，滑杆对这一路不生效
    （tts.py 里对非硅基 provider 明确不走 speed 映射）。
    """

    key = "xiaomi_tts"
    shape = "chat/completions · 文本放 assistant 消息 · 音频在 audio.data"
    auth_header = "api-key"
    auth_prefix = ""

    #: 文档给出的预置音色。中文名的四个（冰糖/茉莉/苏打/白桦）是中文人设，
    #: 本项目主要念外语，所以默认走 Mia/Chloe/Milo/Dean 那组。
    VOICES = ("Mia", "Chloe", "Milo", "Dean", "mimo_default")

    def build(self, *, base_url: str, key: str, model: str, text: str,
              voice: str, speed: float = 1.0,
              sample_rate: int = 44100) -> TTSRequest:
        if voice not in self.VOICES:
            voice = "Mia"
        return TTSRequest(
            url=base_url.rstrip("/") + "/chat/completions",
            headers=self.auth_headers(key),
            json_body={
                "model": model,
                "messages": [{"role": "assistant", "content": text}],
                "audio": {"format": "mp3", "voice": voice},
                "stream": False,
            },
        )

    def parse(self, resp) -> bytes:
        j = resp.json()
        msg = ((j.get("choices") or [{}])[0] or {}).get("message") or {}
        audio = msg.get("audio")
        if not isinstance(audio, dict) or not audio.get("data"):
            raise RuntimeError("TTS 响应里没有音频数据")
        raw = audio["data"]
        if isinstance(raw, dict):
            raise RuntimeError("TTS 返回的是 URL 形状，未支持")
        try:
            out = base64.b64decode(raw)
        except Exception as e:
            raise RuntimeError("TTS 音频 base64 解码失败: %r" % e) from None
        if not out:
            raise RuntimeError("TTS 解码后是空音频")
        return out


TTS_PROVIDERS: dict[str, Type[TTSProvider]] = {
    "siliconflow_cosy": SpeechEndpointTTS,
    "xiaomi_tts": ChatAudioTTS,
}

_INSTANCES: dict[str, TTSProvider] = {}


def get_tts_provider(key: str) -> TTSProvider:
    cls = TTS_PROVIDERS.get(key)
    if cls is None:
        return SpeechEndpointTTS()
    if key not in _INSTANCES:
        _INSTANCES[key] = cls()
    return _INSTANCES[key]