# -*- coding: utf-8 -*-
# 作者: cing  ·  https://github.com/cingzz
# 许可: GPL-3.0 + 商业授权（闭源/商用需向作者申请授权），见 LICENSE 与 LICENSE-COMMERCIAL.md
#
"""检查更新 —— 拉 GitHub Releases，拿安装包下载地址。

需求
> 「软件里面应该有一个『检查更新』选项，就是去拉取我们 GitHub 上的仓库，
>   看看有没有更新，有更新就把软件更新了。」

为什么走 Releases 而不是 raw 文件
---------------------------------
词库仓库（valtrans-lexicon）走 git pull 就够了，但**软件本体**不能：
安装包 60MB，每台电脑 clone 整个历史没意义，而且 Windows 上
不能靠 git 自动替换正在运行的 exe。

GitHub Releases 的好处：
  · 一次发版一个 tag，对应一个安装包，天然版本化
  · `/releases/latest` 是**稳定地址**，不用维护「最新版本号」，
    以后改版本号不用改代码
  · 下载走 CDN，国内也能下

版本比较：语义化版本，**只比 release/pre-release 的版本号**，
不猜发布日期（发布日期会因为补发/重发乱掉）。

**不自动下载、不自动安装。**
自动更新必须让用户看到「哪个版本、变了什么、多大文件」再点确认 ——
静默下载并替换一个 60MB 的 exe 是所有软件最招人烦的行为，
而且这里还涉及签名问题（见下）。
"""
from __future__ import annotations

import json
import os
import re

import httpx

from ..core.security import safe_client

API = "https://api.github.com/repos/{repo}/releases/latest"
DOWNLOAD_PAGE = "https://github.com/{repo}/releases/latest"

# ★ v0.2.19：大陆直连 GitHub 经常超时。词库仓库（我们自己的）在 jsdelivr
#   CDN 有镜像且国内可达，放一份 latest.json 兼做「更新检查兜底」：
#   GitHub API 失败 → 读 CDN 上的 {version,url,notes}。
FALLBACK_LATEST = [
    "https://fastly.jsdelivr.net/gh/cingzz/valtrans-lexicon@main/latest.json",
    "https://cdn.jsdelivr.net/gh/cingzz/valtrans-lexicon@main/latest.json",
]

TIMEOUT = 15

# 提示用户核对哈希（发布页随包附《发布校验-<版本>.txt》）
SHA_HINT = "。下载后请核对 SHA256（发布页附校验文件）"


def _get(url: str) -> bytes:
    # ★ v0.2.16：统一走 security.safe_client（项目约束：所有出站请求
    #   必须经安全模块；此前这里是裸 urllib，绕过了出站校验）
    with safe_client(timeout=TIMEOUT) as client:
        r = client.get(url, headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "ValTrans",
            "X-GitHub-Api-Version": "2022-11-28",
        })
        r.raise_for_status()
        return r.content


def parse_version(v: str) -> tuple:
    """'0.2.11' -> (0, 2, 11)。非数字部分忽略。"""
    nums = re.findall(r"\d+", (v or "").strip().lstrip("vV"))
    out = tuple(int(x) for x in nums[:3])
    return out + (0,) * (3 - len(out))


def is_newer(remote: str, local: str) -> bool:
    return parse_version(remote) > parse_version(local)


def check(repo: str = "cingzz/ValTrans", local_version: str = "") -> dict:
    """检查更新。

    返回：``{ok, has_update, remote, latest_url, notes, assets[], msg}``

    绝不抛异常 —— 网络不通/仓库不存在/限流都要如实回报，
    不能让「检查更新」这个按钮把设置页搞崩。
    """
    out = {"ok": False, "has_update": False, "remote": "", "local": local_version,
           "latest_url": "", "notes": "", "assets": [], "msg": ""}
    if not local_version:
        from ..version import VERSION
        local_version = VERSION
        out["local"] = local_version
    try:
        raw = _get(API.format(repo=repo))
        data = json.loads(raw.decode("utf-8", "replace"))
    except httpx.HTTPStatusError as e:
        code = e.response.status_code
        out["msg"] = {403: "请求被限流或仓库是私有的",
                      404: "还没发布第一个 Release（去 Releases 页点 New release）"
                      }.get(code, f"GitHub 返回 {code}") + SHA_HINT
        return out
    except Exception:
        # ★ v0.2.19：GitHub 直连失败 → 走 CDN 兜底（词库仓库的 latest.json）
        for u in FALLBACK_LATEST:
            try:
                raw = _get(u)
                fb = json.loads(raw.decode("utf-8", "replace"))
                tag = str(fb.get("version", "")).strip()
                if not tag:
                    continue
                out["ok"] = True
                out["remote"] = tag.lstrip("vV")
                out["latest_url"] = fb.get("url") or DOWNLOAD_PAGE.format(repo=repo)
                out["notes"] = (fb.get("notes") or "").strip()[:1500]
                out["has_update"] = is_newer(out["remote"], local_version)
                out["msg"] = (f"发现新版本 v{out['remote']}（当前 v{local_version}）"
                              if out["has_update"] else f"已是最新（v{local_version}）"
                              ) + "（CDN 通道）" + SHA_HINT
                return out
            except Exception:
                continue
        out["msg"] = ("连不上 GitHub（大陆网络常见）。请手动到发布页查看新版本，"
                      "下载后务必核对 SHA256" + SHA_HINT)
        return out

    tag = (data.get("tag_name") or "").strip()
    if not tag:
        out["msg"] = "Release 没有 tag，格式不对"
        return out
    out["ok"] = True
    out["remote"] = tag.lstrip("vV")
    out["latest_url"] = data.get("html_url") or DOWNLOAD_PAGE.format(repo=repo)
    out["notes"] = (data.get("body") or "").strip()[:1500]
    for a in data.get("assets") or []:
        out["assets"].append({
            "name": a.get("name", ""),
            "size_mb": round((a.get("size") or 0) / 1048576, 1),
            "url": a.get("browser_download_url", ""),
            "downloads": a.get("download_count", 0),
        })
    out["has_update"] = is_newer(out["remote"], local_version)
    if out["has_update"]:
        out["msg"] = f"发现新版本 v{out['remote']}（当前 v{local_version}）"
    else:
        out["msg"] = f"已是最新（v{local_version}）"
    out["msg"] += SHA_HINT
    return out


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    print("检查更新自检")
    print("=" * 62)
    print("版本比较：")
    for a, b in [("0.2.11", "0.2.11"), ("0.2.12", "0.2.11"),
                 ("0.3.0", "0.2.11"), ("1.0.0", "0.2.11"),
                 ("0.2.9", "0.2.11"), ("v0.3.0", "v0.2.11"),
                 ("0.2.11", "0.2.9")]:
        print(f"  远端 {a:<8} 本地 {b:<8} -> {'有更新' if is_newer(a, b) else '无更新'}")
    print()
    print("联网检查（仓库可能还没发布 Release）：")
    r = check("cingzz/ValTrans", "0.2.11")
    for k in ("ok", "has_update", "local", "remote", "msg"):
        print(f"  {k:<12} {r[k]}")
    if r["assets"]:
        print("  附件:")
        for a in r["assets"]:
            print(f"    {a['name']}  {a['size_mb']}MB  下载{a['downloads']}次")
