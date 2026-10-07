# -*- coding: utf-8 -*-
# 作者: cing  ·  https://github.com/cingzz
# 许可: GPL-3.0 + 商业授权（闭源/商用需向作者申请授权），见 LICENSE 与 LICENSE-COMMERCIAL.md
#
"""网络安全模块：统一 HTTP 出口校验。

规则（项目安全约束）：
- 仅允许 http/https；
- 发请求前校验 host，拒绝 localhost、环回、私有与保留地址。
所有云端请求必须经 `safe_client()` 创建的客户端发出。
"""
from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

import threading

import httpx

_ALLOWED_SCHEMES = {"http", "https"}


class DisallowedURLError(ValueError):
    """URL 未通过安全校验。"""


def validate_url(url: str) -> str:
    """校验并返回规范化 URL；不合法则抛 DisallowedURLError。"""
    if not url or not isinstance(url, str):
        raise DisallowedURLError("URL 为空")
    parsed = urlparse(url.strip())
    if parsed.scheme not in _ALLOWED_SCHEMES:
        raise DisallowedURLError(f"仅允许 http/https，收到: {parsed.scheme!r}")
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


