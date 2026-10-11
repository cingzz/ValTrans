# -*- coding: utf-8 -*-
# 作者: cing  ·  https://github.com/cingzz
# 许可: GPL-3.0 + 商业授权（闭源/商用需向作者申请授权），见 LICENSE 与 LICENSE-COMMERCIAL.md
#
"""网络安全模块：统一 HTTP 出口校验。

规则（项目安全约束）：
- **仅允许 https**（v0.3.1 起收紧，此前 http/https 都放行）；
- 发请求前校验 host，拒绝 localhost、环回、私有与保留地址。
所有云端请求必须经 `safe_client()` 创建的客户端发出。

★ v0.3.1：为什么把 http 拿掉（外部审计 MiMo 7.1，八家里只有它报了这条）
------------------------------------------------------------------------
这条链路上跑的每一个请求都带：

    Authorization: Bearer <用户的 API Key>

而 http 是**明文**传输。在咖啡厅 / 宿舍 / 网吧 / 任何共享 Wi-Fi 上，
同一网段的人用抓包工具就能直接看到 Key 本体。拿到 Key 就能拿走额度 ——
腾讯 TokenHub 与阿里百炼都是按量计费。

之前放行 http 的理由大概率是「万一有人要接自建服务」，
但代价是**所有人的 Key 都能被同网段嗅探**，收益只是极少数人的方便。
需要自建 http 服务的用户完全可以自己加一行，不该让默认路径替所有人冒险。

★ 残留风险要如实说清：DNS TOCTOU 没有根治
------------------------------------------
`validate_url` 解析 DNS 校验 IP，随后 httpx 发请求时**会再解析一次**。
攻击者若控制 DNS，可以让第一次返回公网 IP（通过校验）、
第二次返回内网 IP，从而绕过 SSRF 防护。

这里**没有**用「缓存 DNS 结果」来「修」它，因为那恰恰会把问题变严重：
窗口从毫秒级被拉长到整个 TTL 期间。**为了看起来更安全而引入更大的洞，
比不修更糟**。

真要根治需要把连接绑到已校验的 IP（保留原始 Host/SNI），
属于一次不小的改造，收益与本项目的威胁模型（个人桌面工具、
不是多租户服务端）不匹配，因此记在这里当作**已知未修**，
而不是假装它不存在。"""
from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

import threading

import httpx

# ★ 只有 https。http 不是「不太安全」，是**把 Key 明文广播出去**。
_ALLOWED_SCHEMES = {"https"}


class DisallowedURLError(ValueError):
    """URL 未通过安全校验。"""


def validate_url(url: str) -> str:
    """校验并返回规范化 URL；不合法则抛 DisallowedURLError。"""
    if not url or not isinstance(url, str):
        raise DisallowedURLError("URL 为空")
    parsed = urlparse(url.strip())
    if parsed.scheme not in _ALLOWED_SCHEMES:
        raise DisallowedURLError(
            "仅允许 https（http 会把 API Key 明文发出去），收到: %r。"
            "如果你要接自建 http 服务，请先给它套一层 https 或反代。"
            % (parsed.scheme,))
    host = parsed.hostname
    if not host:
        raise DisallowedURLError("URL 缺少主机名")
    # 域名先做字面检查（localhost / 以 .local 结尾等）
    literal = host.lower().rstrip(".")
    if literal in {"localhost", "local", "broadcasthost"} or literal.endswith(".local"):
        raise DisallowedURLError(f"拒绝本地主机: {host}")
    # 解析为 IP 后逐个检查是否环回/私有/保留
    try:
        infos = socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80),
                                   proto=socket.IPPROTO_TCP)
    except socket.gaierror as e:
        raise DisallowedURLError(f"主机解析失败: {host} ({e})")
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if (ip.is_loopback or ip.is_private or ip.is_link_local or ip.is_reserved
                or ip.is_multicast or ip.is_unspecified):
            raise DisallowedURLError(f"拒绝私有/保留地址: {host} -> {ip}")
    return url.strip()


def safe_client(timeout: float = 15.0, **kwargs) -> httpx.Client:
    """创建带出站校验事件的 httpx 客户端。"""
    def _guard(request: httpx.Request):
        validate_url(str(request.url))
    # request hook 在每个请求前执行
    return httpx.Client(timeout=timeout, event_hooks={"request": [_guard]}, **kwargs)


# ---------------------------------------------------------------------------
# 连接池（v0.2.4 新增）
# ---------------------------------------------------------------------------
# 每条字幕都新建 httpx.Client = 每条都重走 DNS + TCP + TLS 握手。
# 实测冷连接 11982ms vs 复用 691ms，差的是握手不是推理。
# 这里按 timeout 缓存长期复用的 Client，走 keep-alive。
_POOL: dict = {}
_POOL_LOCK = threading.Lock()


def pooled_client(timeout: float = 15.0, **kwargs) -> httpx.Client:
    """返回可长期复用的安全客户端（热路径用）。

    与 safe_client 的区别：safe_client 每次新建（一次性场景/测试用），
    pooled_client 走 keep-alive 连接池（实时字幕用）。

    kwargs 里若含 headers/base_url 等与连接相关的参数，会强制新建，
    避免把带鉴权的客户端缓存串味。
    """
    if kwargs.get("headers") or kwargs.get("auth"):
        return safe_client(timeout=timeout, **kwargs)

    # ★ v0.2.16：缓存 key 必须含**全部** kwargs——只按 timeout 缓存时，
    #   带其它参数的调用方会在缓存命中时被静默忽略参数（首建配置生效）。
    key = (float(timeout),
           tuple(sorted((k, repr(v)) for k, v in kwargs.items())))
    with _POOL_LOCK:
        cl = _POOL.get(key)
        if cl is None or getattr(cl, "is_closed", False):
            cl = safe_client(timeout=timeout, **kwargs)
            _POOL[key] = cl
        return cl


def close_pool() -> None:
    """退出时关闭所有池化连接（release 会调）。"""
    with _POOL_LOCK:
        for cl in _POOL.values():
            try:
                cl.close()
            except Exception:
                pass
        _POOL.clear()


