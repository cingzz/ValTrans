# -*- coding: utf-8 -*-
"""应用图标 —— **唯一**绘制实现（.ico / 托盘 / Qt 兜底都从这里出）。

为什么必须只有一份
==================
改版前有三份各画各的：
  · assets/icon.ico        绿圆角方块 + 黑 V（用户：「太丑了，绿色的」）
  · host.py `_icon_img`     天蓝方块 + 手绘 V（pystray 用）
  · app.py  `make_icon`     又画一遍（Qt 兜底界面用）
三份长得不一样——这正是「同一个判断只能有一份实现」。
现在只保留这一个 `render()`，别处**只许读，不许画**。

设计依据（NexBox 界面设计报告）
==============================
为什么不再用「字母 V」
  · V 在 16x16 托盘尺寸下笔画粘连成一坨，实测截图里就是一团黑
  · 字母不传达任何功能信息
改成**声波**：三根高度不等的白色圆角竖条
  · 「实时**语音**翻译」—— 声波直接说明它处理什么
  · 16x16 下三根 3px 宽的竖条依然分得开（比任何细节造型都稳）
配色与材质沿用 UI 设计系统，保证图标和窗口是一套东西：
  · 主色 `--primary` = #60A5FA（与界面、按钮同一个蓝）
  · 内高光（报告 §3.2「贡献了一半的玻璃厚度感」）
  · 描边光（报告 §3.3，160° 斜向反光，只画 1px 环）
"""
from __future__ import annotations

import os

# 与 webui/src/tokens.css 的 --primary 保持一致。
# 为什么不直接读 tokens.css：那是 CSS，图标要在**打包后**也能生成，
# 不能依赖前端构建产物。改主色时这两处要一起改 —— audit_app_icon 守着。
PRIMARY = (96, 165, 250)          # #60A5FA
PRIMARY_DEEP = (59, 130, 246)     # #3B82F6


def render(size: int = 256):
    """画一张 size x size 的 RGBA 图标。

    全程用 **4 倍超采样**再缩小：直接在小尺寸上画圆角，
    边缘会出现明显锯齿（托盘 16x16 时尤其难看）。
    """
    from PIL import Image, ImageDraw

    S = 4                      # 超采样倍数
    N = size * S
    img = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    def sc(v):                 # 设计稿按 256 画，这里线性放大
        return v * N / 256.0

    # ── 底：圆角方块 + 135° 蓝渐变 ────────────────────────────────────
    box = [sc(8), sc(8), N - sc(8), N - sc(8)]
    grad = Image.new("RGBA", (N, N))
    gd = ImageDraw.Draw(grad)
    for y in range(N):
        t = y / max(1, N - 1)                 # 沿对角线插值 = 135° 观感
        col = tuple(int(PRIMARY[i] + (PRIMARY_DEEP[i] - PRIMARY[i]) * t)
                    for i in range(3))
        gd.line([(0, y), (N, y)], fill=col + (255,))
    mask = Image.new("L", (N, N), 0)
    ImageDraw.Draw(mask).rounded_rectangle(box, radius=sc(52), fill=255)
    img.paste(grad, (0, 0), mask)

    # ── 内高光（报告 §3.2）：顶部一道白，制造玻璃厚度 ──────────────────
    # ★ 必须是**平滑渐变**。第一版我画成一个 150px 高的圆角矩形，
    #   底边在图中间留下一道明显的硬横线（截图里看得见），像贴了条胶带。
    #   这里按行算 smoothstep 衰减，落到 0 就没有边了。
    hl = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    hd = ImageDraw.Draw(hl)
    span = sc(190)
    for y in range(min(N, int(span))):
        t = y / span
        a = int(62 * (1.0 - t) ** 2)          # 平方衰减，顶部最亮
        if a <= 0:
            continue
        hd.line([(0, y), (N, y)], fill=(255, 255, 255, a))
    img.alpha_composite(Image.composite(
        hl, Image.new("RGBA", (N, N), (0, 0, 0, 0)), mask))

    # ── 描边光（报告 §3.3）：160° 斜向，只画 1px 环 ────────────────────
    d.rounded_rectangle([box[0] + sc(1), box[1] + sc(1),
                         box[2] - sc(1), box[3] - sc(1)],
                        radius=sc(51), outline=(255, 255, 255, 46),
                        width=max(1, int(sc(2))))

    # ── 主标记：三根声波竖条 ──────────────────────────────────────────
    # 尺寸是按 **16px 托盘尺寸倒推**的，不是看着好看随手定的：
    #   竖条宽 32/256 -> 16px 图里正好 2px（1px 会糊）
    #   条间距 30/256 -> 约 2px
    # 第一版用了 20 宽 / 14 间距，**三根直接连成一坨**（见截图），
    # 说明「先画好看、再想小尺寸」这个顺序是错的。
    bars = ((50, 96, 160), (112, 64, 192), (174, 96, 160))
    for x0, y0, y1 in bars:
        w = sc(32)
        d.rounded_rectangle([sc(x0), sc(y0), sc(x0) + w, sc(y1)],
                            radius=w / 2.0, fill=(255, 255, 255, 255))

    return img.resize((size, size), Image.LANCZOS)


def render_ico(path: str, sizes=(16, 24, 32, 48, 64, 128, 256)):
    """多尺寸 ICO（Windows 资源管理器/任务栏/托盘按需挑帧）。"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    base = render(256)
    base.save(path, format="ICO",
              sizes=[(s, s) for s in sizes])
    return path


if __name__ == "__main__":
    import sys
    out = sys.argv[1] if len(sys.argv) > 1 else "assets/icon.ico"
    print("已生成", render_ico(out))