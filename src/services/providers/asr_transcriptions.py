# -*- coding: utf-8 -*-
"""ASR provider：OpenAI 兼容 `/audio/transcriptions`。

覆盖：硅基流动（两个模型档）/ Groq / OpenAI / 自定义端点。

★ 这一族的行为必须与 0.2.22 逐字节一致
---------------------------------------
迁移前的 `CloudASR._post()` 是：

    url   = base_url + "/audio/transcriptions"
    data  = {"model": model, "response_format": "json"}
            + ("language" 仅在显式指定时)
            + {"prompt": <硬编码术语串>}
    files = {"file": ("audio.wav", wav, "audio/wav")}
    headers = {"Authorization": f"Bearer {key}"}
    resp → json["text"].strip()

这里**原样重建**，包括字段顺序无关但值必须相同、文件名固定 `audio.wav`
（某些服务端按扩展名判格式，改了会 415）。验证办法是拿真实样本
跑迁移前后各一次，比对识别文本逐字相同。

★ 术语注入在这一族是**默认开**的
------------------------------
它是 0.2.22 已上线并验证过的行为（vandal/phantom/operator 等英雄武器名
靠它才听对）。抽象层不能顺手「优化」掉它 —— 那是行为变更，不是重构。
chat_audio 那一族默认关，是另一回事（那边实测掉分）。
"""
from __future__ import annotations

from .base import ASRProvider, ASRRequest, ASRResult


class TranscriptionsASR(ASRProvider):
    """`POST {base_url}/audio/transcriptions`，multipart。"""

    shape = "multipart · /audio/transcriptions"
    supports_language = True
    supports_terms = True
    terms_default = True          # 与 0.2.22 等价

    def build(self, *, base_url: str, key: str, model: str, wav: bytes,
              mime: str, language: str | None,
              terms: str | None) -> ASRRequest:
        data = {"model": model, "response_format": "json"}
        if language:
            data["language"] = language
        if terms:
            data["prompt"] = terms
        return ASRRequest(
            url=base_url.rstrip("/") + "/audio/transcriptions",
            headers=self.auth_headers(key),
            data=data,
            # ★ 文件名固定 audio.wav：0.2.22 就是这么发的，
            #   改扩展名等于给服务端换了输入格式（有的会 415）。
            files={"file": ("audio.wav", wav, "audio/wav")},
        )

    def parse(self, payload: dict) -> ASRResult:
        return ASRResult(text=(payload.get("text") or "").strip())


