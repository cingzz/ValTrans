# -*- coding: utf-8 -*-
"""翻译 provider：OpenAI 兼容 `/chat/completions`。

覆盖：硅基流动（Qwen2.5-14B / Hunyuan-MT-7B）/ 智谱 GLM-4-Flash /
      腾讯混元（TokenHub）/ 自定义端点。

★ 为什么 MT 这一层看起来「多余」
-------------------------------
现有三家全是 OpenAI 兼容的 `/chat/completions`，形状确实一样。
但照样单独建这一层，理由是**要接的第 4 家不是这个形状**：
腾讯 TokenHub 兼容 OpenAI 协议，但腾讯云另一套产品线（机器翻译 TMT）
是 TC3-HMAC-SHA256 签名，鉴权头、body 结构、签名时机三样都不一样。

把接口现在立好，等真要接 TMT 时是「新增一个 provider」而不是
「往 _chat 里塞 if」—— 这正是 v0.2.10 踩过的坑（plan_voice 与
resolve_voice 同名导致人设解析静默失效）的提前预防。

★ 行为必须与迁移前一致
----------------------
迁移前 `Translator._chat()`：
    url    = base_url + "/chat/completions"
    json   = {"model", "messages", "temperature": 0.0,
              "max_tokens": max_tokens, "stream": False}
    header = {"Authorization": f"Bearer {key}"}
    resp   → json["choices"][0]["message"]["content"].strip()

字段一个不少、一个不多不多，值必须相同。`temperature: 0.0` 是
「不要发挥」的关键，去掉它等于换了翻译行为。
"""
from __future__ import annotations

from .base import MTProvider, MTRequest, MTResult


class ChatMT(MTProvider):
    """OpenAI 兼容 `/chat/completions`。"""

    shape = "chat/completions · OpenAI 兼容"

    def build(self, *, base_url: str, key: str, model: str,
              messages: list, max_tokens: int = 160) -> MTRequest:
        return MTRequest(
            url=base_url.rstrip("/") + "/chat/completions",
            headers=self.auth_headers(key),
            json_body={
                "model": model,
                "messages": messages,
                # ★ temperature 0.0 不是可有可无：实时字幕要的是
                #   确定性翻译，不要模型「发挥」。去掉它等于换行为。
                "temperature": 0.0,
                "max_tokens": max_tokens,
                "stream": False,
            },
        )

    def parse(self, payload: dict) -> MTResult:
        return MTResult(
            text=(payload["choices"][0]["message"]["content"] or "").strip(),
            raw=payload,
        )


class TencentTokenHubMT(ChatMT):
    """腾讯混元翻译（TokenHub 兼容接口）。

    鉴权与三家 OpenAI 兼容家一致（`Authorization: Bearer`），
    之所以单列一个类，是为了让 `key = "tencent_hunyuan"` 在注册表里
    是**显式存在**的，而不是「靠 base_url 猜」——
    用户填错 Key 的时候，排查方向一眼能看出来。

    ★ 待确认（2026-10-10）：腾讯的 Key 格式资料上有两种说法，
      一处说用 TokenHub 专用 API Key，另一处说 `{secret_id}:{secret_key}`。
      实现时照控制台实际给的来，别照博客。旧混元平台已于
      2026-09-30 全面停服下线，只能走 TokenHub。
    """

    key = "tencent_hunyuan"
    shape = "chat/completions · 腾讯混元（TokenHub 兼容接口）"


class ApiKeyChatMT(ChatMT):
    """`api-key:` 鉴权的 OpenAI 兼容端点。

    目前没有已实测的 MT 服务商用这种形状（小米只有 ASR/TTS），
    保留是因为 TTS 那边要用同一套鉴权切换，别到时候再写一遍。
    """

    key = "api_key_mt"
    auth_header = "api-key"
    auth_prefix = ""