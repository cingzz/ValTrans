# -*- coding: utf-8 -*-
# 作者: cing  ·  https://github.com/cingzz
# 许可: GPL-3.0 + 商业授权（闭源/商用需向作者申请授权），见 LICENSE 与 LICENSE-COMMERCIAL.md
#
"""TTS：edge-tts 合成 + miniaudio 播放（本地播放，队友听不到）。

音色目录：每个语言提供多款音色，含「多语人声」（说外语不带中文口音，更自然）；
语速/音调可调（tts_rate: -50~+50%，tts_pitch: -50~+50Hz）。
"""
from __future__ import annotations

import asyncio
import logging
import queue
import threading
import time

import numpy as np
import sounddevice as sd

import miniaudio

log = logging.getLogger("valtrans.tts")

# 音色目录：(edge-tts 名称, 中文标签, 适用语言, 是否多语人声)
# ---------------------------------------------------------------------------
# 音色目录（v0.2.7 从 voices.json 加载）
# ---------------------------------------------------------------------------
# 用户反馈：「音色太统一化了，基本上都是同一个声音出来的，没有特色」
# 实测结论：
#   · edge-tts 7.2.8 已移除 style 参数（ Communicate 不接受该 kwarg ），
#     所以「同一音色换性格」走不通。
#   · 但 SSML <prosody> 会透传（实测同一句话 9792 -> 23472 字节），
#     这是唯一可用的杠杆。
#   · 中文实际可用 12 个音色（zh-CN 6 + zh-TW 3 + zh-HK 3），
#     原来只用了 5 个，且没分组，所以听起来都一样。
# 详见 docs/音色系统.md。
import json as _json
import os as _os

_VOICES_JSON = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)),
                             "voices.json")
try:
    with open(_VOICES_JSON, "r", encoding="utf-8") as _f:
        _VOICES = _json.load(_f)
except Exception:                                   # pragma: no cover
    _VOICES = {"voices": {}, "personas": []}

# 目录结构：list[(voice_id, label, langs, multilingual, desc, prosody)]
# v0.2.9：韵律内嵌进音色本身，不再需要「人设」这一层概念。
# 用户反馈「39 种太多」，精简到 6~8 个，每个自带性格，听感差异明显。
VOICE_CATALOG = []
for _lg, _lst in (_VOICES.get("voices") or {}).items():
    for _it in _lst:
        VOICE_CATALOG.append((
            _it["id"], _it.get("label", _it["id"]), {_lg},
            _it.get("multilingual", False),
            _it.get("desc", ""), _it.get("prosody", {}),
        ))

# 音色的 id -> 韵律（{"rate": %, "pitch": Hz}）
VOICE_PROSODY = {}
for _lg, _lst in (_VOICES.get("voices") or {}).items():
    for _it in _lst:
        if _it.get("prosody"):
            VOICE_PROSODY[_it["id"]] = _it["prosody"]

# 人设层已在 v0.2.9 移除（音色的性格内嵌进音色本身）。
# 保留这个符号为空字典，避免引用它的旧代码 ImportError。
VOICE_PERSONAS = {p["name"]: p for p in (_VOICES.get("personas") or [])}

# 各语言「默认音色」：优先多语人声，否则该语言第一个
VOICE_DEFAULT = {}
for _lg, _lst in (_VOICES.get("voices") or {}).items():
    _multi = [x for x in _lst if x.get("multilingual")]
    _pick = _multi[0] if _multi else (_lst[0] if _lst else None)
    # 存 id 字符串，不是整条 dict —— 之前存了 dict，
    # 导致 pick_default_voice() 返回 dict，下游当字符串用就炸。
    VOICE_DEFAULT[_lg] = (_pick or {}).get("id", "")

# 「自动」策略：按语种挑一个合适的音色
def pick_default_voice(lang: str) -> str:
    """按语种挑一个默认音色 id（字符串，不是 dict）。"""
    lang = (lang or "zh").lower()[:2]
    if VOICE_DEFAULT.get(lang):
        return VOICE_DEFAULT[lang]
    return VOICE_DEFAULT.get("en") or "en-US-JennyNeural"


def plan_voice(voice_id: str | None, lang: str = "zh"):
    """把 voice_id 解析成 (实际音色, SSML包裹模板, pitch, rate)。

    支持三种写法：
        "zh-CN-XiaoxiaoNeural"         裸音色
        "zh-CN-YunyangNeural|沉稳指挥"   指定音色 + 人设韵律
        "persona:活泼少女"              直接用人设自带的音色

    注意函数名不叫 resolve_voice —— 那个名字已被原有的
    `resolve_voice(override, lang) -> str` 占用（文件末尾定义，
    Python 取最后一个）。同名覆盖导致人设解析静默失效，
    本项目已经栽过两次同类坑，见下方说明。
    """
    vid = (voice_id or "").strip()
    persona = None

    if vid.startswith("persona:"):
        persona = vid.split(":", 1)[1].strip()
        vid = ""
    elif "|" in vid:
        a, b = vid.split("|", 1)
        if a.strip() and b.strip() in VOICE_PERSONAS:
            vid, persona = a.strip(), b.strip()
        else:
            vid = a.strip() or vid

    if persona and persona in VOICE_PERSONAS:
        p = VOICE_PERSONAS[persona]
        if not vid:
            vid = p["voice"]
        return vid, p.get("wrap"), int(p.get("pitch", 0)), int(p.get("rate", 0))

    if not vid:
        vid = pick_default_voice(lang)

    # v0.2.9：音色自带韵律 -> 直接用，生成 SSML 包裹。
    # 这样每个音色本身就是一种"性格"，用户只选音色即可。
    pr = VOICE_PROSODY.get(vid)
    if pr:
        wrap = ("<prosody rate='%s%d%%' pitch='%s%dHz'>{}</prosody>"
                % ("-" if pr.get("rate", 0) < 0 else "+", abs(pr.get("rate", 0)),
                   "-" if pr.get("pitch", 0) < 0 else "+", abs(pr.get("pitch", 0))))
        return vid, wrap, pr.get("pitch", 0), pr.get("rate", 0)
    return vid, None, None, None
# 按语言自动选择的默认音色（优先多语人声）
DEFAULT_BY_LANG = {
    "zh": "zh-CN-XiaoxiaoMultilingualNeural",
    "en": "zh-CN-XiaoxiaoMultilingualNeural",   # 中文用户听英文也用中文人声更顺耳
    "ja": "zh-CN-XiaoxiaoMultilingualNeural",
    "ko": "zh-CN-XiaoxiaoMultilingualNeural",
}

# 多语人声在 edge-tts 服务端偶发不可用（NoAudioReceived），为默认音色配普通音色兜底；
# 该语言的普通音色作为第二兜底，保证"有声音"优先于"音色完美"。
FALLBACK_VOICE = {
    "zh-CN-XiaoxiaoMultilingualNeural": "zh-CN-XiaoxiaoNeural",
    "en-US-AvaMultilingualNeural": "en-US-EmmaNeural",
}
FALLBACK_BY_LANG = {
    "zh": "zh-CN-XiaoxiaoNeural", "en": "en-US-EmmaNeural",
    "ja": "ja-JP-NanamiNeural", "ko": "ko-KR-SunHiNeural",
    # v0.2.8：pt/es/ru 已按用户要求移除（玩家极少，基本匹配不到）
    # v0.2.17：Jenny/Yunyang/Andrew 移出目录（用户嫌 AI 味重/数量多），
    # en 兜底改 Emma；zh 默认改云希（自然口吻）
}


def resolve_voice(override: str, lang: str) -> str:
    """按语种返回实际使用的音色 id（原有接口，保留兼容）。

    人设解析请用 plan_voice()，它会额外返回 SSML 韵律与音调语速。
    """
    if override:
        return plan_voice(override, lang)[0]
    return pick_default_voice(lang)


class TTSPlayer:
    def __init__(self, voice: str = "", enabled: bool = True,
                 rate: int = 0, pitch: int = 0, sf_key: str = ""):
        self.voice_override = voice
        self.enabled = enabled
        self.rate = rate
        self.pitch = pitch
        # ★ v0.2.18：CosyVoice2 云端音色走硅基流动（与 MT/ASR 同一把 Key）。
        # 空 Key 时自动跳过云端款、用本地 edge 音色。
        self.sf_key = sf_key
        self._q: queue.Queue[tuple[str, str]] = queue.Queue(maxsize=8)
        self._thread = threading.Thread(target=self._worker, daemon=True)
        self._running = False
        # 播放中标志：管线采集到该事件即暂停识别（防 loopback 模式 TTS 回声自触发死循环）
        self.playing = threading.Event()

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        # 每次启动新建线程：Thread 对象 start 一次后就废弃（stop 后重启会报
        # "threads can only be started once"）
        self._thread = threading.Thread(target=self._worker, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        try:
            sd.stop()   # 立即掐断当前播放（否则已合成的语音会放完才停）
        except Exception:
            pass
        try:
            self._q.put_nowait(("", ""))
        except queue.Full:
            pass

    def say(self, text: str, lang: str = "zh") -> None:
        if not self.enabled or not text:
            return
        try:
            self._q.put_nowait((text, lang))
        except queue.Full:
            pass  # 丢最旧策略：直接丢弃本次


    # ---------- 内部 ----------
    def _worker(self) -> None:
        while self._running:
            try:
                text, lang = self._q.get(timeout=1.0)
            except queue.Empty:
                continue
            if not text:
                break
            try:
                mp3 = self._synth_for_lang(text, lang)
                if mp3:
                    self._play(mp3)
            except Exception:
                log.exception("TTS 合成/播放失败")  # 不再静默：静默吞异常曾让朗读无声故障难以排查
                continue  # 单句失败不影响队列

    def _synth_for_lang(self, text: str, lang: str) -> bytes:
        """按语言解析音色合成；云端/多语人声不可用时自动降级到本地音色。"""
        voice = resolve_voice(self.voice_override, lang)
        # ★ v0.2.18：CosyVoice2 云端音色（voices.json 里 provider=cosyvoice、
        # id 前缀 cosy:）。没配硅基 Key 时直接用本包兜底音色，不浪费时间。
        if voice.startswith("cosy:"):
            if not self.sf_key:
                voice = FALLBACK_BY_LANG.get(lang) or voice
            else:
                try:
                    return self._synth_cosy(text, voice[5:])
                except Exception:
                    log.warning("CosyVoice 合成失败，回落 edge-tts 本地音色",
                                exc_info=True)
                    voice = FALLBACK_BY_LANG.get(lang) or voice
        try:
            return self._synth(text, voice)
        except Exception:
            fb = FALLBACK_VOICE.get(voice) or FALLBACK_BY_LANG.get(lang)
            if not fb or fb == voice:
                raise
            log.warning("音色 %s 合成失败，自动降级为 %s", voice, fb)
            return self._synth(text, fb)

    def _synth_cosy(self, text: str, cv_name: str) -> bytes:
        """硅基流动 CosyVoice2 合成（MP3 bytes）。不走 SSML/韵律包装——
        该模型自带自然韵律；用户语速滑杆映射到 speed 参数。"""
        from ..core.security import pooled_client
        speed = max(0.5, min(2.0, 1.0 + (self.rate or 0) / 100.0))
        client = pooled_client(timeout=30.0)
        r = client.post(
            "https://api.siliconflow.cn/v1/audio/speech",
            headers={"Authorization": f"Bearer {self.sf_key}"},
            json={"model": "FunAudioLLM/CosyVoice2-0.5B",
                  "input": text,
                  "voice": f"FunAudioLLM/CosyVoice2-0.5B:{cv_name}",
                  "response_format": "mp3",
                  "sample_rate": 44100,
                  "speed": speed, "gain": 0},
            timeout=30.0)
        r.raise_for_status()
        mp3 = r.content
        if not mp3:
            raise RuntimeError("CosyVoice 返回空音频")
        return mp3

    def _synth(self, text: str, voice: str) -> bytes:
        # v0.2.9：音色自带韵律（persona 层已移除，性格内嵌进音色）。
        # 用 getattr 而不是 self._lang —— TTSPlayer.__init__ 里并没有这个
        # 属性，之前是我在测试里手动赋值才没暴露，一到真实调用就 AttributeError。
        voice, _wrap, p_pitch, p_rate = plan_voice(
            voice, getattr(self, "_lang", "zh"))

        # ★★ v0.2.21 重大修复（2026-10-06，用户实测「语音等了很久都没出」）
        # ------------------------------------------------------------------
        # 原来这里把音色韵律拼成 `<prosody rate=.. pitch=..>文本</prosody>`
        # 再交给 edge_tts.Communicate。**那是错的**：
        #   edge-tts 7.2.8 把传入文本当**纯文本**做 XML 转义，
        #   我们拼的标签被转义成 `&lt;prosody...&gt;` —— 于是**被当正文念出来**。
        #
        # 实测对照（同一音色 en-US-EmmaNeural、同一句 "Don't play with your Operator."）：
        #   不包裹 -> 音频 2.0 秒 / 12096 字节
        #            ASR 转回 "Don't play with your operator."            ✓
        #   包裹   -> 音频 8.7 秒 / 51984 字节
        #            ASR 转回 "Prosody rate equals plus zero percent.
        #                       Pitch equals plus six hertz.
        #                       Don't play with your operator. Slash prosody."  ★
        # 音频长 4.3 倍，而且绝大部分内容是「韵律参数朗读」。
        #
        # 为什么全库都中招：`plan_voice` 里 `if pr:` —— voices.json 给
        # **每一个**音色都写了 prosody（含 rate/pitch 全 0 的），
        # 非空 dict 就是真，所以**全部**音色都被包了一层。
        # 唯一念对的是 en-US-JennyNeural —— 它不在 catalog 里，
        # VOICE_PROSODY.get() 返回 None，恰好没被包。
        #
        # 原注释说「edge-tts 7.2.8 会透传 <prosody>（实测有效）」——**该结论错了**，
        # 下面这组对照就是反证。人设韵律改走 Communicate 自带的 rate/pitch：
        # 它内部会生成**正确的** <prosody>（见 edge_tts/communicate.py:mkssml）。
        #
        # 用户滑杆与音色韵律**不叠加**（取其一）：
        #   叠加过一次，「急报点」变成 +36% 直接 NoAudioReceived，
        #   「沉稳指挥」-16% 慢得发傻。滑杆有值就用滑杆，否则用音色自带。
        _b_rate = int(p_rate or 0)
        _b_pitch = int(p_pitch or 0)
        rate = f"{self.rate:+d}%" if self.rate else f"{_b_rate:+d}%"
        pitch = f"{self.pitch:+d}Hz" if self.pitch else f"{_b_pitch:+d}Hz"

        async def run() -> bytes:
            import edge_tts
            data = b""
            com = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch)
            async for chunk in com.stream():
                if chunk["type"] == "audio":
                    data += chunk["data"]
            return data
        try:
            return asyncio.run(run())
        except RuntimeError:
            box: list[bytes] = []
            t = threading.Thread(target=lambda: box.append(asyncio.run(run())), daemon=True)
            t.start(); t.join(timeout=30)
            return box[0] if box else b""

    def _play(self, mp3: bytes) -> None:
        if not mp3:
            return
        # miniaudio 仅负责 mp3 解码；播放走 sounddevice（sd.play/sd.wait 跨版本稳定，
        # miniaudio 的 PlaybackDevice API 在 1.71 已不兼容旧写法且会静默失败）
        dec = miniaudio.decode(mp3, nchannels=2, sample_rate=44100,
                               dither=miniaudio.DitherMode.TRIANGLE)
        audio = np.frombuffer(bytes(dec.samples), dtype=np.int16).reshape(-1, dec.nchannels)
        self.playing.set()   # 采集暂停门：播放期间管线丢块，防回声
        try:
            sd.play(audio, dec.sample_rate)
            sd.wait()
            time.sleep(1.2)  # 尾音抑制：等扬声器余音/音效处理散尽再放行采集
        finally:
            self.playing.clear()
