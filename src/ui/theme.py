# -*- coding: utf-8 -*-
# 作者: cing  ·  https://github.com/cingzz
# 许可: GPL-3.0 + 商业授权（闭源/商用需向作者申请授权），见 LICENSE 与 LICENSE-COMMERCIAL.md
#
"""深色主题 v2：以《无畏契约》官方视觉语言为根基的设计令牌 + 全局 QSS。

底色 #0F1923 深海军蓝 / 文字 #ECE8E1 米白 / 主 CTA #FF4655 标志红 /
调节与焦点 #18E4B7 青绿 / 状态语义：绿=运行中 黄=识别中 红=危险。
拉丁展示字 Bahnschrift（Win10/11 自带 DIN 风，Valorant 同气质），
中文正文 Microsoft YaHei UI。

性能纪律：QSS 不用 `*` 全局选择器（任何 setStyleSheet 都会引发全窗口
重铺 → 滚动卡、按钮迟滞）；字体经 QApplication.setFont 下发，QSS 只管
颜色与边框，且只在启动时设置一次。
"""
from __future__ import annotations

# ---- 设计令牌 ----
BG0 = "#0F1923"        # 窗口底（深海军蓝）
BG1 = "#1A2733"        # 卡片
BG2 = "#223140"        # 输入框/次级
BG3 = "#2E4154"        # 悬停
STROKE = "#3B4C5C"     # 描边
TEXT = "#ECE8E1"       # 主文字（米白）
MUTED = "#8FA0AD"      # 次级文字
ACCENT = "#FF4655"     # 主强调（标志红）：主动作/危险
ACCENT_HOVER = "#FF5A68"
ACCENT_PRESS = "#D93A48"
ACCENT2 = "#18E4B7"    # 次强调（青绿）：焦点/调节/选中
OK = "#3DD68C"         # 运行中/成功
WARN = "#F5A524"       # 识别中/注意
DANGER = "#FF4655"
RADIUS = 4             # 锐角扁平（Valorant 语言：小圆角+直角切边）

FONT_FAMILY = "Microsoft YaHei UI"   # 中文正文
FONT_DISPLAY = "Bahnschrift"         # 拉丁展示字（品牌/大数字/按钮）

QSS = f"""
QWidget {{ background: {BG0}; color: {TEXT}; font-size: 13px; }}
QMainWindow, QWidget#Root {{ background: {BG0}; }}
QWidget#Side {{ background: {BG1}; border-right: 1px solid {STROKE}; }}
QWidget#Card {{ background: {BG1}; border: 1px solid {STROKE}; border-radius: {RADIUS}px; }}
QWidget#CardInner {{ background: {BG2}; border: none; border-radius: {RADIUS}px; }}
QWidget#Hero {{ background: {BG1}; border: 1px solid {STROKE}; border-radius: {RADIUS}px; }}
QWidget#PreviewBox {{ background: {BG2}; border: 1px dashed {STROKE}; border-radius: {RADIUS}px; }}

QLabel {{ background: transparent; color: {TEXT}; font-size: 13px; }}
QLabel#H1 {{ font-size: 21px; font-weight: 700; }}
QLabel#H2 {{ font-size: 15px; font-weight: 600; }}
QLabel#Muted {{ color: {MUTED}; font-size: 12px; }}
QLabel#Brand {{ font-family: "{FONT_DISPLAY}"; font-size: 17px; font-weight: 700;
    letter-spacing: 3px; color: {TEXT}; }}
QLabel#Chip {{ background: {BG2}; border: 1px solid {STROKE}; border-radius: 3px;
    color: {MUTED}; font-size: 12px; padding: 2px 8px; }}
QLabel#ChipOn {{ background: rgba(61,214,140,26); border: 1px solid {OK};
    border-radius: 3px; color: {OK}; font-size: 12px; padding: 2px 8px; }}

QPushButton {{ background: {BG2}; color: {TEXT}; border: 1px solid {STROKE};
    border-radius: {RADIUS}px; padding: 7px 16px; font-size: 13px; }}
QPushButton:hover {{ background: {BG3}; border-color: {MUTED}; }}
QPushButton:pressed {{ background: {BG0}; }}
QPushButton:focus {{ border-color: {ACCENT2}; }}
QPushButton:disabled {{ background: {BG1}; color: {MUTED}; border-color: {STROKE}; }}
QPushButton#Primary {{ background: {ACCENT}; color: #140A0E; font-weight: 700;
    border: none; }}
QPushButton#Primary:hover {{ background: {ACCENT_HOVER}; }}
QPushButton#Primary:pressed {{ background: {ACCENT_PRESS}; }}
QPushButton#Primary:disabled {{ background: {BG3}; color: {MUTED}; }}
QPushButton#Ghost {{ background: transparent; }}
QPushButton#Danger {{ background: transparent; color: {DANGER}; border-color: {DANGER}; }}
QPushButton#Danger:hover {{ background: rgba(255,70,85,36); }}
QPushButton#Nav {{ background: transparent; color: {MUTED}; border: none;
    border-radius: {RADIUS}px; padding: 9px 14px; text-align: left; font-size: 13px; }}
QPushButton#Nav:hover {{ background: {BG2}; color: {TEXT}; }}
QPushButton#Nav:checked {{ background: {BG2}; color: {TEXT}; font-weight: 600;
    border-left: 3px solid {ACCENT}; }}
QPushButton#Seg {{ background: transparent; border: 1px solid {STROKE};
    border-radius: {RADIUS}px; padding: 6px 14px; color: {MUTED}; }}
QPushButton#Seg:hover {{ color: {TEXT}; border-color: {MUTED}; }}
QPushButton#Seg:checked {{ background: {BG2}; color: {TEXT}; border-color: {ACCENT2}; }}

QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
    background: {BG2}; color: {TEXT}; border: 1px solid {STROKE};
    border-radius: {RADIUS}px; padding: 6px 10px; font-size: 13px;
    selection-background-color: {ACCENT2}; selection-color: {BG0};
}}
QLineEdit:focus, QComboBox:focus {{ border-color: {ACCENT2}; }}
QLineEdit:disabled, QComboBox:disabled {{ color: {MUTED}; background: {BG1}; }}
QComboBox::drop-down {{ border: none; width: 24px; }}
QComboBox::down-arrow {{ image: none; border-left: 4px solid transparent;
    border-right: 4px solid transparent; border-top: 5px solid {MUTED};
    margin-right: 8px; }}
QComboBox QAbstractItemView {{ background: {BG1}; color: {TEXT};
    border: 1px solid {STROKE}; selection-background-color: {BG3};
    selection-color: {TEXT}; outline: 0; }}

QSlider {{ background: transparent; min-height: 22px; }}
QSlider::groove:horizontal {{ height: 4px; background: {STROKE}; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {ACCENT2}; border-radius: 2px; }}
QSlider::handle:horizontal {{ width: 12px; height: 12px; margin: -4px 0;
    background: {TEXT}; border-radius: 2px; }}
QSlider::handle:horizontal:hover {{ background: {ACCENT2}; }}
QSlider:disabled::sub-page:horizontal {{ background: {STROKE}; }}

QCheckBox {{ background: transparent; color: {TEXT}; font-size: 13px; spacing: 7px; }}
QCheckBox::indicator {{ width: 15px; height: 15px; border: 1px solid {STROKE};
    border-radius: 3px; background: {BG2}; }}
QCheckBox::indicator:hover {{ border-color: {ACCENT2}; }}
QCheckBox::indicator:checked {{ background: {ACCENT2}; border-color: {ACCENT2}; }}

QProgressBar {{ background: {BG2}; border: 1px solid {STROKE}; border-radius: 2px;
    height: 10px; text-align: center; color: transparent; }}
QProgressBar::chunk {{ background: {OK}; }}

QScrollArea {{ border: none; background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 8px; margin: 0; }}
QScrollBar::handle:vertical {{ background: {STROKE}; border-radius: 4px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {MUTED}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
QScrollBar:horizontal {{ background: transparent; height: 8px; margin: 0; }}
QScrollBar::handle:horizontal {{ background: {STROKE}; border-radius: 4px; min-width: 30px; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{ background: transparent; }}

QMenu {{ background: {BG1}; color: {TEXT}; border: 1px solid {STROKE}; }}
QMenu::item {{ padding: 6px 24px; }}
QMenu::item:selected {{ background: {BG3}; }}
QMenu::separator {{ height: 1px; background: {STROKE}; margin: 4px 8px; }}

QToolTip {{ background: {BG2}; color: {TEXT}; border: 1px solid {STROKE};
    padding: 4px 8px; font-size: 12px; }}

QListWidget, QTreeWidget {{ background: {BG1}; border: 1px solid {STROKE};
    border-radius: {RADIUS}px; }}
QListWidget::item:selected {{ background: {BG3}; color: {TEXT}; }}
"""


def status_qss(color: str) -> str:
    """状态灯圆点样式。"""
    return (f"background:{color}; border-radius:7px; min-width:14px; max-width:14px;"
            f"min-height:14px; max-height:14px; border: 2px solid {BG1};")
