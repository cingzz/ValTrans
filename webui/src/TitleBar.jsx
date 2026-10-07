// 自绘标题栏（v0.2.10 建立，v0.2.21 按 NexBox 设计报告重做）
//
// 为什么不用系统标题栏
// --------------------
// 原生标题栏是 Windows 深色/蓝色的一条，跟整套设计打架，
// 截图里一眼就能看出不是同一个软件。
//
// ⚠ easy_drag 必须在 Python 侧显式关掉
// ------------------------------------
// host.py 的 create_window 传了 easy_drag=False。
// pywebview 只有在「edgechromium 且 easy_drag 且 frameless」时才注入
// 'True'；一旦注入，它会给 window 加全局 mousedown 拖动监听，
// 而且 DRAG_REGION_DIRECT_TARGET_ONLY 默认 False —— 不做区域判断，
// 结果是全窗口任意位置按下鼠标都变成拖窗，按钮/滑杆/输入框全废。
//
// 所以这里的做法是：靠 .pywebview-drag-region 类标记可拖区域。
// customize.js 的 onBodyMouseDown 是**无条件注册**的，
// 它从 mousedown 的 target 向上冒泡找这个类 —— 不需要 easy_drag。
//
// ★ v0.2.21 两处改动
// ----------------
// ① 顶栏按报告 §3.3 做成**连续玻璃带**。报告的理由值得记：
//    `z-index` 只保证「画在上面」，**透明的东西画在上面什么都挡不住**。
//    搜索框自身有玻璃，但左右那条横带是空的 —— 一旦没有底色，
//    主内容滚动时会原样从顶栏穿过去，观感非常廉价。
//    报告给的量值：亮色 .96（.66 可读、.92 暗色仍有影，.96 才到肉眼不可见）。
//
// ② 最大化/还原图标改用 morphicons 的变形引擎，且**由 maximized 驱动**。
//    原写法是 `const MaxIcon = maximized ? IconRestore : IconMax` ——
//    换组件等于**卸载重建**，变形动画根本不会触发（那只是两张图瞬切）。
//    引擎的价值正在于「同一个组件里 from 图变到 to 图」。
import { useEffect, useState, useCallback } from 'react'
import { call, callOr, bus } from './api.js'
import { IconMin, IconMaxRestore, IconClose, IconPin, IconPinOff } from './icons.jsx'

export default function TitleBar({ version }) {
  const [maximized, setMaximized] = useState(false)
  const [onTop, setOnTop] = useState(false)

  // 首屏读一次真实状态，避免图标一开始画错
  useEffect(() => {
    call('win_state')
      .then(s => { if (s) { setMaximized(!!s.maximized); setOnTop(!!s.always_on_top) } })
      .catch(() => {})
  }, [])

  // Python 侧窗口事件（最大化/还原/拖到边缘自动最大化）推过来的状态
  useEffect(() => {
    const off = bus.on('winstate', s => {
      if (!s) return
      setMaximized(!!s.maximized)
      setOnTop(!!s.always_on_top)
    })
    return off
  }, [])

  const onMin = useCallback(() => { callOr('win_min').catch(() => {}) }, [])
  const onClose = useCallback(() => { callOr('win_close').catch(() => {}) }, [])
  const onToggleMax = useCallback(
    () => { callOr('win_toggle_max').then(() => {
      // 以 Python 回读为准，避免图标与实际状态不同步
      call('win_state').then(s => s && setMaximized(!!s.maximized)).catch(() => {})
    }).catch(() => {}) },
    [])
  const onToggleTop = useCallback(
    () => { callOr('win_set_top', !onTop).then(s => s && setOnTop(!!s.always_on_top)).catch(() => {}) },
    [onTop])

  // 双击标题栏空白处 = 最大化/还原
  const onDoubleClick = useCallback((e) => {
    // 点在按钮上就别触发双击
    if (e.target.closest('.titlebar .win-btns button')) return
    onToggleMax()
  }, [onToggleMax])

  return (
    <div className="titlebar" onDoubleClick={onDoubleClick}>
      {/* 可拖区域：只有标记了 .pywebview-drag-region 的块能被拖动窗口 */}
      <div className="tb-left pywebview-drag-region">
        <span className="logo" aria-hidden="true">V</span>
        <span className="name pywebview-drag-region">ValTrans</span>
        {version ? <span className="ver pywebview-drag-region">v{version}</span> : null}
        <span className="tb-sub pywebview-drag-region">瓦罗兰特实时语音翻译</span>
      </div>

      <div className="win-btns">
        <button
          className={onTop ? 'on' : ''}
          onClick={onToggleTop}
          title={onTop ? '取消置顶' : '窗口置顶'}
          aria-label={onTop ? '取消置顶' : '窗口置顶'}
          aria-pressed={onTop}
        >
          {onTop ? <IconPinOff size={15} /> : <IconPin size={15} />}
        </button>
        <button onClick={onMin} title="最小化" aria-label="最小化">
          <IconMin size={15} />
        </button>
        {/* ★ 变形由 maximized 驱动，同一个组件内部 from→to */}
        <button
          onClick={onToggleMax}
          title={maximized ? '还原' : '最大化'}
          aria-label={maximized ? '还原' : '最大化'}
        >
          <IconMaxRestore maximized={maximized} size={15} />
        </button>
        <button className="close" onClick={onClose}
                title="关闭（隐藏到托盘）" aria-label="关闭">
          <IconClose size={15} />
        </button>
      </div>
    </div>
  )
}