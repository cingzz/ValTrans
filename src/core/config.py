# -*- coding: utf-8 -*-
# 作者: cing  ·  https://github.com/cingzz
# 许可: GPL-3.0 + 商业授权（闭源/商用需向作者申请授权），见 LICENSE 与 LICENSE-COMMERCIAL.md
#
"""配置管理：默认值 + %APPDATA%/ValTrans/config.json 持久化。

v0.2.16 三条硬约束（都有真实事故背书）：
1. **API Key 加密落盘**（DPAPI，按用户账户绑定）——config.json 里不再有
   明文 `sk-`，info-stealer 类木马扫配置文件收割密钥的路被堵死。
   旧明文配置照常读（自动迁移），下次 save() 起全部密文。
2. **写盘必须原子**：先写临时文件再 os.replace。此前直接截断重写，
   断电/多线程并发可产生半截 JSON，而 load() 对坏文件静默重置 ——
   用户的 Key 一夜归零（v0.2.3 抹 Key 事故的同款敞口）。
3. **save() 全程持锁**：ASR 线程/浮窗 STA 线程/热键线程/JS 线程都会写。
"""
from __future__ import annotations

import base64
import ctypes
import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path

CONFIG_DIR = Path(os.environ.get("APPDATA", str(Path.home()))) / "ValTrans"
CONFIG_FILE = CONFIG_DIR / "config.json"
LOG_DIR = CONFIG_DIR / "logs"

_SAVE_LOCK = threading.Lock()
_LOG = logging.getLogger("valtrans.config")

# ---------------------------------------------------------------------------
# DPAPI 加密（ctypes 直调 crypt32，不引第三方依赖）
# ---------------------------------------------------------------------------
# 密文信封："dpapi1:" + base64(CryptProtectData 输出)。
# 解密绑定当前 Windows 用户账户（拷去别的机器/别的账户解不开 -> 返回空串
# 并告警，绝不让配置加载崩掉）。附加熵用固定串，防其它程序用 DPAPI 随手解。
_DPAPI_ENTROPY = b"ValTrans/config-keys/v1"
_ENC_PREFIX = "dpapi1:"

_CRYPTPROTECT_UI_FORBIDDEN = 0x1


class _BLOB(ctypes.Structure):
    _fields_ = [("cbData", ctypes.c_uint), ("pbData", ctypes.c_void_p)]


def _blob(data: bytes) -> _BLOB:
    buf = ctypes.create_string_buffer(data, len(data))
    return _BLOB(len(data), ctypes.cast(buf, ctypes.c_void_p)), buf


def _dpapi_protect(text: str) -> str:
    data = text.encode("utf-8")
    pin, pin_buf = _blob(data)
    pout = _BLOB()
    ent, ent_buf = _blob(_DPAPI_ENTROPY)
    if not ctypes.windll.crypt32.CryptProtectData(
            ctypes.byref(pin), None, ctypes.byref(ent), None, None,
            _CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(pout)):
        raise OSError("CryptProtectData failed")
    try:
        raw = ctypes.string_at(pout.pbData, pout.cbData)
        return _ENC_PREFIX + base64.b64encode(raw).decode("ascii")
    finally:
        ctypes.windll.kernel32.LocalFree(pout.pbData)


def _dpapi_unprotect(envelope: str) -> str:
    raw = base64.b64decode(envelope[len(_ENC_PREFIX):])
    pin, pin_buf = _blob(raw)
    pout = _BLOB()
    ent, ent_buf = _blob(_DPAPI_ENTROPY)
    if not ctypes.windll.crypt32.CryptUnprotectData(
            ctypes.byref(pin), None, ctypes.byref(ent), None, None,
            _CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(pout)):
        raise OSError("CryptUnprotectData failed")
    try:
        return ctypes.string_at(pout.pbData, pout.cbData).decode("utf-8")
    finally:
        ctypes.windll.kernel32.LocalFree(pout.pbData)


def _encrypt_keys(d: dict) -> dict:
    """Key dict -> 信封 dict（空值原样保留为 ""）。"""
    out = {}
    if not isinstance(d, dict):
        return out
    for k, v in d.items():
        v = (v or "").strip() if isinstance(v, str) else ""
        out[k] = _dpapi_protect(v) if v else ""
    return out


def _decrypt_keys(d: dict) -> dict:
    """信封 dict / 旧明文 dict -> 明文 dict（解不开的条目返回空并告警）。"""
    out = {}
    if not isinstance(d, dict):
        return out
    for k, v in d.items():
        v = v or "" if isinstance(v, str) else ""
        if v.startswith(_ENC_PREFIX):
            try:
                out[k] = _dpapi_unprotect(v)
            except Exception:
                _LOG.warning("config: 一条密钥解不开（换账户/换机器？），已置空")
                out[k] = ""
        else:
            out[k] = v   # 旧版明文配置：照常读，下次 save() 自动加密
    return out

# 云端 ASR 预设（OpenAI 兼容 /audio/transcriptions）
ASR_PRESETS = {
    # v0.2.13：默认换成 Qwen3-ASR-1.7B。
    #
    # 换的根据是**实测**（用户现有硅基 Key，同一段 4.3 秒真实对局语音，各打 4 次）：
    #     模型                        中位延迟   最慢      识别质量
    #     SenseVoiceSmall（旧默认）      6724ms   21114ms   日语「民ト…気用鮮命」全乱
    #                                                    韩语全错、粤语「滚住法育」全错
    #     Qwen3-ASR-1.7B               622ms     625ms   日语✓ 粤语「唔好送，稳住发育先」✓✓
    #                                                    英语「Careful! Your jungle…」✓
    #     XingChenASR-V3.2              826ms     907ms   日/韩全错
    #     XingChenASR-V3.2-Ultra       3196ms    3893ms   日/韩全错
    #
    # 即 **10.8 倍加速 + 识别更准**，而且延迟从 6724~21114ms 的巨大波动
    # 收敛到 622~625ms。旧默认保留在下面的 siliconflow_sensevoice 预设里。
    #
    # 为什么不用 Groq whisper-large-v3-turbo：实测本机 console.groq.com 与
    # api.groq.com 均返回 **403**（api.openai.com 直接连接超时）——
    # 是网络层被挡，换 Key 也无解。（阿里 DashScope / Deepgram 是通的，
    #  401 = 只是没 Key，将来可作备选。）
    "siliconflow": {
        "label": "硅基流动 Qwen3-ASR（国内直连·快 10 倍·推荐）",
        "base_url": "https://api.siliconflow.cn/v1",
        "model": "Qwen/Qwen3-ASR-1.7B",
        "price": "免费",
        "languages": ["zh", "en", "ja", "ko", "yue"],
        # 实测 language 参数被接受但**不影响输出**（ja/zh/en 三种都返回同一句
        # 正确日语），说明它走自动检测。所以这里置 True，
        # 免得我们把语言硬塞给它反而干扰。
        "auto_detect": True,
    },
    "siliconflow_sensevoice": {
        "label": "硅基流动 SenseVoice（旧默认·较慢，保留作回退）",
        "base_url": "https://api.siliconflow.cn/v1",
        "model": "FunAudioLLM/SenseVoiceSmall",
        "price": "免费",
        "languages": ["zh", "en", "ja", "ko", "yue"],
        "auto_detect": False,
    },
    "groq": {
        "label": "Groq whisper-large-v3（全语言·自动检测）",
        "base_url": "https://api.groq.com/openai/v1",
        "model": "whisper-large-v3-turbo",
        "languages": ["zh", "en", "ja", "ko"],
        "auto_detect": True,
    },
    "openai": {
        "label": "OpenAI whisper-1（全语言·自动检测）",
        "base_url": "https://api.openai.com/v1",
        "model": "whisper-1",
        "languages": ["zh", "en", "ja", "ko"],
        "auto_detect": True,
    },
    "custom": {
        "label": "自定义 OpenAI 兼容端点",
        "base_url": "",
        "model": "",
        "languages": ["zh", "en", "ja", "ko"],
        "auto_detect": True,
    },
}

# 翻译服务商预设（OpenAI 兼容 /chat/completions）
# ---------------------------------------------------------------------------
# 翻译模型预设（v0.2.5 实测重排）
# ---------------------------------------------------------------------------
# 实测口径：硅基流动上用同一批「本地表覆盖不到的云端兜底句」跑对拍。
#
#   模型              平均延迟   最大延迟   解释泄漏   输出tok   成本
#   Qwen2.5-14B          615ms     811ms     0/10       64     ≈¥0.005/局
#   Hunyuan-MT-7B       3547ms   12685ms     2/10      174     免费
#
# 社区语言对比（这是选 Qwen 的真正理由，不是速度也不是钱）：
#   they planted spike on A
#     Hunyuan  他们在A点放置了尖刺装置       ← 书面语 + 错译
#     Qwen     A包被种了                     ← 社区话
#   spike dropped mid
#     Hunyuan  "spike dropped mid"在《无畏契约》中指的是…（66 token 解释）
#     Qwen     中点包掉了
#
# 注意：Qwen 也会犯错（can you flash me -> 你给我放烟吗，flash≠烟）。
# 所以架构仍是「本地表先兜 95%，模型只处理剩下 5%」，
# 不要因为换模型就放松本地术语表的扩充。
MT_PRESETS = {
    "qwen": {
        "label": "千问 Qwen2.5-14B（推荐·社区语言最准）",
        "price": "¥1.26 / M tokens",
        "base_url": "https://api.siliconflow.cn/v1",
        "model": "LoRA/Qwen/Qwen2.5-14B-Instruct",
        "note": "实测 615ms / 零解释泄漏。唯一短板：偶发术语误解，靠本地表兜。",
    },
    "siliconflow": {
        "label": "Hunyuan-MT-7B（免费档）",
        "price": "免费",
        "base_url": "https://api.siliconflow.cn/v1",
        "model": "tencent/Hunyuan-MT-7B",
        "note": "输入/输出均免费。但实测 3547ms、2/10 解释泄漏、「尖刺装置」式书面语。",
    },
    "zhipu": {
        "label": "智谱 GLM-4-Flash（免费·仅故障兜底）",
        "price": "免费",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "model": "glm-4-flash",
        "note": "需单独配智谱 Key。默认不启用。",
    },
}

# 默认走 Qwen（v0.2.5 起）。旧配置里的 "siliconflow" 仍然有效，
# 不强制改写用户的 mt_preset —— 用户想用免费档就让他用。
DEFAULT_MT_PRESET = "qwen"

LANGUAGE_NAMES = {
    "zh": "中文", "en": "英语", "ja": "日语", "ko": "韩语",
     "yue": "粤语",
}


@dataclass
class AppConfig:
    # 音频
    capture_mode: str = "cable"          # cable=虚拟声卡线路(推荐) / loopback=整机输出
    cable_output_device: str = ""        # CABLE Output 设备名（空=自动查找）
    loopback_device: str = ""            # loopback 模式的输出设备名
    mic_device: str = ""                 # 反向翻译麦克风（空=系统默认）
    monitor_relay: bool = True           # 软件级监听：把 CABLE 声音回放到耳机（免手动设侦听）
    vad_mode: str = "silero"             # silero / rms
    rms_threshold: float = 0.01          # RMS 兜底阈值
    prebuffer_seconds: float = 3.0       # 3 秒预缓冲，实机测出的平衡点
    min_speech_ms: int = 250
    silence_ms: int = 300
    max_segment_s: float = 15.0
    # v0.2.16 同传增量：说话期间每 draft_interval_ms 出一版「草稿字幕」，
    # 说完后的最终稿照常替换。关掉则回退纯批式（说完才翻）。
    partial_enabled: bool = True
    draft_interval_ms: int = 1000

    # 语言
    target_lang: str = "zh"              # 队友语音 -> 中文
    reverse_target_lang: str = "en"      # 我说中文 -> 该语言
    lock_source_lang: str = ""           # 空=自动检测；否则锁定

    # 云端
    asr_preset: str = "siliconflow"
    asr_keys: dict = field(default_factory=dict)      # preset->key
    mt_preset: str = DEFAULT_MT_PRESET
    mt_keys: dict = field(default_factory=dict)
    custom_asr_url: str = ""
    custom_asr_model: str = ""
    custom_mt_url: str = ""
    custom_mt_model: str = ""

    # 字幕浮窗
    overlay_x: int = -1                  # -1 = 底部居中
    overlay_y: int = -1
    overlay_opacity: float = 0.8
    overlay_font_size: int = 22
    overlay_width: int = 520
    overlay_style: str = "tactical"      # tactical/cream/walkie/card/radar
    overlay_anim: str = "fade"           # fade/typewriter/line/pop
    overlay_locked: bool = False
    overlay_enabled: bool = False         # 字幕显示总开关（样式页可一键开关）
    # v0.2.11：字幕高度可调（此前只有宽度可调，高度硬编码 OVERLAY_FIXED_H=380）。
    # 默认仍是 380 —— 保持既有行为不变，用户想调再调。
    overlay_height: int = 380
    overlay_pinned: bool = False          # True=固定在当前位置（鼠标穿透，不可拖动）
                                         # False=可拖动（拖完保存新位置）
    show_original: bool = True
    show_speaker: bool = True
    fade_seconds: float = 8.0

    # 朗读 / 模式
    tts_enabled: bool = True
    tts_voice: str = ""                  # 空=按语言自动（多语人声）
    tts_rate: int = 0                    # 语速 -50~+50（百分比）
    tts_pitch: int = 0                   # 音调 -50~+50（Hz）
    streamer_mode: bool = False          # 主播模式：关朗读+关复制
    asr_mode: str = "fast"               # fast / precision（precision 换高质量模型）
    auto_copy: bool = True               # PTT 译文自动复制剪贴板

    # 热键
    hotkey_lock: str = "<ctrl>+<alt>+q"
    hotkey_review: str = "<ctrl>+<alt>+h"
    hotkey_ptt: str = "<ctrl>+<alt>+s"
    hotkey_move: str = "<ctrl>+<shift>+d"   # 切换浮窗「固定/可拖动」

    # 其他
    first_run_done: bool = False
    disclaimer_accepted: bool = False

    # ---------- 持久化 ----------
    @classmethod
    def load(cls) -> "AppConfig":
        cfg = cls()
        try:
            if CONFIG_FILE.exists():
                data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
                for k, v in data.items():
                    if hasattr(cfg, k):
                        setattr(cfg, k, v)
        except json.JSONDecodeError:
            # ★ v0.2.16：坏文件**留档改名**再从头开始，绝不能无声重置——
            #   静默重置 + 下次任意一次 save() = 用户 Key 永久丢失。
            try:
                stamp = time.strftime("%Y%m%d-%H%M%S")
                CONFIG_FILE.replace(CONFIG_FILE.with_name(
                    f"config.json.corrupt-{stamp}"))
                _LOG.error("config.json 损坏，已留档为 config.json.corrupt-%s，"
                           "使用默认配置启动", stamp)
            except OSError:
                pass
        except OSError:
            pass
        # Key 解密（v0.2.16）：明文旧配置原样通过，密文信封解开
        cfg.asr_keys = _decrypt_keys(cfg.asr_keys)
        cfg.mt_keys = _decrypt_keys(cfg.mt_keys)

        # v0.2.5：老配置的 mt_preset=="siliconflow" 升级为 "qwen"，
        # 并把 Key 复制到 qwen 名下。只改这两个字段，不碰其它任何配置。
        # migrate_mt_preset 内部已保证「已有 qwen Key 时不动」。
        try:
            if cfg.migrate_mt_preset():
                cfg.save()
        except Exception:
            pass    # 迁移失败不影响启动，用户仍可手动在设置里选
        return cfg

    def save(self) -> None:
        # ★ v0.2.16：①全程持锁（ASR/浮窗 STA/热键/JS 四个线程都会写）
        # ②先写临时文件再 os.replace（原子替换，杜绝半截 JSON）
        # ③Key 字段 DPAPI 加密后再落盘
        with _SAVE_LOCK:
            try:
                d = asdict(self)
                d["asr_keys"] = _encrypt_keys(self.asr_keys)
                d["mt_keys"] = _encrypt_keys(self.mt_keys)
                CONFIG_DIR.mkdir(parents=True, exist_ok=True)
                tmp = CONFIG_FILE.with_name("config.json.tmp")
                tmp.write_text(json.dumps(d, ensure_ascii=False, indent=2),
                               encoding="utf-8")
                os.replace(tmp, CONFIG_FILE)
            except Exception:
                _LOG.exception("config 保存失败")

    # ---------- 便捷取值 ----------
    def asr_endpoint(self) -> tuple[str, str, list, bool]:
        """返回 (base_url, model, languages, auto_detect)。"""
        if self.asr_preset == "custom":
            p = ASR_PRESETS["custom"]
            return self.custom_asr_url, self.custom_asr_model, p["languages"], p["auto_detect"]
        p = ASR_PRESETS.get(self.asr_preset, ASR_PRESETS["siliconflow"])
        if self.asr_mode == "precision" and self.asr_preset == "groq":
            return p["base_url"], "whisper-large-v3", p["languages"], p["auto_detect"]
        return p["base_url"], p["model"], p["languages"], p["auto_detect"]

    def asr_key(self) -> str:
        """取当前预设的 ASR Key。

        v0.2.20：补「同 provider 回落」——这是 mt_key() 那个 v0.2.5 bug
        在 ASR 侧的**同款翻版，当时没修**。

        事实（实测 ASR_PRESETS）：
            siliconflow           base_url = api.siliconflow.cn/v1
            siliconflow_sensevoice base_url = api.siliconflow.cn/v1   ← 同一个
            groq / openai         各自不同 base_url
        也就是说 `siliconflow` 与 `siliconflow_sensevoice` 是**同一 provider
        的两个模型档位，共用同一把 Key**。而这里原来只有
            return self.asr_keys.get(self.asr_preset, "")
        于是：用户把 Key 存在 asr_keys["siliconflow"]，而 asr_preset 选的是
        `siliconflow_sensevoice`（或反过来）-> 拿到空串 -> **ASR 静默失效**，
        界面上只表现为「识别不出」，不报任何错。

        参照 mt_key() 的注释原话：
            「qwen 与 hunyuan 同属硅基流动，共用同一把 Key。用户的 Key 存在
              mt_keys["siliconflow"] 下，若不做回落，切到 qwen 预设会拿到空串
              —— 翻译静默失效。」

        ★ 为什么**只**按 base_url 回落，不做「任意 provider 都能用」：
          跨 provider 回落会拿到**别家的 Key** -> 401。
          空串会明确报「ASR 未配置」，而一个无效 Key 会让人误以为是服务端
          或网络问题，排查方向完全跑偏（错误可见性 > 猜）。
        """
        k = (self.asr_keys or {}).get(self.asr_preset, "")
        if k:
            return k
        if self.asr_preset == "custom":
            return ""
        base = ASR_PRESETS.get(self.asr_preset, {}).get("base_url", "")
        for name, val in (self.asr_keys or {}).items():
            if not val:
                continue
            p = ASR_PRESETS.get(name)
            if p and p.get("base_url") == base:
                return val
        return ""

    def mt_endpoint(self) -> tuple[str, str]:
        if self.mt_preset == "custom":
            return self.custom_mt_url, self.custom_mt_model
        p = MT_PRESETS.get(self.mt_preset, MT_PRESETS[DEFAULT_MT_PRESET])
        return p["base_url"], p["model"]

    def mt_key(self) -> str:
        """取当前预设的 Key。

        v0.2.5：qwen 与 hunyuan 同属硅基流动，共用同一把 Key。
        用户的 Key 存在 mt_keys["siliconflow"] 下，若不做回落，
        切到 qwen 预设会拿到空串 —— 翻译静默失效。
        """
        k = self.mt_keys.get(self.mt_preset, "")
        if k:
            return k
        # 按 base_url 反查同 provider 的 Key
        if self.mt_preset == "custom":
            return ""
        base = MT_PRESETS.get(self.mt_preset, {}).get("base_url", "")
        for name, val in (self.mt_keys or {}).items():
            if not val:
                continue
            p = MT_PRESETS.get(name)
            if p and p.get("base_url") == base:
                return val
        # 最后兜底：硅基流动系任一 Key 都行
        for name in ("siliconflow", "qwen"):
            v = (self.mt_keys or {}).get(name, "")
            if v:
                return v
        return ""

    def migrate_mt_preset(self) -> bool:
        """老配置升级：siliconflow -> qwen，并把 Key 复制过去。

        只动 mt_preset 和 mt_keys 两个字段，绝不整文件覆盖
        （整文件覆盖会抹掉 API Key，见 实测事故）。
        返回 True 表示确实改动了。
        """
        changed = False
        keys = dict(self.mt_keys or {})
        if self.mt_preset == "siliconflow" and not keys.get("qwen") and keys.get("siliconflow"):
            keys["qwen"] = keys["siliconflow"]
            self.mt_keys = keys
            self.mt_preset = "qwen"
            changed = True
        return changed
