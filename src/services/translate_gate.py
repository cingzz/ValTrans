# -*- coding: utf-8 -*-
# 作者: cing  ·  https://github.com/cingzz
# 许可: GPL-3.0 + 商业授权（闭源/商用需向作者申请授权），见 LICENSE 与 LICENSE-COMMERCIAL.md
#
"""语种闸门：这个句子该不该进翻译链。

用户铁律（2026-10-03）
--------------------
    「永远要记住，别人说外文，你要翻译成中文，
      而不是别人说中文你翻译成中文
      如果别人说中文，你完全可以不用翻译照抄」

不做闸门的实际故障（可复现）
------------------------------
    队友说中文「他们下包了」
      -> 本地表查不到 -> 云端做 zh->zh 翻译
      -> 输出「他们放置了包」这类改写，凭空制造错误
    队友说中文「注意中路」
      -> 云端可能返回「请注意中间的道路」

中文进翻译链就是自找麻烦，所以入口就拦掉。

阈值为什么取 0.34 而不是 0.5
---------------------------
游戏语音很短，「中路」这种 2 字词若分母算上标点/空格会被拉到 0.5；
而「他们下包了，注意」这类混排又需要留余量。0.34 是实测折中：
低于它判外语（保护日语音译里的汉字），高于它判中文（放行短词）。
"""

from __future__ import annotations

import re

# 中文汉字（含扩展 A）
_CJK = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf]")
# 日文假名（平假名 + 片假名）
_KANA = re.compile(r"[\u3040-\u309f\u30a0-\u30ff]")
# 韩文
_HANGUL = re.compile(r"[\uac00-\ud7af\u1100-\u11ff\u3130-\u318f]")

DEFAULT_ZH_RATIO = 0.34


def cjk_ratio(text: str) -> float:
    """汉字占比（去掉空白与标点后算）。"""
    s = re.sub(r"[\s\W_]+", "", text or "", flags=re.UNICODE)
    if not s:
        return 0.0
    return len(_CJK.findall(s)) / len(s)


def has_kana(text: str) -> bool:
    return bool(_KANA.search(text or ""))


def has_hangul(text: str) -> bool:
    return bool(_HANGUL.search(text or ""))


# 粤语特征字：这些字基本只出现在粤语书面语里（唔=不，嘅=的，啲=些，
# 乜=什么，冇=没有，喺=在，咁=这样，嚟=来，佢=他，咗=了，嗰=那）。
# 粤语全汉字，会被汉字占比判成中文而照抄；产品决策（2026-10-03）：
# 队友说粤语也要翻成普通话，所以含特征字一律**判外语**、进翻译链。
#
# v0.2.11 修正：原来粤语判定只写在 should_translate 里，
# 于是 looks_chinese('唔好送') 返回 True 而 should_translate 返回 True ——
# **两个公开函数给相反答案**。功能上靠 should_translate 兜住了，
# 但这是个埋雷的 API 设计：将来任何人（或任何测试）单独用 looks_chinese
# 判断，都会得出「这是中文、该照抄」的错误结论。
# 现在统一到 looks_chinese 里判定，should_translate 只做薄封装。
_YUE_MARK = re.compile(r"[唔嘅啲乜冇喺咁嚟攞佢咗嗰]")


def is_cantonese(text: str) -> bool:
    """是否含粤语特征字（含即判粤语）。"""
    return bool(_YUE_MARK.search(text or ""))


def looks_chinese(text: str, threshold: float = DEFAULT_ZH_RATIO) -> bool:
    """判断输入是否已经是**普通话**（= 该照抄、不该进翻译链）。

    刻意不把「含少量汉字」判为中文 —— 日语音译里汉字假名混排很常见，
    那必须走翻译。有假名/韩文一律判外语。

    ⚠ v0.2.11：粤语**不算**中文（虽然全是汉字）—— 队友说粤语要翻成普通话，
    所以 looks_chinese 对粤语返回 False。这样本函数与 should_translate
    结论永远一致，不会再出现「一个说照抄一个说要翻」的埋雷设计。
    """
    t = (text or "").strip()
    if not t:
        return False
    if has_kana(t):          # 日语，不是中文
        return False
    if has_hangul(t):        # 韩文，不是中文
        return False
    if is_cantonese(t):      # 粤语全汉字，但要翻成普通话 -> 判外语
        return False
    return cjk_ratio(t) >= threshold


def should_translate(text: str, target: str) -> bool:
    """该不该翻译。target=zh 且原文已是普通话 -> 不该翻。"""
    if target != "zh":
        return True
    return not looks_chinese(text)