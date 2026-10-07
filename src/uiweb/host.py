# -*- coding: utf-8 -*-
# 作者: cing  ·  https://github.com/cingzz
# 许可: GPL-3.0 + 商业授权（闭源/商用需向作者申请授权），见 LICENSE 与 LICENSE-COMMERCIAL.md
#
"""Web UI 宿主：pywebview 主控窗 + 原生字幕浮窗 + 托盘。

主窗  = webui/dist/index.html（React，WebView2 —— 复杂交互需要）
浮窗  = NativeOverlay（WinForms 分层窗 + GDI+，主进程内，v0.2.11 起）
        —— 不再产生浮窗的 msedgewebview2.exe 子进程（真机 要求）
"""
from __future__ import annotations

import ctypes
import logging
import os
import sys
import threading
import time
from ctypes import wintypes as wtypes
from pathlib import Path

import webview

from .api import Api, OVERLAY_TITLE, OVERLAY_FIXED_H
from ..core.config import CONFIG_DIR

GWL_EXSTYLE = -20
GWLP_HWNDPARENT = -8          # 设置窗口 owner（父窗口句柄）
WS_EX_LAYERED = 0x80000
WS_EX_TRANSPARENT = 0x20
WS_EX_APPWINDOW = 0x00040000  # ★ 任务栏/Alt+Tab 图标来源，必须移除
WS_EX_TOOLWINDOW = 0x00000080
LWA_ALPHA = 0x02
MAIN_TITLE = "ValTrans"        # 主窗标题，浮窗据此设置 owner
DWMWA_WINDOW_CORNER_PREFERENCE = 33
DWMWCP_ROUND = 2


def _dist_file(name: str) -> str:
    if getattr(sys, "frozen", False):
        p = os.path.join(sys._MEIPASS, "webui_dist", name)
    else:
        p = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__)))), "webui", "dist", name)
    return p


def _url(name: str) -> str:
    # 传本地路径字符串（非 file:// URI），pywebview 才会以内置 HTTP 服务器加载，
    # 否则 ES module 在 file:// 下被 CORS 拦截导致白屏
    return _dist_file(name)


def _set_mouse_passthrough(hwnd: int, passthrough: bool) -> None:
    """给窗口及其**全部后代窗口**设置/清除鼠标穿透。

    ★ 这是「切到可拖动后拖不动」的真正修复（v0.2.3 定位）：

    浮窗是 WebView2（Chromium）宿主，真实接收鼠标的是渲染子窗口
    `Chrome_RenderWidgetHostHWND`。它**自带 exstyle 的 WS_EX_TRANSPARENT 位**，
    与父窗口相互独立——只改父窗口的样式，命中测试仍然会穿透到下层窗口，
    表现就是「解锁了但拖不动」。

    实测子窗口清单（可拖动态，父窗口 TRANSPARENT 已清除时）：
        Chrome_WidgetWin_0            exstyle=0x0
        Chrome_WidgetWin_1            exstyle=0x200000
        Chrome_RenderWidgetHostHWND   exstyle=0x20   ← 带穿透，命中测试落在这里
        Intermediate D3D Window       exstyle=0x280024

    因此必须递归遍历 EnumChildWindows 逐个改样式。
    """
    if not hwnd:
        return
    targets = [hwnd]
    try:
        @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
        def _cb(child, _lparam):
            targets.append(int(child))
            return True
        ctypes.windll.user32.EnumChildWindows(hwnd, _cb, 0)
    except Exception:
        logging.getLogger("valtrans.webui").debug("枚举浮窗子窗口失败", exc_info=True)

    for h in targets:
        try:
            cur = ctypes.windll.user32.GetWindowLongPtrW(h, GWL_EXSTYLE)
            if passthrough:
                cur |= WS_EX_TRANSPARENT
            else:
                cur &= ~WS_EX_TRANSPARENT
            ctypes.windll.user32.SetWindowLongPtrW(h, GWL_EXSTYLE, cur)
        except Exception:
            logging.getLogger("valtrans.webui").debug("设置子窗口样式失败 hwnd=%s", h, exc_info=True)

def _apply_main_round(hwnd: int) -> None:
    """主窗圆角（frameless 之后系统圆角会失效，得自己补）。

    复用浮窗那套 DWM 常量（DWMWCP_ROUND / DWMWA_WINDOW_CORNER_PREFERENCE）。
    """
    try:
        DWMWA_WINDOW_CORNER_PREFERENCE = 33
        DWMWCP_ROUND = 2
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            wtypes.HWND(hwnd),
            ctypes.c_int(DWMWA_WINDOW_CORNER_PREFERENCE),
            ctypes.byref(ctypes.c_int(DWMWCP_ROUND)),
            ctypes.sizeof(ctypes.c_int))
    # DWM 圆角纯属装饰，调用失败不影响主窗可用：Win7 / 精简版系统上
    # DwmSetWindowAttribute 直接不存在，frameless 顶栏照样能开。
    except Exception:
        pass


def find_main_hwnd() -> int:
    """按主窗标题找 HWND（给 api.win_set_top 改 WS_EX_TOPMOST 用）。

    刻意与浮窗分开：浮窗标题是 OVERLAY_TITLE，主窗是 MAIN_TITLE，
    两者不会撞（OVERLAY_TITLE 特意带了 'vt-overlay-window-v02'
    这种不会与真实标题重复的串）。
    """
    try:
        h = ctypes.windll.user32.FindWindowW(None, MAIN_TITLE)
        return int(h) if h else 0
    except Exception:
        return 0


def _apply_overlay_style(api: Api) -> None:
    """浮窗窗口样式：整窗分层半透明（跟随透明度滑杆）+ DWM 圆角 + 锁定穿透 +
    WS_EX_TOOLWINDOW（不占任务栏/Alt+Tab，任务栏只有 ValTrans 一个入口）。

    必须在浮窗 show() 之后调用：WinForms 的 Show() 可能重建 HWND，
    施加在旧句柄上的样式会随之丢失。
    """
    hwnd = ctypes.windll.user32.FindWindowW(None, OVERLAY_TITLE)
    if not hwnd:
        return
    # 半透明 + 不占任务栏
    cur = ctypes.windll.user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
    cur |= WS_EX_LAYERED | 0x00000080   # WS_EX_LAYERED + WS_EX_TOOLWINDOW
    ctypes.windll.user32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, cur)
    # 鼠标穿透：判据是「固定(pinned)」而非旧的「锁定(locked)」，
    # 且必须递归到 WebView2 子窗口（见 _set_mouse_passthrough 的说明）。
    pinned = getattr(api._cfg, "overlay_pinned", False)
    locked = getattr(api._cfg, "overlay_locked", False)
    # ★ v0.2.22：判据由 `pinned and locked` 改为 `pinned or locked`。
    #
    #   这是「按了立即固定，过一会又能拖动」的真凶（真机 实测）。
    #   两个开关**语义完全不同**，却是用「与」串起来的：
    #     · pinned ← toggle_pin  「立即固定」按钮 + 老板键 hotkey_move
    #                config.py 明文：True = 固定在当前位置（鼠标穿透，不可拖动）
    #     · locked ← toggle_lock 「锁定穿透」热键 hotkey_lock
    #   两者默认值都是 False（config.py:275/280）。于是用户点「立即固定」
    #   只让 pinned 变 True，locked 仍是 False，`True and False` = False
    #   → **穿透从未生效**，面板照样能被抓住拖 —— 表现为「固定不住」。
    #
    #   为什么该是「或」：pinned 自身就已经完整表达了「固定 = 穿透」这个
    #   语义（见 config.py 注释），不该再被另一个独立开关否决；
    #   locked 是历史上的第二个入口，保留它是为了不破坏 Ctrl+Alt+Q 的行为。
    _set_mouse_passthrough(hwnd, passthrough=bool(pinned or locked))
    alpha = max(102, int(255 * float(getattr(api._cfg, "overlay_opacity", 0.86))))  # 下限 40%
    ctypes.windll.user32.SetLayeredWindowAttributes(hwnd, 0, alpha, LWA_ALPHA)
    pref = ctypes.c_int(DWMWCP_ROUND)
    ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, DWMWA_WINDOW_CORNER_PREFERENCE,
                                               ctypes.byref(pref), 4)


def _make_tray_icon(api: Api):
    try:
        import pystray

        def _icon_img():
            # v0.2.21：托盘图标不再**手绘**。
            # 原来这里自己画了个天蓝方块 + "V"，和 assets/icon.ico
            # （绿方块 + 黑 V）长得完全不一样 —— 两份实现必然漂移，
            # 用户看到的托盘图标和安装包图标对不上。
            # 现在统一走 src/uiweb/app_icon.py 这一份绘制实现。
            from .app_icon import render
            return render(64)

        def show(icon=None, item=None):
            api._win.show()

        def toggle(icon=None, item=None):
            if getattr(api._pipeline, "_running", None) and api._pipeline._running.is_set():
                api.stop()
            else:
                api.start()

        def quit_app(icon=None, item=None):
            icon.stop()
            api.quit()

        menu = pystray.Menu(
            pystray.MenuItem("显示主窗口", show, default=True),
            pystray.MenuItem("开始/停止翻译", toggle),
            pystray.MenuItem("退出", quit_app),
        )
        return pystray.Icon("ValTrans", _icon_img(), "ValTrans · 瓦罗兰特实时语音翻译", menu)
    except Exception:
        return None


def _bind_win_events(api: Api, window) -> None:
    """订阅窗口事件，把状态变化推给前端标题栏。

    v0.2.10 新增。原来 pywebview 的 window.events 一个都没订阅，
    于是「用户自己拖到屏幕边缘自动最大化」「双击标题栏变大」
    这两种情况前端完全不知道，标题栏图标会和实际状态不符。

    注意 minimized/closing 是**在 GUI 线程外**派发的回调，
    这里只做 _emit（evaluate_js），pywebview 内部会排队，
    但仍要包 try —— 窗口正在销毁时 evaluate_js 会抛。
    """
    try:
        def _safe(name):
            def _fn(*_a, **_kw):
                try:
                    # 最大化/还原会重建 HWND 并重置 style，
                    # 所以每次都要把缩放边框补回去，
                    # 否则「最大化 -> 还原」之后窗口就再也拖不动大小了。
                    if name in ("maximized", "restored", "shown"):
                        _keep_resizable(None)
                    api._push_winstate()
                # 可以静默：这是 pywebview 的**窗口状态事件回调**，跑在
                #   WebView2 的事件线程上。这里抛异常既没人接也传不出去，
                #   只会变成事件线程里的未捕获异常（连带影响后续事件）。
                #   而做的两件事都是锦上添花：回补缩放边框 + 推送窗口状态。
                except Exception:
                    pass
            return _fn

        for ev in ("maximized", "restored", "resized", "shown"):
            try:
                window.events[ev] += _safe(ev)
            # 可以静默：某个事件订阅不上（比如该版本 window.events 是普通
            #   dict 不支持 +=）不该拖垮其余事件 —— 每个事件独立订阅，
            #   一个失败其余照常。
            except Exception:
                pass
    except Exception as e:
        logging.getLogger("valtrans.webui").debug(
            "窗口事件订阅失败（不影响主功能）: %r", e)


def _keep_resizable(window) -> None:
    """frameless 之后把缩放边框加回来。

    为什么必须补
    ------------
    实测：frameless=True 时 WS_THICKFRAME 也会被 WinForms 一起去掉
    （FormBorderStyle=None 同时清掉 WS_CAPTION | WS_THICKFRAME），
    于是窗口**拖不动大小**，min_size 也就形同虚设。

    做法：只加 WS_THICKFRAME，不加 WS_CAPTION ——
    有缩放边框、没有系统标题栏，正是自绘标题栏想要的结果。

    必须在窗口**真正建好之后**调用
    ----------------------------
    pywebview 的 start() 先启 func 线程、再建窗（__init__.py:294-303），
    所以 _bootstrap 一进来时 handle 还不存在。
    这里做短轮询兜底，别指望传进来的 window 对象。

    WinForms 的 maximize/restore 会重建 HWND 并重置 style，
    所以每次最大化/还原后还要再补一次（见 _bind_win_events）。
    """
    GWL_STYLE = -16
    WS_THICKFRAME = 0x00040000
    WS_CAPTION = 0x00C00000
    WS_SYSMENU = 0x00080000
    WS_MINIMIZEBOX = 0x00020000
    WS_MAXIMIZEBOX = 0x00010000

    hwnd = 0
    for _ in range(30):                    # 最多等 3 秒
        if window is not None:
            try:
                hwnd = int(window.native.Handle)
            except Exception:
                hwnd = 0
        if not hwnd:
            hwnd = find_main_hwnd()
        if hwnd:
            break
        time.sleep(0.1)
    if not hwnd:
        # 早于建窗时调用是正常的（pywebview 先启 func 线程再建窗），
        # 那次不报警，等 _bootstrap 里 sleep 之后再调一次就行。
        logging.getLogger("valtrans.webui").debug(
            "keep_resizable: 主窗尚未创建，跳过（由 _bootstrap 重试）")
        return
    try:
        style = ctypes.windll.user32.GetWindowLongW(wtypes.HWND(hwnd),
                                                     GWL_STYLE)
        style &= ~WS_CAPTION               # 保持无标题栏
        style |= (WS_THICKFRAME | WS_SYSMENU |
                  WS_MINIMIZEBOX | WS_MAXIMIZEBOX)
        ctypes.windll.user32.SetWindowLongW(wtypes.HWND(hwnd),
                                             GWL_STYLE, style)
        ctypes.windll.user32.SetWindowPos(
            wtypes.HWND(hwnd), 0, 0, 0, 0, 0,
            0x0001 | 0x0002 | 0x0040)      # NOSIZE|NOMOVE|NOACTIVATE
        after = ctypes.windll.user32.GetWindowLongW(wtypes.HWND(hwnd),
                                                     GWL_STYLE)
        logging.getLogger("valtrans.webui").info(
            "keep_resizable hwnd=%s 0x%08X -> 0x%08X",
            hwnd, style, after)
    except Exception as e:
        logging.getLogger("valtrans.webui").warning(
            "keep_resizable 失败: %r", e)


def _bootstrap(api: Api, window) -> None:
    api._win = window
    log = logging.getLogger("valtrans.webui")
    icon = _make_tray_icon(api)
    if icon is not None:
        threading.Thread(target=icon.run_detached, daemon=True).start()
        api._tray_icon = icon

    # v0.2.10 自绘标题栏：订阅窗口事件（原来一个都没订阅）。
    # 前端不知道用户把窗口拖到屏幕边缘自动最大化了，
    # 标题栏的 maximize/restore 图标会和实际状态不符。
    #
    # ⚠ 这里**不能**碰窗口样式
    # ------------------------
    # pywebview 的 start() 是这样启动的（webview/__init__.py:294-303）：
    #     thread = threading.Thread(target=func, args=args); thread.start()
    #     ...
    #     guilib.create_window(windows[0])     <- 真正的 WinForms 窗体在这时才建
    # 也就是说 **_bootstrap 跑在独立线程上、且早于建窗**，
    # 此时 window.native.Handle 还不存在、FindWindowW 也找不到窗口。
    # 实测就是因此 _keep_resizable 静默失败（style 仍是 0x16010000，
    # 只有 MAXIMIZEBOX，窗口拖不动大小）。
    # 所以样式/圆角必须在下面的 sleep 之后、窗口真正建好时再设。
    _bind_win_events(api, window)

    # 诊断：页面加载状态 + 实际 URL（排查白屏用）
    time.sleep(1.5)

    # v0.2.10：窗口已建，补 frameless 带来的两处副作用
    #  1) WS_THICKFRAME 被一起去掉 -> 窗口不能缩放
    #  2) 系统圆角失效 -> 自己用 DWM 补
    _keep_resizable(window)
    try:
        _apply_main_round(find_main_hwnd())
    # 可以静默：主窗圆角同上，纯装饰，失败不影响 frameless 顶栏可用。
    except Exception:
        pass

    try:
        diag = window.evaluate_js(
            "document.readyState + '||' + document.body.innerHTML.length + '||' +"
            " (window.__vt?1:0) + '||' + (window.pywebview?1:0) + '||' + location.href")
        log.info("DIAG " + str(diag))
    except Exception as e:
        log.exception("DIAG 失败: %s", e)
    # JS 通知桥接就绪
    window.evaluate_js("window.__vt && window.__vt.emit('boot', true)")

    # 演示钩子（VALTRANS_DEMO=1）：注入假字幕与状态，供截图验收 / 新用户体验
    if os.environ.get("VALTRANS_DEMO"):
        threading.Thread(target=_demo_feed, args=(api,), daemon=True).start()


def _demo_feed(api: Api) -> None:
    log = logging.getLogger("valtrans.webui")
    time.sleep(3.5)
    # ★ v0.2.16：真实链路在跑就不注入假数据（此前无互斥，假字幕会
    #   糊进真实字幕流，last_rms 还被钉死在 0.42）
    if api._pipeline._running.is_set():
        log.info("demo: pipeline running, skip demo feed")
        return
    log.info("demo: start feeding")
    api._emit("status", {"kind": "listening", "text": "监听中", "desc": "演示数据 · 扬声器 [Loopback]"})
    demo = [
        ("こんにちは、Bサイトにラッシュしよう。", "你好！让我们赶紧冲 B 点吧！", 1198),
        ("Enemy is rotating to B site. I will flash for you.", "敌人正在转点 B，我来给你闪光。", 1312),
        ("바론 곧 리스폰이니까 모여줘.", "大龙马上就要刷新了，都集合过来。", 1450),
    ]
    api._pipeline.last_rms = 0.42
    for orig, trans, ms in demo:
        api._emit("subtitle", {"original": orig, "translated": trans, "latency_ms": ms,
                               "fallback": False, "error": "", "mine": False,
                               "time": time.strftime("%H:%M:%S")})
        api._overlay_show(orig, trans, "队友")
        time.sleep(1.2)
    api._overlay_show("集合打大龙，别分散。", "Group up for the Baron, don't split.", "我", True)


def make_native_overlay(api: Api):
    """浮窗懒创建工厂（v0.2.11 原生渲染）。

    放在模块级而不是 run() 内：startup_overlay_test 等测试与本函数
    必须是**同一份实现** —— 测试工厂自己另写一份，测的就不是用户跑的
    路径了（本轮实测教训：测试还在用旧 webview 工厂，原生浮窗从未被测过）。
    """
    from .native_overlay import NativeOverlay
    ov = NativeOverlay(api)
    _apply_overlay_style(api)
    return ov


def run() -> int:
    # ★ v0.2.18 防护：pywebview 本地桥（http://127.0.0.1:<随机端口>）的
    #   uid 用 uuid1 生成——含 MAC+时间戳、可预测性弱，远程网页扫到端口后
    #   有机会命中桥地址。进程内把 uuid1 换成 uuid4（只影响本进程），
    #   本地桥地址变成不可猜的随机端点。本地同权限恶意软件不受此影响
    #   （那是杀软的战场，见 AGENTS 防护清单）。
    import uuid as _uuid_mod
    _uuid_mod.uuid1 = _uuid_mod.uuid4

    # ★ v0.2.16：先建 logs 目录再建 FileHandler——此前 Api.__init__ 里的
    #   mkdir 晚于 basicConfig，全新机器首次启动 FileNotFoundError 直接闪退
    #   （老用户因目录已存在而掩盖）。
    (CONFIG_DIR / "logs").mkdir(parents=True, exist_ok=True)
    log_file = str(CONFIG_DIR / "logs" / "webui.log")
    from logging.handlers import RotatingFileHandler
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[RotatingFileHandler(log_file, maxBytes=2 * 1024 * 1024,
                                      backupCount=1, encoding="utf-8"),
                  logging.StreamHandler(sys.stderr)])

    # ★ v0.2.21 单实例守卫（用户实测「后台退了但弹窗还在桌面上，我根本退不了」）
    #
    #   日志证明那次跑着**两个实例**（全局热键打印两次、DIAG 两个端口、
    #   overlay created 两次 = 两个浮窗）。用户从托盘退掉的是其中一个，
    #   另一个的浮窗就留在桌上了 —— 而窗口能留着说明**那个进程还活着**。
    #   所以这不是 close() 写错了，是「有两个进程」，修 close() 修不到点上。
    #
    #   行为：第二次启动**不新建浮窗**，而是把已有实例叫到前台然后自己退出。
    #   wait_ms 给「刚退出就重开」留 3 秒宽限（上一个进程被 kill 后
    #   内核释放互斥有极短延迟）。
    #
    #   互斥量是内核对象：进程一死（哪怕 taskkill /F）内核自动释放，
    #   不会像锁文件那样留下死锁导致下次永远起不来。
    if os.environ.get("VALTRANS_TEST") != "1":
        from ..core.single_instance import acquire, activate_existing
        got, why = acquire(wait_ms=3000)
        if not got:
            logging.getLogger("valtrans.webui").warning(
                "检测到已有实例在运行（%s）：本次启动改为唤醒它", why)
            activate_existing(MAIN_TITLE)
            return 0

    api = Api()

    # 浮窗懒创建工厂：点「开始翻译」后面板才出现（空闲时不存在任何浮窗窗口）。
    # api._ensure_overlay 调 factory() **不传参**，这里闭包绑住 api。
    api._overlay_factory = lambda: make_native_overlay(api)

    # v0.2.11：VALTRANS_TEST=1 时不抢前台。
    #
    # 背景：自动化测试每次都要拉起一个真实应用实例（一次全量验收 9 次，
    # 追flake 连跑三轮就是 27 次），每次都会：
    #     · 弹窗抢前台，打断用户手上的事（实测用户开着 VALORANT）
    #     · 注册全局热键 Ctrl+Alt+Q / Ctrl+Alt+H / Ctrl+Shift+D
    # 用户反馈「刚刚一直在反复地重启那个软件」——
    # 那是测试在拉起它（应用自身没有任何自动重启机制，已确认）。
    #
    # 所以给测试留一个静默开关：窗口正常创建（测试要量尺寸/截图），
    # 但**不激活、不抢焦点**，并跳过全局热键注册
    # （热键注册会真的占用系统按键，测试期间用户按这些键会被吃掉）。
    _is_test = os.environ.get("VALTRANS_TEST") == "1"

    window = webview.create_window(
        "ValTrans", url=_url("index.html"),
        width=1240, height=800, min_size=(980, 660), js_api=api,
        # ★ v0.2.16：测试模式不抢前台——此前 _is_test 是个**死变量**，
        #   注释承诺了「不激活、不抢焦点」却从没传 focus=False
        focus=not _is_test,
        # v0.2.10 自绘标题栏：去掉 Windows 原生标题栏。
        # 原生那条是系统深色/蓝绿色的，跟整套暖橘护眼设计打架，
        # 截图里一眼就能看出不是同一个软件。
        frameless=True,
        # ⚠ easy_drag=False 是**必须项**，不是优化项。
        #   pywebview 只在「edgechromium 且 easy_drag 且 frameless」
        #   时才注入 'True'（webview/util.py:379-381）；注入后
        #   customize.js:92 会给 window 加全局 mousedown 拖动监听，
        #   而 customize.js:55-61 的 DRAG_REGION_DIRECT_TARGET_ONLY
        #   默认 False —— **不做任何区域判断**。
        #   结果：全窗口任意位置按下鼠标都变成拖窗，
        #   按钮点不动、滑杆拖不动、输入框选不了字，全站交互报废。
        #   正确做法：关掉 easy_drag，只在标题栏元素上加
        #   .pywebview-drag-region（customize.js:89 的 onBodyMouseDown
        #   是无条件注册的，走 DOM 向上找这个类，不需要 easy_drag）。
        easy_drag=False)

    # 锁定切换回调（api.toggle_lock 内部会调用）
    api._apply_overlay_style = lambda: _apply_overlay_style(api)

    # ★ v0.2.16：删掉 webview.start 之前的这次 _keep_resizable——
    #   那时窗口必然还不存在，函数只会空轮询 3 秒拖慢启动；
    #   真正生效的调用在 _bootstrap 的 sleep(1.5) 之后。

    # http_server=True：经内置 localhost 服务器加载（file:// 下 ES module 会被 CORS 拦截）
    webview.start(_bootstrap, args=(api, window), debug=False, http_server=True)

    try:
        if getattr(api, "_tray_icon", None) is not None:
            api._tray_icon.stop()
    # 可以静默：这是 webview.start() 返回后的收尾。托盘图标停不掉时
    #   现象是「关掉主窗后任务栏还留个图标」，而进程此刻本来就要退出，
    #   残留的托盘句柄会随进程一起释放。绝不该为它抛异常、让正常退出
    #   变成非零返回码。
    except Exception:
        pass
    return 0
