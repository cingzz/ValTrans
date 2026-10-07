/* ============================================================================
   图标 —— morphicons + lucide-react（v0.2.21 替换原先 12 个手写 SVG）

   ★★ 这里踩了**两次**包选型的坑，都记下来（两次都是白屏，而且
      `npm run build` 照样通过、零警告 —— **构建通过 ≠ 渲染正确**）

   坑 1：只装 `lucide`（vanilla 数据包）当组件用
   ------------------------------------------------
   它的导出是 **IconNode 数据**（`[["rect",{...}]]`），不是 React 组件。
   于是 `<IconHome />` 把一个对象当组件渲染：
       Uncaught Error: Minified React error #130  ... args[]=object
   → 修法：页面里直接渲染的那些，从 `lucide-react` 取**组件**。

   坑 2：把 `lucide-react` 的组件喂给 MorphIcon（本次白屏的真凶）
   ------------------------------------------------
   morphicons 的 `icon` 入参类型（node_modules/morphicons/dist/types-*.d.ts）：
       type IconNode  = ReadonlyArray<readonly [string, IconNodeAttrs]>
       type IconInput = IconNode | string      // 或者是裸的 d 字符串
   我第一版写的是 `<MorphIcon icon={maximized ? Copy : Square} />`，
   而 `Copy`/`Square` 是 **lucide-react 的组件**，不是 IconNode，于是引擎里：
       iconToCubics(input) -> input 不是数组 -> TypeError: input is not iterable
   整页崩（React 渲染期抛错会把整棵树拆掉，`#root` 直接被清空）。

   定位这一条的关键不是读代码，是**让引擎自己说话**：探针把
   `console.error` 挂在 `<head>` 里（排在 module 脚本**前面**），
   截图回来直接看到 `iconToCubics -> canonicalID -> MorphIcon` 的完整调用栈。
   注意 React 渲染期错误走 console.error、**不走 window.onerror**，
   所以 host.py 只挂 window.onerror 时日志是干净的（曾据此误判「没报错」）。

   写这行注释前刚验过的三条实测结论（不是推测）：
       · `lucide-react` 的组件对象上**只有** `$$typeof` 和 `render`，
         没有任何 IconNode 数据 -> 拿不到，只能另外引 `lucide`
       · `lucide` 导出的正是引擎要的形态，实测：
             Square -> [["rect",{"width":"18","height":"18","x":"3","y":"3","rx":"2"}]]
             Copy   -> [["rect",{...,"ry":"2"}],
                        ["path",{"d":"M4 16c-1.1 0-2-.9-2-2V4..."}]]
       · 引擎能吃 `rect`（normalize 里有 `rectPath(attrs)`），
         所以「最大化(Square) <-> 还原(Copy)」这对能正常变形

   所以最终搭配是**两个包各司其职**，各引各的：
       `lucide-react` -> 组件（页面里直接渲染）
       `lucide`       -> IconNode 数据（只给 MorphIcon）
   ============================================================================ */
import React from 'react'
import {
  Home, Radio, Gauge, Palette, Settings2, CircleHelp, Info, Mic,
  Minus, X, Search, Keyboard, AlertTriangle, Check, Pin, PinOff,
} from 'lucide-react'
/* 只取变形那一对的数据，别把整个 vanilla 包拉进来 */
import { Square as SquareNode, Copy as CopyNode } from 'lucide'

/* 变形引擎：只给「成对出现」的图标用 */
import { MorphIcon } from 'morphicons/react'

/* ---- 静态图标：lucide-react 的 React 组件（描边风格，与旧手写 SVG 同族）-- */
export const IconHome     = Home
export const IconLive     = Radio
export const IconQuota    = Gauge
export const IconStyle    = Palette
export const IconGear     = Settings2
export const IconHelp     = CircleHelp
export const IconInfo     = Info
export const IconMic      = Mic
export const IconMin      = Minus
export const IconClose    = X
export const IconSearch   = Search
export const IconKeyboard = Keyboard
export const IconWarn     = AlertTriangle
export const IconCheck    = Check
export const IconPin      = Pin
export const IconPinOff   = PinOff

/* ---- 变形图标：窗口「最大化 <-> 还原」 --------------------------------
   ★ 必须由 `maximized` **驱动同一个组件**，不能靠换组件实现 ——
     `const MaxIcon = maximized ? IconRestore : IconMax` 那种写法
     等于卸载旧组件、挂载新组件，变形动画根本不会触发（只是两张图瞬切）。
     morphicons 的全部价值就在「同一组件内 from 图变到 to 图」。

   ★ 这里传的是 `lucide` 的 **IconNode 数据**（见文件头坑 2），
     不是 lucide-react 的组件。                              */
export const IconMaxRestore = ({ maximized = false, size = 14, ...rest }) => (
  <MorphIcon icon={maximized ? CopyNode : SquareNode}
              size={size} strokeWidth={1.9} {...rest} />
)

/* ---- 兼容旧名（外部引用可能还用旧导出）------------------------------ */
export const IconMax = IconMaxRestore
export const IconRestore = IconMaxRestore