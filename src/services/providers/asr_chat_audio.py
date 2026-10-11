# -*- coding: utf-8 -*-
"""ASR provider：`/chat/completions` + base64 `input_audio`。

覆盖：
    aliyun_qwen   阿里千问 qwen3-asr-flash（OpenAI 兼容端点）
    aliyun_ds     阿里千问 qwen3-asr-flash（DashScope 原生端点，唯一能带术语）
    xiaomi_mimo   小米 MiMo-V2.5-ASR

★ 三家形状一样，但有三处**必须分开**，否则一定会静默出错
-------------------------------------------------------
1. **鉴权头不同**
   阿里/腾讯走 `Authorization: Bearer`，小米走 `api-key: <key>`。
   写成一样 → 小米 401，而且错误信息只说「unauthorized」，看不出是头错了。

2. **能不能带术语，差别不是「方式不同」而是「能不能」**
   实测（2026-10-10）：
     · OpenAI 兼容端点 + system 消息 → **HTTP 400**
       `InternalError.Algo.InvalidParameter: The dedicated task 'asr'
        ... does not support this input`
     · DashScope 原生端点 + system 消息 → 正常
   也就是说**同一个模型，走兼容端点就丢掉了术语能力**。
   所以不能写成「兼容端点带 prompt 参数」——它会 400。

3. **小米只允许 user 角色**
   文档明确 messages 里的 role 可选值只有 `user`。
   塞 system → 被拒。术语这一条对它直接不存在。

★ 为什么术语对这一族默认关闭
--------------------------
实测 8 个带真值样本：
    阿里·无术语  均分 0.997  达标 8/8
    阿里·带术语  均分 0.966  达标 7/8
粤语样本带术语后语种判定从 yue 变 zh，繁体被打回简体，均分 1.000→0.750。
1866 条术语稀释了对语音本身的注意力。所以默认关，让用户按场景手动开。

★ 小米不接日韩这件事，实测比接口声明更糟
-------------------------------------
接口只声明 `asr_options.language` 没有 ja/ko；实测 `auto` 自动识别同样不行：
    ko  0.286  적이 미드에서 → 절기 비대에서
    ja  0.858  ラッシュ→拉致、ミッド→密土
所以小米 ASR 保留在代码里但**不进 ASR_PRESETS** —— 有代码但不给用户选，
比没有更危险（用户会以为可选）。
"""
from __future__ import annotations

import base64

from .base import ASRProvider, ASRRequest, ASRResult


def audio_data_url(wav: bytes, mime: str = "audio/wav") -> str:
    """base64 + data URL 前缀。

    `audio/wav` 与 `audio/mpeg` 两家都要求带 data URL 前缀而不是裸 base64。
    """
    return "data:%s;base64,%s" % (mime, base64.b64encode(wav).decode())


def _annotations(payload: dict) -> tuple[str, str]:
    """从响应的 annotations 里取 language / emotion。

    OpenAI 兼容形状下路径是
        choices[0].message.annotations[0]
    缺字段、类型不对、列表为空都要能扛住 —— 家家写法不一样，
    不能假设它一定在。
    """
    try:
        msg = payload["choices"][0]["message"]
    except (KeyError, IndexError, TypeError):
        return "", ""
    ann = msg.get("annotations") or []
    if not isinstance(ann, list) or not ann:
        return "", ""
    a = ann[0] if isinstance(ann[0], dict) else {}
    return (str(a.get("language") or ""), str(a.get("emotion") or ""))


def _audio_seconds(payload: dict) -> float:
    """取响应里的音频时长（秒）—— 算费用的唯一依据。

    两家文档都把它放在 `usage.seconds`：
        OpenAI 兼容  usage: {..., "seconds": 1, "prompt_tokens_details": {...}}
        DashScope 原生 usage: {..., "seconds": 1, "input_tokens_details": {...}}
    早期实测里还存在过 `prompt_tokens_details.seconds` 的写法，
    所以两处都读，谁有算谁。

    ★ 为什么必须真的取到
    ------------------
    ¥0.00022/秒是按音频时长计费的，取不到时长就没法给用户算成本，
    设置页的「这一局花了多少钱」就是空的 —— 等于把付费服务接进来
    却不让用户知道花了多少。（实测第一版漏了这个字段，
    audio_seconds 恒为 0，是迁移自证脚本的输出里发现的。）
    """
    usage = payload.get("usage") or {}
    if not isinstance(usage, dict):
        return 0.0
    for path in (("seconds",),
                 ("prompt_tokens_details", "seconds"),
                 ("input_tokens_details", "seconds")):
        cur: object = usage
        for k in path:
            if not isinstance(cur, dict):
                cur = None
                break
            cur = cur.get(k)
        if isinstance(cur, (int, float)):
            return float(cur)
    return 0.0


class ChatAudioASR(ASRProvider):
    """OpenAI 兼容形状：`/chat/completions` + input_audio。

    子类只需要覆盖 `key` 和（可选的）`auth_*` / `supports_terms`。
    """

    shape = "chat/completions · input_audio"
    supports_language = True        # asr_options.language
    supports_terms = False          # ★ 实测：加术语掉分，默认关
    terms_default = False

    #: asr_options.language 的取值；None 表示该家不支持这个字段
    # ★ 只列项目**已授权**的 5 种，不照抄服务商支持的 30 种。
    #   用户明确决定过不做 pt/es/ru（「玩的人很少，一般匹配不到，
    #   把与他们相关的全部删掉」）。千问支持 30 语种是**服务商能力**，
    #   不是本项目的承诺 —— 列出来等于对没有词库、没实测的语种做了承诺。
    #   tests/verify_src.py 的 ALLOWED_LANGS 守护会拦着。
    language_codes: tuple = ("zh", "yue", "en", "ja", "ko")

    def build(self, *, base_url: str, key: str, model: str, wav: bytes,
              mime: str, language: str | None,
              terms: str | None) -> ASRRequest:
        body = {
            "model": model,
            "messages": [{"role": "user", "content": [
                {"type": "input_audio",
                 "input_audio": {"data": audio_data_url(wav, mime)}}]}],
            "stream": False,
        }
        opts = {}
        if language and language in self.language_codes:
            opts["language"] = language
        if opts:
            body["asr_options"] = opts
        return ASRRequest(
            url=base_url.rstrip("/") + "/chat/completions",
            headers=self.auth_headers(key),
            json_body=body,
        )

    def parse(self, payload: dict) -> ASRResult:
        # ★ 防御式取值，不能用 payload["choices"][0]["message"]。
        #   自证里专门喂了 {"choices":[{}]} 这种残缺响应，
        #   直接下标会抛 KeyError —— 而这是**识别热路径**，
        #   一个畸形的响应就会把整条识别链炸掉，字幕直接不出。
        #   响应结构各家写法不一，这里只当「可能缺」处理。
        try:
            msg = payload["choices"][0]["message"]
        except (KeyError, IndexError, TypeError):
            return ASRResult(text="")
        if not isinstance(msg, dict):
            return ASRResult(text="")
        text = msg.get("content")
        # 形状差异：OpenAI 兼容下是字符串；DashScope 原生下是
        # [{"text": "..."}]。统一在这里抹平，别让上层各判一次。
        if isinstance(text, list):
            text = "".join(x.get("text", "") for x in text
                           if isinstance(x, dict))
        elif text is not None and not isinstance(text, str):
            text = str(text)
        lang, emo = _annotations(payload)
        return ASRResult(text=(text or "").strip(), language=lang,
                         emotion=emo, audio_seconds=_audio_seconds(payload))


class AliyunQwenASR(ChatAudioASR):
    """阿里千问 qwen3-asr-flash，走 OpenAI 兼容端点。

    base_url: https://dashscope.aliyuncs.com/compatible-mode/v1
    （有 WorkspaceId 时可换 {WorkspaceId}.cn-beijing.maas.aliyuncs.com，
      文档说旧域名仍可正常使用，新域名只是性能与稳定性更好）
    """

    key = "aliyun_qwen"
    shape = "chat/completions · 阿里千问（兼容端点·不能带术语）"
    supports_terms = False          # ★ 带 system 会被 400 拒，实测过


class XiaomiMiMoASR(ChatAudioASR):
    """小米 MiMo-V2.5-ASR。

    ★ 鉴权头是 `api-key:`，不是 `Authorization: Bearer`。
    ★ language 只有 auto/zh/en —— 传 ja/ko 会被忽略或出错，别传。
    ★ V2.5 系列 2026-10-21 下线，接入前要确认型号还有效。
    ★ 不进 ASR_PRESETS（原因见模块头），仅保留实现备用。
    """

    key = "xiaomi_mimo"
    shape = "chat/completions · 小米 MiMo（api-key 鉴权·无日韩）"
    auth_header = "api-key"
    auth_prefix = ""
    supports_language = True
    language_codes = ("auto", "zh", "en")
    supports_terms = False          # 只允许 user 角色，没有 system


class DashScopeASR(ASRProvider):
    """阿里千问走 DashScope 原生端点 —— **唯一能带术语的千问通路**。

    base_url: https://dashscope.aliyuncs.com/api/v1
    路径:     /services/aigc/multimodal-generation/generation

    与 OpenAI 兼容形状的差别：
        消息放在 `input.messages` 而不是顶层
        音频字段是 `{"audio": ...}` 而不是 `{"type":"input_audio",...}`
        asr_options 放在 `parameters` 里
    """

    key = "aliyun_dashscope"
    shape = "DashScope 原生 · 千问（唯一支持术语的通路）"
    supports_language = True
    supports_terms = True
    terms_default = False           # ★ 实测：带术语掉分，所以默认关但可开

    def build(self, *, base_url: str, key: str, model: str, wav: bytes,
              mime: str, language: str | None,
              terms: str | None) -> ASRRequest:
        msgs = []
        if terms:
            msgs.append({"role": "system", "content": terms})
        msgs.append({"role": "user", "content": [{"audio": audio_data_url(
            wav, mime)}]})
        params: dict = {"asr_options": {"enable_itn": False}}
        if language:
            params["asr_options"]["language"] = language
        return ASRRequest(
            url=base_url.rstrip("/") +
            "/services/aigc/multimodal-generation/generation",
            headers=self.auth_headers(key),
            json_body={"model": model, "input": {"messages": msgs},
                       "parameters": params},
        )

    def parse(self, payload: dict) -> ASRResult:
        msg = payload["output"]["choices"][0]["message"]
        c = msg.get("content")
        text = ("".join(x.get("text", "") for x in c if isinstance(x, dict))
                if isinstance(c, list) else c)
        lang, emo = "", ""
        ann = msg.get("annotations") or []
        if isinstance(ann, list) and ann and isinstance(ann[0], dict):
            lang = str(ann[0].get("language") or "")
            emo = str(ann[0].get("emotion") or "")
        return ASRResult(text=(text or "").strip(), language=lang,
                         emotion=emo, audio_seconds=_audio_seconds(payload))