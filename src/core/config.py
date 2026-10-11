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
        # ★ v0.3.1：新增 acc = 实测准确率，给 UI 直接标注。
        #   数字出处：providers/base.py:29-33 的 2026-10-10 实测
        #   （8 个带真值样本，中/粤/英/日/韩）。没有实测的档**不填** ——
        #   填一个没跑过的数字，等于对用户做没有依据的承诺（同 languages 的原则）。
        "acc": "0.926 · 达标 4/8",
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
        # ★ 2026-10-11 官方核价（console.groq.com/docs/model/whisper-large-v3-turbo）：
        #   $0.04/小时；免费档每天 2000 次请求（一局 = 1 次请求，个人够用）。
        "price": "免费档每天 2000 次；付费 $0.04 / 小时（一局约 ¥0.14）",
        # ★ 但**国内网络实测不通**：api.groq.com 返回 403，换 Key 无解
        #   （见上方注释 L131-134）。不标这条，用户会选一个用不了的档。
        "note": "⚠ 国内网络实测 403 被挡，换 Key 无解；海外网络可用。",
        "languages": ["zh", "en", "ja", "ko"],
        "auto_detect": True,
    },
    "openai": {
        "label": "OpenAI whisper-1（全语言·自动检测）",
        "base_url": "https://api.openai.com/v1",
        "model": "whisper-1",
        # ★ 2026-10-11 官方核价：$0.006 / 分钟（= $0.0001/秒）。
        #   一局约 30 分钟 → $0.18 ≈ ¥1.3，是阿里千问（¥0.026）的约 50 倍。
        #   实测 api.openai.com 直连超时（同上 L131-134）。
        "price": "$0.006 / 分钟（一局约 ¥1.3）",
        "note": "⚠ 国内直连实测超时；比阿里千问贵约 50 倍。",
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
    # —— v0.3.0 新增：阿里千问（2026-10-10 实测，8 个带真值样本）——
    #   均分 0.997 / 达标 8/8，对比现有硅基基线 0.926 / 4/8。
    #   差距集中在**韩语**：硅基 0.848（把 적이 听成 저이），
    #   而韩语是外服 VALORANT 的核心场景。粤语硅基 0.750（繁体打龍→简体打龙）。
    #   代价 ¥0.00022/秒，一局约 ¥0.026。
    #
    # ★ 两个预设是**同一个模型的两条通路**，不是两个服务商：
    #   aliyun_qwen       OpenAI 兼容端点，形同其他家，接入最省事
    #   aliyun_dashscope  DashScope 原生端点 —— **唯一能带术语的通路**
    #     实测：兼容端点带 system 消息会被 400 拒掉
    #       InternalError.Algo.InvalidParameter: The dedicated task `asr`
    #         ... does not support this input
    #   所以默认给 aliyun_qwen；需要注入游戏术语时才选 dashscope，
    #   且注意**实测带术语反而掉分**（0.997→0.966，粤语 1.000→0.750），
    #   所以术语开关默认关闭。
    #
    # ★ base_url 用旧的 dashscope.aliyuncs.com：没有 WorkspaceId 时
    #   只能用旧的，文档明写「现有域名仍可正常使用」。
    "aliyun_qwen": {
        # ★ label 里的价格已移到 price 字段 —— 原来 label 和 price
        #   都写着 ¥0.00022，同一个数在两处维护，改一处漏一处就是错的。
        # ★ 不写「推荐」：硅基那档（免费默认）已经占了「推荐」，
        #   同一个下拉里两个「推荐」等于都没有。这里按场景写清楚差异点。
        "label": "阿里千问 qwen3-asr-flash（韩语最准·外服首选）",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "qwen3-asr-flash",
        "price": "¥0.00022 / 秒（一局约 ¥0.026）",
        "acc": "0.997 · 达标 8/8",
        # ★ 只列项目**已授权**的 5 种，不照抄服务商支持的 30 种。
        #   用户明确决定过：白名单外的三种小众语种「玩的人很少，
        #   一般匹配不到，把与他们相关的全部删掉」，保留 zh(含粤语)/en/ja/ko。
        #   千问确实支持更多语种，但那属于「服务商能做」而不是
        #   「本项目承诺做」—— 列出来等于对用户做了没有对应词库、
        #   也没有实测的承诺。
        #   verify_src.py 的 ALLOWED_LANGS 守护会拦着
        #   （它连**注释里提到**那些语种都判红，所以这里也不能点名）。
        "languages": ["zh", "yue", "en", "ja", "ko"],
        "auto_detect": False,     # 支持显式指定语种，实测能提升准确率
        "key_group": "aliyun",    # 与 aliyun_dashscope 共用一把 Key
    },
    "aliyun_dashscope": {
        "label": "阿里千问·原生端点（唯一支持术语注入·默认不注入）",
        "base_url": "https://dashscope.aliyuncs.com/api/v1",
        "model": "qwen3-asr-flash",
        "price": "¥0.00022 / 秒（一局约 ¥0.026）",
        # 同一个模型的另一条通路，准确率相同；但**一旦开术语注入就掉分**
        # （实测 0.997→0.966，粤语 1.000→0.750），所以标注的是不开术语的值。
        "acc": "0.997 · 达标 8/8",
        "languages": ["zh", "yue", "en", "ja", "ko"],
        "auto_detect": False,
        "key_group": "aliyun",    # ★ 不加这条，用户得把同一把 Key 贴两遍
    },
    # ★ 故意**不注册**小米 ASR（代码在 services/providers/asr_chat_audio.py
    #   里保留了 XiaomiMiMoASR，但这里不放进预设表）：
    #     · 接口只声明 language 支持 auto/zh/en，没有日韩
    #     · 实测 auto 自动识别同样不行：ko 0.286、ja 0.858
    #       （적 미드에서 → 절기 비대에서；ラッシュ→拉致、ミッド→密土）
    #     · V2.5 系列 2026-10-21 下线
    #   放进预设表 = 给用户一个必然出错的选项。有代码但不给选，
    #   比没有更危险（用户会以为「可以选」）。
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
#
#   ★ 2026-10-11 补记：下面这段对比的是 **Qwen vs Hunyuan-MT-7B**。
#     后来接入的 hy-mt2-pro 不在这组对比里，而 mt_eval_3way 的同批 10 句
#     实测它是 0.581 > Qwen 0.422 > Hunyuan-7B 0.362 ——
#     所以「Qwen 社区语言最准」这句话**只在它俩之间成立**，
#     现在选 Qwen 的理由是「更快、且一样不泄漏解释」，不是「最准」。
#     判据见下方 acc 字段（三方同批样本，可横向比）。
#
# they planted spike on A
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
        # ★ v0.3.1：原标签是「推荐·社区语言最准」。前半句还成立（它是默认档），
        #   后半句已被自己的实测推翻 —— mt_eval_3way 同批 10 句里它是**第 2**
        #   （0.422，输给 hy-mt2-pro 的 0.581），而它比第 1 名便宜、还更快。
        #   既然便宜和更快都是真的，就照实说便宜和更快，
        #   不留一句数据已经不支持的「最准」。
        "label": "千问 Qwen2.5-14B（延迟更低·零解释泄漏）",
        "price": "¥1.26 / M tokens",
        # ★ v0.3.1：acc 来自 tests/mt_eval_3way.py（10 句带参考译文，同一批样本），
        #   三方横向可比 —— 见 tencent_hunyuan 下的对照表。
        "acc": "0.422 · 3 方第 2 · 387ms",
        "base_url": "https://api.siliconflow.cn/v1",
        "model": "LoRA/Qwen/Qwen2.5-14B-Instruct",
        # ★ 延迟只在 acc 里报一次（三方同批样本，可横向比）。
        #   原先 note 写 615ms、acc 写 387ms —— 同一个预设两个延迟，
        #   用户没法判断该信哪个。定性的（不泄漏解释、术语靠本地表）留在这里。
        "note": "零解释泄漏。唯一短板：偶发术语误解，靠本地表兜。",
    },
    "siliconflow": {
        "label": "Hunyuan-MT-7B（免费档）",
        "price": "免费",
        "acc": "0.362 · 3 方第 3 · 599ms",
        "base_url": "https://api.siliconflow.cn/v1",
        "model": "tencent/Hunyuan-MT-7B",
        # 延迟同理只在 acc 里报（原先 note 写 3547ms、acc 写 599ms，两处打架）。
        "note": "输入/输出均免费。但 2/10 解释泄漏、「尖刺装置」式书面语。",
    },
    "zhipu": {
        "label": "智谱 GLM-4-Flash（免费·仅故障兜底）",
        "price": "免费",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "model": "glm-4-flash",
        "note": "需单独配智谱 Key。默认不启用。",
    },
    # —— v0.3.0 新增：腾讯混元（TokenHub）——
    # ★ 旧混元平台 2026-06-30 停止售卖、**2026-09-30 全面停服下线**，
    #   现在只能开 TokenHub：https://cloud.tencent.com/product/tokenhub
    #   TokenHub 兼容 OpenAI 协议，所以这个预设就是标准 ChatMT。
    #   计费 ¥1.2 / ¥3.6 每百万 token（输入/输出），新用户有免费额度。
    #   ⚠️ 待确认：Key 格式。资料两种说法 —— 一处说 TokenHub 专用
    #      API Key，另一处说 `{secret_id}:{secret_key}`。照控制台实际
    #      给的来，别照博客。
    "tencent_hunyuan": {
        "label": "腾讯混元 Hy-MT2-Pro（游戏黑话最准·准确率第 1）",
        # ★ 2026-10-10 三方实测（tests/mt_eval_3way.py，10 句带参考译文）
        #     链路                均分    通过   均延迟
        #     腾讯 hy-mt2-pro     0.581   3/10   750ms   ← 本项
        #     硅基 Qwen2.5-14B    0.422   2/10   387ms   ← 现有默认
        #     硅基 Hunyuan-MT-7B  0.362   1/10   599ms
        #
        #   质量比现有默认高 37%，但延迟接近两倍且要花钱。
        #   → 列为**可选档**而非默认：实时字幕对延迟敏感，
        #     而「说人话不说书面语」是用户定的最高优先级 ——
        #     愿意为质量付延迟的人自己切。
        #
        #   具体差距看两例：
        #     ko1 「敌人在中路绕回来」  腾讯 83%（译成「男爵」的对应中文）
        #                               Qwen 33%
        #     yue1「别送，稳住发育」    腾讯 88%   Qwen 75%
        #   但 yue2 腾讯 58% 反而输给 Qwen 92% —— 不是全面领先。
        #
        #   ★ 域名务必核对：tokenhub.tencentmaas.com
        #     差一个 cloud 的那个（tencentcloudmaas）会返回
        #     401「API Key 不存在或签名校验失败」，而报错**不提示**是域名问题。
        "price": "¥0.5 / ¥2 每百万 tokens（一局约 ¥0.001）",
        "acc": "0.581 · 3 方第 1 · 750ms",
        "base_url": "https://tokenhub.tencentmaas.com/v1",
        "model": "hy-mt2-pro",
        "note": "翻译专用模型，游戏黑话用词明显优于通用对话模型。"
                "实测 0.581 vs 千问 0.422，但慢 363ms。"
                "需要 TokenHub 的单个 API Key（sk- 开头）。",
    },
}

# 默认走 Qwen（v0.2.5 起）。旧配置里的 "siliconflow" 仍然有效，
# 不强制改写用户的 mt_preset —— 用户想用免费档就让他用。
DEFAULT_MT_PRESET = "qwen"

# TTS 服务商预设
# ---------------------------------------------------------------------------
# 默认仍是 edge-tts 本地链（不依赖云、零延迟、零成本），
# 云端音色是**可选增强** —— 这条不能变：把默认换成云端等于让所有用户
# 的每次 PTT 都多付一次网络往返，而本地链本来就好用。
# ---------------------------------------------------------------------------
TTS_PRESETS = {
    "local": {
        "label": "本地音色（edge-tts·免费·无延迟）",
        "price": "免费",
        "base_url": "",
        "model": "",
        "provider": "siliconflow_cosy",   # 占位：本地链不走 provider
        "note": "默认档。微软的在线音色接口，通过本机通道返回，"
                "不占用你的云端额度。",
    },
    "siliconflow_cosy": {
        "label": "硅基 CosyVoice2（自然音色）",
        # ★ 2026-10-11 修正：原来写「随 ASR 额度」——**错的**。
        #   CosyVoice 是 TTS，按字符计费，跟 ASR（按秒）不是一个账。
        #   官方 siliconflow.cn/pricing 实测：¥0.05 / 千字符 UTF-8
        #   （国际站 $7.15 / M UTF-8 bytes，同一价格的两种表述）。
        "price": "¥0.05 / 千字符",
        # ★ 这三个字段别删：tts_endpoint()/tts_key() 靠 provider 判定走哪条链
        "base_url": "https://api.siliconflow.cn/v1",
        "model": "FunAudioLLM/CosyVoice2-0.5B",
        "provider": "siliconflow_cosy",
        "note": "音色自然、语气丰富。失败自动回落到本地链。",
    },
    "xiaomi_tts": {
        # —— v0.3.0 新增：小米 MiMo-TTS（2026-10-10 实测）——
        #   en 1523ms / ja 2503ms / zh 1389ms，三种语言全部能解码出有效音频。
        #   ⚠️ 明显比本地链慢（本地链几乎无延迟），所以只做可选档。
        #   ⚠️ 这一路**没有 speed 参数**（文档里没有），语速滑杆对它不生效。
        #   ⚠️ V2.5 系列 2026-10-21 下线，接入前确认型号还有效。
        "label": "小米 MiMo-TTS（三种语言都可用·较慢）",
        "price": "限时免费",
        "base_url": "https://api.xiaomimimo.com/v1",
        "model": "mimo-v2.5-tts",
        "provider": "xiaomi_tts",
        "key_group": "xiaomi",
        "note": "实测英/日/中都能合成。音色 Mia/Chloe/Milo/Dean。"
                "比本地链慢 1~2 秒；没有语速参数。"
                # ★ 时效风险必须标出来：用户选了它，2026-10-21 之后就用不了，
                #   而那时**没有 v2.6-tts 可换**（实测小米 /models 的 TTS 型号
                #   全是 V2.5 系列，V2.6 只有对话模型）。不写在眼前等于埋雷。
                "　⚠ V2.5 系列 2026-10-21 下线，届时需换型号。",
    },
}

DEFAULT_TTS_PRESET = "local"

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

    # ★ v0.3.0 补：浮窗**实际**可见性（区别于 overlay_enabled 那个用户开关）。
    #   之前前端 Styles.jsx / Home.jsx 一直在读 cfg.overlay_visible、
    #   还 patchCfg 写回配置，但 AppConfig **里没有这个字段** ——
    #   值落到 config.json，load() 时被丢掉，再也读不回来。
    #   后果：当前会话里「字样风格」页看得到真实状态，
    #   **一重启就归零**，永远显示成「没显示」。
    #   写它的 Python 侧（api.py 的 _overlay_cfg_payload）一直是好的，
    #   坏的是「读回来」这一段 —— 半截接线最难自己看出来。
    overlay_visible: bool = False

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
    # v0.3.0：划词翻译。在**任何程序**里选中文字后按这个键即可，
    #   不需要本软件在前台。默认 <ctrl>+<alt>+t 而不是 Alt+T ——
    #   Alt+T 会和大量软件的「新建标签页/新建窗口」撞车，
    #   ctrl+alt+t 极少被占用。
    hotkey_select: str = "<ctrl>+<alt>+t"
    # v0.3.0：划词翻译的目标语言。auto = 原文已是中文则翻成英文（发给队友），
    #   否则翻成中文（主方向）。
    select_target: str = "auto"
    # v0.3.0：云端 TTS 选择。默认 local（edge-tts 本地链）——
    #   不改成云端是刻意的：云端每次 PTT 多一次网络往返，
    #   而本地链本来就好用。
    tts_preset: str = "local"
    tts_keys: dict = field(default_factory=dict)

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
        # ★ v0.3.0：tts_keys 走同一套 DPAPI 信封。
        #   漏掉这一行的话，新加的 TTS Key 会**明文落盘** ——
        #   而本项目的硬规矩是「凭据绝不进版本库 / 不落明文」。
        #   表现上看不出异常（功能正常），只有翻配置文件才发现。
        cfg.tts_keys = _decrypt_keys(getattr(cfg, "tts_keys", {}) or {})

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
                # ★ v0.3.0：TTS Key 同样加密（配对 load() 里那行）
                d["tts_keys"] = _encrypt_keys(
                    getattr(self, "tts_keys", {}) or {})
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
        # ★ v0.3.0：key_group 回落。
        #   同一家服务商的**两条通路**（阿里千问的兼容端点与 DashScope
        #   原生端点）base_url 不同，按 base_url 回落会漏掉它们，
        #   于是用户切到 dashscope 预设就拿到空串 → **ASR 静默失效**，
        #   界面表现只是「识别不出」，不报任何错（与本函数注释里
        #   记的那次 siliconflow/sensevoice 事故完全同型）。
        grp = ASR_PRESETS.get(self.asr_preset, {}).get("key_group", "")
        if grp:
            for name, val in (self.asr_keys or {}).items():
                if val and ASR_PRESETS.get(name, {}).get("key_group") == grp:
                    return val
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

    # ---------- TTS ----------
    def tts_endpoint(self) -> tuple[str, str, str]:
        """返回 (base_url, model, provider_key)。

        `local` 档返回空 base_url —— 调用方据此走本地 edge-tts 链，
        不发任何网络请求。
        """
        name = getattr(self, "tts_preset", DEFAULT_TTS_PRESET)
        p = TTS_PRESETS.get(name)
        if p is None:
            p = TTS_PRESETS[DEFAULT_TTS_PRESET]
        return p["base_url"], p["model"], p["provider"]

    def tts_key(self) -> str:
        """取当前 TTS 档的 Key。

        `local` 档返回空串 —— 本地链不需要 Key。
        其余档先按预设名取，再按 `key_group` 回落（同 asr_key 的理由：
        同一家服务商的多个档位共用一把 Key，切过去不该拿到空串）。
        """
        name = getattr(self, "tts_preset", DEFAULT_TTS_PRESET)
        if name == "local":
            return ""
        keys = getattr(self, "tts_keys", {}) or {}
        k = keys.get(name, "")
        if k:
            return k
        grp = TTS_PRESETS.get(name, {}).get("key_group", "")
        if grp:
            for other, val in keys.items():
                if val and TTS_PRESETS.get(other, {}).get("key_group") == grp:
                    return val
        return ""

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
