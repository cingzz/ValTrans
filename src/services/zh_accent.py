# -*- coding: utf-8 -*-
# 作者: cing  ·  https://github.com/cingzz
# 许可: GPL-3.0 + 商业授权（闭源/商用需向作者申请授权），见 LICENSE 与 LICENSE-COMMERCIAL.md
#
"""中文语音黑话纠错：ASR 把游戏黑话听成同音的日常词。

真机 实测（全部真实踩到）：
    「奶妈别送」    -> 「妈妈别送」   （奶妈=治疗位/贤者 Sage）
    「尚勃勒别单摸了」-> 「上播了别单播了」（尚勃勒=Chamber；单摸=一人走）
判据哲学与 accent.py（英文口音纠错）一致：**有证据才改**——
整句必须先命中「游戏祈使语境」，只动白名单里的整词映射；
表里没有的一律不动（宁缺毋滥），绝不整句重写。
"""
from __future__ import annotations

import re

_CJK = re.compile(r"[\u4e00-\u9fff]")

# (语境门槛正则, [(错, 对), ...], 依据)
_RULES = [
    (re.compile(r"别送|别浪|别送包|去送"),
     [("妈妈", "奶妈")],
     "游戏语音里「妈妈别送」只可能是奶妈（治疗位/贤者 Sage）——用户实测"),
    (re.compile(r"单播"),
     [("单播", "单摸")],
     "「单播」是网络术语，游戏语音里指单摸（一个人绕后走）——用户实测"),
    (re.compile(r"上播了?[，,。]?\s*别单|上播啦[，,。]?\s*别单"),
     [("上播了", "尚勃勒"), ("上播啦", "尚勃勒")],
     "尚勃勒(Chamber)谐音被听成上播了；仅当后面紧跟『别单…』祈使句才纠"),
]


def fix_zh_slang(text: str) -> str:
    """中文 ASR 结果的黑话纠错。无语境证据不改动，异常不外抛。"""
    try:
        if not text or not _CJK.search(text):
            return text
        out = text
        for gate, pairs, _why in _RULES:
            if not gate.search(out):
                continue
            for wrong, right in pairs:
                if wrong in out:
                    out = out.replace(wrong, right)
        return out
    except Exception:
        return text


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    for t in ["妈妈别送", "妈妈我爱你", "上播了，别单播了", "我要上播了",
              "单播是什么", "钱包别单摸了"]:
        print(f"{t!r} -> {fix_zh_slang(t)!r}")
