# -*- coding: utf-8 -*-
# 作者: cing  ·  https://github.com/cingzz
# 许可: GPL-3.0 + 商业授权（闭源/商用需向作者申请授权），见 LICENSE 与 LICENSE-COMMERCIAL.md
#
"""云端语音识别（OpenAI 兼容 /audio/transcriptions）与翻译（/chat/completions）。

- ASR 预设链：主预设失败自动降级（siliconflow -> zhipu 不适用 ASR；ASR 降级顺序可配置）
- 翻译：Hunyuan-MT-7B 官方模板 -> 失败降级 GLM-4-Flash（带游戏术语表）
- 相同文本缓存；带延迟统计。
"""
from __future__ import annotations

import hashlib
import io
import logging
import re
import time
import wave
from typing import Callable

import httpx
import numpy as np

from ..core.security import safe_client, pooled_client
from ..core.config import AppConfig, ASR_PRESETS, MT_PRESETS
from .game_terms import match_english_terms, build_prompt_glossary
from .local_rules import translate_local
from .cjk_slang import translate_cjk, detect_lang, scrub_residual_cjk
from . import tm
from . import cross_check
from . import post_edit
from .agents import translate_fixed
from . import learning
from . import accent
from .translate_gate import should_translate, looks_chinese
from .zh_to_en import translate_zh_to_en
from .translation_clean import clean_translation, STRICT_RULES_ZH

# 游戏术语表（注入 LLM 兜底翻译；Hunyuan-MT 用官方极简模板，不注入）
GLOSSARY = {
    "rotate": "转点", "rotating": "转点", "rush": "冲", "plant": "下包",
    "defuse": "拆包", "spike": "包", "site": "点位", "A site": "A点", "B site": "B点",
    "flash": "闪光", "smoke": "烟", "molly": "燃烧弹", "ult": "大招",
    "echo": "回声", "recon": "侦察", "trade": "换血", "peek": "拉枪线",
    "one tap": "一枪爆头", "clutch": "残局", "eco": "经济局", "full buy": "起全枪",
    "push": "进攻推进", "hold": "架住", "flank": "绕后", "entry": "首杀突破",
}

_HUNYUAN_TARGET = {"zh": "中文", "en": "英语", "ja": "日语", "ko": "韩语",
                   }


def float32_to_wav_bytes(pcm: np.ndarray, sr: int = 16000) -> bytes:
    buf = io.BytesIO()
    w = wave.open(buf, "wb")
    w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
    w.writeframes((np.clip(pcm, -1, 1) * 32767).astype(np.int16).tobytes())
    w.close()
    return buf.getvalue()


def _apply_glossary(text: str, target: str = "zh") -> str:
    """按翻译方向生成术语提示。

    - target=zh：英文→中文，取文本里命中的游戏术语（队友说英文时用）
    - 其他语言：中→外语，给出「中文=外语」对照作为提示词
    """
    if target == "zh":
        hits = match_english_terms(text)
        out = []
        for e in hits[:14]:
            note = f"（{e['note']}）" if e.get("note") and len(e["note"]) < 40 else ""
            out.append(f"{e['en']}={e['zh']}{note}")
        return "；".join(out)
    gl = build_prompt_glossary(target, limit=60)
    low = (text or "").lower()
    extra = []
    for en, zh in GLOSSARY.items():
        if en in low:
            extra.append(f"{zh}={en}")
    if extra:
        gl = gl + "；" + "；".join(extra[:10])
    return gl


class CloudASR:
    """OpenAI 兼容语音转文字，带降级与缓存。"""

    def __init__(self, cfg: AppConfig):
        self.cfg = cfg
        self.cache: dict[tuple[str, str], str] = {}
        self.last_latency = 0.0
        self.used_fallback = False

    def _post(self, base_url: str, key: str, model: str, wav: bytes,
              language: str | None, timeout: float = 25.0) -> str:
        url = base_url.rstrip("/") + "/audio/transcriptions"
        data = {"model": model, "response_format": "json"}
        if language:
            data["language"] = language
        # ASR 域提示（prompt/hotwords）：提升游戏术语识别准确度，尤其是有口音时。
        #
        # ★ v0.2.22：删掉了原来包着它的 `try/except Exception: pass`。
        #   那层防护是**纯冗余**——它包的是一段字符串字面量拼接，
        #   赋值给 dict 键，**不可能抛任何异常**（连 MemoryError 都不算
        #   可捕获的正常路径）。留着它的代价是：
        #     · 被 audit_silent_except 棘轮判为「无理由的静默吞异常」
        #       （engine.py 因此从基线 3 处涨到 4 处，闸门判红）
        #     · 让读代码的人以为「构造 prompt 这步可能会失败」，
        #       进而不敢在这里加真正的逻辑
        #   真正会失败的是下面 client.post()，那里已经有多级重试。
        data["prompt"] = (
            "Valorant in-game voice comms. "
            "Frequent terms: Sage, Vandal, Phantom, Operator, Marshal, Sheriff, "
            "Ice Wall, wall, smoke, molly, flash, ult, spike, plant, defuse, "
            "site A, site B, site C, mid, main, heaven, hell, rotate, peek, "
            "trade, lurk, rush, retake, GG, GGWP, NT, nice try. "
            "Mixed Chinese/English/Japanese/Korean common. "
            "Prioritize correct game-specific terms."
        )
        files = {"file": ("audio.wav", wav, "audio/wav")}
        # ★ v0.2.16：禁止 `with pooled_client(...)`！httpx.Client.__exit__
        #   会把**缓存里的共享客户端** close 掉，下一句字幕又得重付
        #   DNS+TCP+TLS（本模块注释量过：冷 11982ms vs 复用 691ms）——
        #   池化等于没生效。客户端由连接池统一持有，退出时 close_pool() 统一关。
        #   timeout 走**每请求**覆盖（httpx 支持传给 post），这样 ASR 的
        #   8s/22s 档和 MT 的 25s 档能共用同一个池化客户端。
        client = pooled_client(timeout=30.0)
        r = client.post(url, headers={"Authorization": f"Bearer {key}"},
                        data=data, files=files, timeout=timeout)
        r.raise_for_status()
        j = r.json()
        return (j.get("text") or "").strip()

    # ★ v0.2.13：ASR 的「快失败 + 升级重试」节奏
    #
    # 实测（2026-10-04，用户实测「翻译巨慢」）：
    #     同一段 4.27 秒音频，硅基 SenseVoiceSmall
    #         会话早些时候：452ms
    #         同一时刻连打 4 次：8351 / 10615 / 19041 / 22986ms（中位 19s）
    #     两条链路（队友字幕 / PTT）共用这一个 ASR，
    #     所以它是**唯一同时拖慢两个方向的单点**。
    #
    # 超时怎么定（这里我改过一次，第二次才对）
    # ----------------------------------------
    # 第一版我写成「5.5s 快失败 + 9s 重试」，理由是别让用户干等 25s。
    # 实测立刻打脸：接口拥堵到 19s 时，**5.5s 会把本来能成功的请求掐掉**，
    # 于是字幕直接丢失 —— 用户视角是「等半天什么都没有」，比慢更糟。
    #
    # 所以正确的方向是**超时递增**而不是**收紧**：
    #     第一次 8s  —— 正常时期（实测 452ms~2.1s）秒回，不受影响；
    #                   拥堵时期第一次就掐掉，不浪费 20 秒。
    #     第二次 22s —— 覆盖实测最差 23s（留一点余量），宁可慢也别丢字幕。
    # 最坏 30s 出结果；旧代码是 25s **然后什么都没有**。
    _ATTEMPTS = (8.0, 22.0)

    # 换模型兜底（不是换 Key）：同一把硅基 Key 下实测可用两个 ASR 模型。
    _FALLBACK_MODEL = "FunAudioLLM/SenseVoiceSmall"

    def transcribe(self, pcm: np.ndarray, sr: int = 16000,
                   language: str | None = None) -> tuple[str, str]:
        """返回 (text, lang_hint)。language 显式指定时优先生效。"""
        wav = float32_to_wav_bytes(pcm, sr)
        # 缓存键用内容摘要而非 hash()：内置 str hash 每进程随机加盐，
        # 跨进程不一致，且理论上存在碰撞导致「A 的音频返回 B 的文本」的风险。
        cache_key = hashlib.blake2b(wav, digest_size=16).hexdigest()
        if cache_key in self.cache:
            return self.cache[cache_key], ""

        base_url, model, langs, auto = self.cfg.asr_endpoint()
        key = self.cfg.asr_key()
        if not base_url or not key:
            raise RuntimeError("ASR 未配置：请先在设置中填写 API Key")
        if language is None:
            language = None if auto else (self.cfg.lock_source_lang or None)

        _log = logging.getLogger("valtrans.engine")
        t0 = time.perf_counter()
        text = None
        last_exc = None
        permanent = False
        # 计划 = [(超时, 模型)]：先用主模型递增超时，全挂再换旧模型兜底。
        # 换模型而不是换 Key：用户只有硅基一把 Key，而它同时挂着两个 ASR 模型
        # （实测 Qwen3-ASR-1.7B 快 10.8 倍，旧默认 SenseVoice 留着当保险）。
        # —— 第 1 段：主模型，超时递增重试（最多 len(_ATTEMPTS) 次）——
        for i, to in enumerate(self._ATTEMPTS):
            try:
                text = self._post(base_url, key, model, wav, language, timeout=to)
                dt = time.perf_counter() - t0
                if i and _log.isEnabledFor(logging.INFO):
                    _log.info("ASR 重试第 %d 次才成功，累计 %.2fs", i + 1, dt)
                break
            except Exception as e:
                last_exc = e
                _log.warning("ASR 重试第 %d 次失败(%.1fs 超时上限)：%s",
                             i + 1, to, type(e).__name__)
                # ★ v0.2.16：401/413/422 这类 4xx 重试也不会好，直接失败，
                #   别把单 worker 队列堵 52 秒
                if self._is_permanent(e):
                    permanent = True
                    break
        # —— 第 2 段：换**模型**兜底（不是换 Key）——
        # 用户只有硅基一把 Key，而它同时挂着两个 ASR 模型：
        # 实测 Qwen3-ASR-1.7B 快 10.8 倍，SenseVoice 更准一点但慢 10 倍，
        # 留作保险。这一段固定只发 1 次请求。
        # 4xx 换模型也没用（同一把 Key、同一份音频），跳过。
        if (text is None and not permanent
                and self._FALLBACK_MODEL and self._FALLBACK_MODEL != model):
            try:
                _fb = self._FALLBACK_MODEL.split("/")[-1]
                _log.warning("主 ASR 模型全挂，换 %s 重试一次", _fb)
                text = self._post(base_url, key, self._FALLBACK_MODEL, wav,
                                  language, timeout=self._ATTEMPTS[-1])
            except Exception as e:
                last_exc = e
        self.last_latency = time.perf_counter() - t0
        if text is None:
            raise RuntimeError(
                "ASR 识别失败（主模型重试 %d 次 + 换模型 1 次）：%s"
                % (len(self._ATTEMPTS), last_exc))
        text = text.strip()

        # ------------------------------------------------------------------
        # v0.2.10 口音纠错：ASR 认错了词，后面所有翻译层都白搭。
        #   love  -> low        元音被吃掉
        #   spik  -> spike      词尾脱落
        #   theay -> they       元音混淆
        # 实测 6/6 纠正、0/13 误伤（tests/audit_accent.py）。
        # 接在缓存【写入之前】，保证缓存里存的也是纠好的文本。
        # ------------------------------------------------------------------
        if text:
            text = self._fix_accent(text)

        # ★ v0.2.17：中文黑话谐音纠错（妈妈->奶妈 / 上播了->尚勃勒 /
        #   单播->单摸）。与英文口音纠错同一位置：缓存写入之前，
        #   保证缓存里存的也是纠好的文本。
        if text:
            from .zh_accent import fix_zh_slang
            text = fix_zh_slang(text)

        # ★ v0.2.21：中文游戏词同音/形近误听纠错（真机 实测：
        #   说「别玩你的冥狙了」-> 屏上「别往你的民居了」）。
        #   两个错：①「冥狙」被听成「民居」②音近「玩」->「往」。
        #
        #   为什么修在**这里**（ASR 输出后、翻译前）：
        #     · 修在翻译之后 = 拿译文猜原文，会误伤且错两次
        #     · 修在云端 prompt 里 = 换模型/改 prompt 是死路（本项目实测过）
        #     · 这里修 = 输入还是那句话，只是把明显错字归一，
        #       后面的本地表 / 云端拿到的都是对的词 —— 一处修，全链受益
        #   同样接在缓存**写入之前**，保证缓存里存的也是纠好的文本。
        if text:
            from .zh_asr_fix import fix_asr_zh
            text = fix_asr_zh(text)

        # ★ v0.2.22：ASR 噪音过滤（真机 实测：队友喊「AAA」，
        #   识别成 `eeee`，云端 MT 直接报错「文本太短，只有字母 E」）。
        #
        #   为什么修在这里：噪片段**不该进缓存也不该发云端**。
        #   云端对纯字母残片会抛 400，用户看到的是一句看不懂的报错，
        #   而正确行为是「这一段没听清，什么都不显示」。
        #
        #   ★ 必须放行 A/B/C 重复（宁缺毋滥的反面：这次宁滥也不能杀）：
        #   「AAA / AAAA / BBB / CCC」是**真实的集合报点**，不是噪音。
        #   一刀切「同字符 >=3 就丢」会把正常报点吃掉 —— 这正是
        #   原则「误伤 > 漏修」在此处的具体形态。
        #   判据只杀「同字符重复且不是 A/B/C」。
        if text:
            t2 = text.strip()
            if t2:
                low2 = t2.lower()
                if len(set(low2)) == 1 and len(t2) >= 3 and low2[0] not in "abc":
                    # 全是同一个字符（eeee/aaaa/oooo…）且不含中文 -> 识别残片
                    text = ""
                else:
                    import re as _re_noise
                    _has_cjk = bool(_re_noise.search(
                        r"[\u4e00-\u9fff\uf900-\ufaff]", t2))
                    if not _has_cjk:
                        # 无中文时，纯字母残片（长度 1~2，如 "e"、"ab"）也丢；
                        # 但含数字或 >=3 个字母的短词保留（可能是 "A1"、"mid"）
                        _alpha = [c for c in t2 if c.isalpha()]
                        if 0 < len(_alpha) <= 2 and not any(
                                c.isdigit() for c in t2):
                            text = ""

        if text:
            self.cache[cache_key] = text
            if len(self.cache) > 256:
                self.cache.pop(next(iter(self.cache)))
        return text, ""

    @staticmethod
    def _fix_accent(text: str) -> str:
        """口音误识纠正。整句匹配优先（更保守），词级兜底。"""
        try:
            # 通道 0（v0.2.11）：超短词显式映射——ASR 常把 ULT 听成 os/ox，
            # 2 字母词进不了音形匹配，必须在最前面硬替换。
            text = re.subn(r"\b(os|ox)\b", "ult", text, flags=re.I)[0]
            # 通道 2：整句模糊匹配 —— 够像就换成标准写法。
            # 比逐词猜保守得多，先试它。
            whole = accent.match_phrase(text)
            if whole:
                return whole
            # 通道 1：词级音形纠错（两道闸门：上下文 + 非英语词）
            fixed, n = accent.correct_accent(text)
            return fixed if n else text
        except Exception as e:
            # 纠错是增强功能，绝不能把识别结果搞挂
            import logging
            logging.getLogger("valtrans.engine").warning(
                "口音纠错异常，原文透传：%r", e)
            return text


_CJS = re.compile(r"[\u4e00-\u9fff]")
_LATIN = re.compile(r"[A-Za-z]")
# 这些是**本来就该保持外文**的（社区直接这么说），不算翻译失败
_LATIN_OK = re.compile(
    r"^(?:gg+wp|gg|wp|gg ez|ace|nb|oj|ow|nice try"
    r"|odin|viper|neon|breach|raze|reyna|kj"
    r"|[0-9]+v[0-9]+|\d+\s*打\s*\d+|[a-z])$", re.I)


def _mixed_output(out: str, target: str) -> bool:
    """名词替换的半成品检测（v0.2.17）：目标语言的句子里残留源语言 = 没翻完。"""
    s = out or ""
    if target == "zh":
        # 残留 2+ 连续英文字母（A/B/C 点位、GG、数字放行）
        return bool(re.search(r"[A-Za-z]{2,}", s))
    return bool(_CJS.search(s))   # 目标非中文却残留汉字


def _looks_untranslated(out: str) -> bool:
    """译文是否「根本没翻成中文」。

    真机实测的失败形态（tests/eval_tm.py）：
        'they dropped the 控场 on s'   cjk=2  latin=22  -> 判失败
    正常形态：
        '我在这架枪。'                 cjk=5  latin=0   -> 判正常
        'GGWP' / '1v3' / 'Odin'        社区本来就这么说  -> 放行
    """
    s = (out or "").strip()
    if not s:
        return True                       # 空 = 失败
    if _LATIN_OK.fullmatch(s.replace(" ", "")):
        return False                      # 社区惯用外文，放行
    cjk = len(_CJS.findall(s))
    latin = len(_LATIN.findall(s))
    if latin == 0:
        return False                      # 纯中文，正常
    # 汉字数至少要压得住拉丁字母数的 40%
    return cjk < max(1, latin * 0.4)


class Translator:
    """Hunyuan-MT-7B 优先（官方模板），失败降级 GLM-4-Flash + 术语表。"""

    def __init__(self, cfg: AppConfig):
        self.cfg = cfg
        self.cache: dict[tuple[str, str], str] = {}
        self.last_latency = 0.0
        self.used_fallback = False
        # v0.2.6 统计：本地/云端命中数（设置页「本地占比」卡片用）
        self.stats_local = 0
        self.stats_cloud = 0
        # 照抄（原文已是中文，原样返回，不进翻译链）
        self.stats_passthrough = 0
        self.src_passthrough = False
        self.src_user = False       # 本次译文是否来自用户自建词库
        self.used_local = False     # 本次是否本地命中（对外兼容字段）

    def _chat(self, base_url: str, key: str, model: str, messages: list,
              timeout: float = 25.0, max_tokens: int = 160) -> str:
        url = base_url.rstrip("/") + "/chat/completions"
        # ★ v0.2.13：512 -> 160。
        #   实时语音字幕的译文几乎都 <60 字，512 只是
        #   给模型留的解码预算；留得越大，最坏情况下的
        #   解码耗时越长。实测本项目译文均值 694ms，
        #   这里给 160 足够（含日韩假名/谚文也够），
        #   而异常输出（模型开始解释）会被后半段截断 ——
        #   而那本来就是要被 clean_translation 砍掉的。
        # ★ v0.2.16：同 _post —— 池化客户端用完**不关**（with 会把它
        #   close 掉，池化失效）；timeout 每请求覆盖，与 ASR 共用一个池。
        client = pooled_client(timeout=30.0)
        r = client.post(url, headers={"Authorization": f"Bearer {key}"},
                        json={"model": model, "messages": messages,
                              "temperature": 0.0,
                              "max_tokens": max_tokens, "stream": False},
                        timeout=timeout)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip()

    def warmup(self) -> bool:
        """极短请求把连接池建起来（v0.2.16 挪到 Translator：谁持有谁预热）。

        冷连接 5-12 秒，正好落在用户点「开始翻译」后的第一句字幕上，
        体感是「按了没反应」。这里预热一次：建连 + 打通鉴权，
        后续每句只付模型推理时间。

        ★ 此前 api._warmup_worker 调的是**不存在的** self._chat
        （Api 类没有这个方法），AttributeError 被吞 —— 预热从未生效过。
        """
        try:
            base_url, model = self.cfg.mt_endpoint()
            key = self.cfg.mt_key()
            if not base_url or not key:
                return False
            self._chat(base_url, key, model,
                       [{"role": "user", "content": "ok"}],
                       timeout=15.0, max_tokens=1)
            return True
        except Exception:
            return False

    @staticmethod
    def _is_permanent(e: Exception) -> bool:
        """4xx（除 408/429）= 重试也不会好的错：Key 无效(401)、音频超大(413)、
        参数错(422)。对它们重试只会白烧 8+22+22 秒，还把单 worker 队列堵死。"""
        if isinstance(e, httpx.HTTPStatusError):
            code = e.response.status_code
            return 400 <= code < 500 and code not in (408, 429)
        return False

    def usage_stats(self) -> dict:
        """翻译用量统计（设置页「本地占比」卡片用）。

        本地命中 = 0 成本，本地占比直接等于省下的钱。
        """
        loc = int(getattr(self, "stats_local", 0))
        clo = int(getattr(self, "stats_cloud", 0))
        tot = loc + clo
        learn = {}
        # 可以静默：这里只是**用量统计**的附带项，learning 模块挂了
        # 不该让出字失败 —— 降级成空统计，下一次采样自然就补回来了。
        try:
            learn = learning.stats()
        except Exception:
            pass
        pas = int(getattr(self, "stats_passthrough", 0))
        tot_all = tot + pas
        # ★ v0.2.16：这里曾有**重复键** local_ratio（字面量里写了两遍），
        #   后值悄悄覆盖前值，且分母口径与 total 对不上。保留「含照抄」口径：
        #   本地命中与中文照抄都 0 成本，占比=省下的钱。
        return {
            "local_hits": loc,
            "cloud_hits": clo,
            "passthrough": pas,
            "total": tot_all,
            "local_ratio": (loc / tot_all) if tot_all else 0.0,
            "passthrough_ratio": (pas / tot_all) if tot_all else 0.0,
            "learning": learn,
        }

    def reset_usage_stats(self) -> dict:
        self.stats_local = 0
        self.stats_cloud = 0
        self.stats_passthrough = 0
        return self.usage_stats()


    def translate(self, text: str, target: str = "zh") -> str:
        """三层翻译：本地规则 -> 云端 -> 清洗。

        为什么分层
        ----------
        实测通用翻译模型的三个硬伤：
          1. 直译游戏黑话：说「我的发」-> "my hair"（实际是 wtf 的谐音）
          2. 输出解释而非译文：「可以理解为...所以这句话可能表示...」
          3. 慢：注入术语表让 prompt 翻倍，延迟与 token 一起翻倍

        所以：能在本地正则里解决的，绝不送网络。
        """
        t0 = time.perf_counter()

        # 【铁律 v0.2.10】目标语言是中文、而原文已经是中文 -> 原样照抄，
        # 绝不进翻译链。队友说中文时做 zh->zh 翻译只会凭空制造错误
        # （实测「他们下包了」会被改写成「他们放置了包」）。
        if not should_translate(text, target):
            self.used_local = True
            self.src_passthrough = True
            self.stats_passthrough += 1
            self.last_latency = time.perf_counter() - t0
            return (text or "").strip()

        key2 = (text, target)
        if key2 in self.cache:
            # 缓存命中同样是「本地命中」：0 网络、0 token。
            # 必须在这里计数，否则本地占比会被系统性低估
            # （同一句第二次说走缓存，恰恰是最该算进 0 成本的部分）。
            self.stats_local += 1
            self.last_latency = time.perf_counter() - t0
            return self.cache[key2]

        self.used_fallback = False
        self.used_local = False

        # ── 第 1 层：本地规则（0 网络 / 0 token / <1ms）──
        # 内部优先级（v0.2.6）：
        #   0) 用户自建词库  —— 用户亲手教的，压过一切内置表
        #   1) 固定名词      —— 英雄/武器官方译名，不可能错
        #   2) 日/韩社区黑话 —— 云端会把「スパイク」翻成「尖刺装置」
        #   3) 英/中黑话表 + 多从句组合
        hit, how = learning.lexicon_lookup(text, target)

        # ★ v0.2.17：translate_fixed 只换**名词**（猎枭->Sova）。它返回的
        #   「Sova别去打了」是混排半成品——旧代码当成 local 命中直接上浮窗，
        #   剩下的整句永远没翻（用户实测「猎枭别去打了 -> Sova，别去打了。」）。
        #   词有据 ≠ 句有据：混排不算命中；名词替换后的文本（work）继续
        #   送后续层/云端，让剩下的部分真正被翻掉。
        work = text
        if not hit:
            hit, _ = translate_fixed(text, target)
            if hit and _mixed_output(hit, target):
                work = hit
                hit = None

        if not hit:
            if target == "zh":
                # 英译中的表键是**英文原文**，必须喂原文而不是 work
                hit, _ = translate_local(text)
                if not hit and detect_lang(text):
                    hit, _ = translate_cjk(text)
            else:
                # 中译英的表键是中文；名词已换成英文，正好拼出完整句
                hit, _ = translate_zh_to_en(work)

        if hit:
            self.last_latency = time.perf_counter() - t0
            self.used_local = True
            self.src_user = (how == "user")
            self.stats_local += 1
            self.cache[key2] = hit
            return hit

        self.src_user = False
        self.src_passthrough = False

        base_url, model = self.cfg.mt_endpoint()
        key = self.cfg.mt_key()
        if not base_url or not key:
            raise RuntimeError("翻译未配置：请先在设置中填写 API Key")

        tname = _HUNYUAN_TARGET.get(target, target)

        # ── 云端 ↔ 本地术语交叉校对（v0.2.11，第 3 项工作）──
        # 需求背景：「一句话是由很多个词组成的，那你可以云端和本地多对照一下，
        # 相互对照翻译。」
        #
        # 为什么要做：本地有 1200+ 条社区词库，但云端只看到通用的
        # STRICT_RULES_ZH，**看不到它们**。于是 'care they might be wrapping'
        # 里 wrapping 被直译成「包装的东西」—— 模型不认识游戏黑话。
        #
        # 修法是把**这句里实际出现过**的术语挑出来告诉它，而不是丢一整本
        # 术语表过去（丢了模型也会忽略，而且会诱发解释）。
        gl = ""
        if target == "zh":
            try:
                gl = cross_check.build_hint(text)
            except Exception:
                gl = ""
        if not gl:
            gl = _apply_glossary(text, target)
        # 术语表过长会拖慢并诱发模型解释，只保留精简版
        if gl and len(gl) > 500:
            gl = gl[:500]

        # ── 第 2 层增强：翻译记忆（v0.2.11 自学习核心）──
        # 从**已确认过**的译文里检索最相似的几条，连同待译句当 few-shot。
        # 依据 Moslem et al. (EACL 2023, *Adaptive MT with LLMs*)，论文实测
        # 这种做法超过 Google Translate / DeepL。
        #
        # 为什么这不是「收录词进词库」：
        #   · 记忆条目来自**实际用过的对局**，越玩越多、越准
        #   · 检索是按**当前这句话**找相似例句，不是查表命中
        #   · 学的是「怎么译这类句子」和口吻，不是死记某个词
        #
        # 为什么排除云端自己的输出（src_kind != 'cloud'）：
        #   拿模型的偏见当它自己的示例 = 把错误喂回给它，
        #   那正是 learning.py 老毛病的换皮。
        tm_ex = ""
        if target == "zh":
            try:
                _lang = detect_lang(text) or "en"
                if _lang in ("", "en"):
                    _lang = "en"
                elif _lang not in ("ko", "ja"):
                    _lang = "en"
                tm_ex = tm.as_examples(text, _lang)
                if tm_ex:
                    tm.mark_used(text, _lang)
            except Exception:
                logging.getLogger("valtrans.engine").exception(
                    "翻译记忆检索失败（不影响出字）")
                tm_ex = ""

        # ── 第 2 层：云端翻译 ──
        # ★ v0.2.17：中译英方向喂 work（名词已是英文，云端只需翻剩下的，
        #   "Sage别送" -> "Sage don't feed"）；英译中方向喂原文（本地表
        #   需要英文键，云端也更需要原始英文骨架）。
        cloud_in = work if target != "zh" else text
        try:
            # v0.2.11：翻译记忆示例与术语表**合并**进 system prompt。
            # 顺序：**示例在前、术语在后** —— 先给「照着这么译」的具体例句，
            # 再给术语表；反过来模型容易逐条对照术语表，把译文写成术语清单。
            sys_parts = []
            if tm_ex:
                sys_parts.append(tm_ex)
            if gl:
                sys_parts.append(f"术语对照（务必采用）：{gl}")

            if sys_parts:
                sys_prompt = (
                    "你是《无畏契约》(VALORANT) 玩家的实时语音翻译器。\n"
                    + STRICT_RULES_ZH + "\n" + "\n".join(sys_parts)
                )
                out = self._chat(base_url, key, model,
                                 [{"role": "system", "content": sys_prompt},
                                  {"role": "user",
                                   "content": f"把下面的语音翻译成{tname}。\n{cloud_in}"}])
            else:
                out = self._chat(base_url, key, model,
                                 [{"role": "user",
                                   "content": f"把下面的文本翻译成{tname}，不要额外解释。\n{cloud_in}"}])
        except Exception:
            fb_model = MT_PRESETS["zhipu"]["model"]
            if base_url == MT_PRESETS["zhipu"]["base_url"]:
                raise
            fb_key = self.cfg.mt_keys.get("zhipu", "")
            if not fb_key:
                raise
            out = self._chat(MT_PRESETS["zhipu"]["base_url"], fb_key, fb_model,
                             [{"role": "system",
                               "content": "你是电竞游戏语音翻译器，只输出译文。\n"
                                          + STRICT_RULES_ZH
                                          + f"\n术语对照：{gl or '无'}"},
                              {"role": "user", "content": text}])
            self.used_fallback = True
        finally:
            self.last_latency = time.perf_counter() - t0

        # ── 第 3 层：清洗（强制「只输出译文」）──
        out = clean_translation(out, fallback=text)
        out = re.sub(r"^(译文|翻译)[:：]\s*", "", out).strip()
        untranslated = False   # 云端没翻出来的句子：不进缓存、不喂自学习（见文末）

        # ── 第 3.5 层：外文残留清洗 + 翻译失败兜底（v0.2.11）──
        # 两件事，都必须是**实测驱动**的，不是「感觉应该有个检查」。
        if target == "zh":
            # (1) 云端整句翻对了、却把游戏专有名词原样留在中文里
            #     实测「리스폰 곧이에요」->「리스폰 马上到」
            #     玩家看到中韩混排是懵的，而且「리스폰」在国服根本不是词。
            #     用 cjk_slang 已有的 KO/JA 词表**反向**替换（同一份表，
            #     不维护第二份），0ms —— 不为几处残留再等 400~800ms。
            try:
                out, _fixed, _left = scrub_residual_cjk(out)
                _elog = logging.getLogger("valtrans.engine")
                if _fixed:
                    # ★ v0.2.16：日志只记数量，不落译文内容（语音是个人数据，
                    #   webui.log 明文留存对局对话 = 隐私泄漏面）
                    _elog.info("外文残留已修正 %d 处", len(_fixed))
                if _left:
                    # 词表缺条目：如实上报（可据此补表），不乱猜替换
                    _elog.warning("译文仍含 %d 个表外外文词，待补词表", len(_left))
            except Exception:
                logging.getLogger("valtrans.engine").exception(
                    "外文残留清洗失败（不影响出字）")

            # (2) 云端**根本没翻译**。实测（tests/eval_tm.py，A/B 两组复现）：
            #     'they dropped the smoke on site'
            #       -> 'they dropped the 控场 on s'
            #     整句还是英文，中间被塞了一个术语表里的汉字，尾巴还被截断。
            #     `clean_translation` 是清白的（实测原样通过）——
            #     问题在于**没有任何检查抓这种输出**。
            #
            #     判据用**比例**不是「有没有汉字」：第一版只查有没有汉字，
            #     被 '控场' 这一个词溜过去了（实测）。
            #     真正的��变量是「拉丁字母不能压过汉字」。
            #     与 `zh_to_en` 的「残留中文 >35% 就回云端」对称。
            if _looks_untranslated(out):
                # ★ v0.2.16：日志不落原文/译文内容（隐私），只记长度
                logging.getLogger("valtrans.engine").warning(
                    "云端未真正翻译（拉丁压过汉字，out_len=%d），退回原文",
                    len(out))
                out = (text or "").strip()
                untranslated = True

            # ── 后置校对：云端没用我们的译法时，如实记账 ──
            # 刻意**不静默改写**：译文语序不可知，机械插词会造出病句
            # （需求背景：「一定要通顺一点」）。这里只记录，作为
            # 「该给哪些术语补担保/提权」的依据。
            # ★ v0.2.16：未翻译退回原文的句子**跳过全部后置校对**——
            #   post_edit 会把英文原文里的词整词替换成中文，产出
            #   「they 掉包了 the 烟 on site」这种混排垃圾（实测）。
            if not untranslated:
                try:
                    _out2, _missed = cross_check.enforce(text, out)
                    if _missed:
                        logging.getLogger("valtrans.engine").info(
                            "云端未采用本地术语译法: %s", _missed)
                # 可以静默：译文**已经拿到了**（out 在上面就定型了），
                # enforce 只是事后回贴本地术语。术语表有问题也只该
                # 少贴一处词，不该把整条已译好的结果丢掉 —— 宁可少纠正，
                # 不能不出字（宁缺毋滥说的是「不译错」，不是「不出字」）。
                except Exception:
                    pass

                # ── v0.2.13：云端错译的**有证据**纠错（post_edit）──
                # 与上面的 cross_check.enforce 是两件事：
                #   enforce = 记账（不改写，因为它要动语序，会造病句）
                #   本模块  = 只整词替换已知错译（不动语序，无病句风险）
                # 依据实测：本地词表在真实语料上 0/10 命中，
                # 决定译文质量的是云端，而它会把 B site 当成「B站」。
                try:
                    out, _fixed2 = post_edit.correct_known_mistakes(text, out)
                except Exception:
                    logging.getLogger("valtrans.engine").exception(
                        "译后纠错失败（不影响出字）")

        # ── 第 3.5 层：外文残留清洗（v0.2.11）──
        # 云端兜底记账（v0.2.6）：喂给自学习系统。
        # 达标（≥8 次 + 跨 30 分钟 + 译文稳定）的会进候选池问用户是否入库。
        # ★ v0.2.16：云端没翻出来（退回原文）的句子**不进缓存、不喂自学习**
        #   —— 否则会缓存「英文=英文」的假翻译，还会攒出一条请用户
        #   「采纳」的英文→英文假词条永久压过云端。
        self.stats_cloud += 1
        if not untranslated:
            # 可以静默：这是**自学习语料的留档**，属于「锦上添花」。
            # 用户这一句已经翻译完成、马上要显示了；写盘失败只说明
            # 这一条学不到，下次同类句子多花一次云端往返而已，
            # 绝不该因此把已经好的结果回滚掉。
            try:
                learning.record_cloud_fallback(text, target, out)
            except Exception:
                pass

            self.cache[key2] = out
            if len(self.cache) > 512:
                self.cache.pop(next(iter(self.cache)))
        return out

