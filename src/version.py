# -*- coding: utf-8 -*-
# 作者: cing  ·  https://github.com/cingzz
# 许可: GPL-3.0 + 商业授权（闭源/商用需向作者申请授权），见 LICENSE 与 LICENSE-COMMERCIAL.md
#
"""版本号唯一来源。

发布前只需改这里一处：
  1. 本文件 VERSION
  2. packaging/setup.iss 的 #define AppVersion（ISCC 不读 Python，无法自动同步，
     校验脚本 tests/verify_src.py 会比对两者，不一致即报错）
"""
VERSION = "0.2.22"