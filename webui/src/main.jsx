import React from 'react'
import { createRoot } from 'react-dom/client'
import App from './App.jsx'
// v0.2.21：CSS 层顺序按「令牌 -> 界面 -> 旧样式兜底」。
//
// 为什么换了顺序
// --------------
// 改之前是 styles.css -> design.css -> design_fix.css，
// 而且 design.css / styles.css **各自定义了一套 token** 且互相冲突
// （天蓝 #45BEE8 vs 暖橘 #E07A4F），实际生效的是后加载的 design.css。
// 后果：改 --primary 没反应、不知道哪套是权威。
//
// 现在：tokens.css 是**唯一**令牌来源（设计报告 §4.1「换主题色只改一行」），
// shell.css 是新版面（报告 §3/§5/§7），
// 剩下三个旧文件只提供**组件细节**，且必须排在 shell.css 之后、
// styles.css 必须在 design.css 之前（见下面 import 处的说明）。
import './tokens.css'      // ① 令牌（只有变量，无选择器，顺序无关）
import './shell.css'       // ② 新壳层：版面 + 材质（五件套）
import './styles.css'      // ③ 旧基础样式 —— 必须**在 design 之前**，
                           //    否则它会覆盖新设计系统（.card 的圆角/投影/内边距）
import './design.css'      // ④ 旧组件细节（卡片/表格/弹窗/输入）= 特异度修正层
import './design_fix.css'  // ⑤ 最后：修正 design.css 的疏漏
// ↑ 顺序被 tests/verify_src.py 第 751 行守着（「design.css 必须在 styles.css 之后」）。
//   v0.2.21 我一度把 styles.css 放到最后，verify_src 直接判红 —— 那是对的：
//   styles.css 的 `.card{border-radius:var(--radius); box-shadow:var(--shadow);
//   padding:20px 22px}` 会把 design.css 的新圆角/投影覆盖掉。
import { waitReady } from './api.js'

// v0.2.10：先渲染，**再**等桥接就绪。
//
// 原来是无条件 waitReady() 之后才 createRoot().render()。
// 有系统标题栏时无所谓（窗口上写着「ValTrans」，用户知道程序起来了），
// 但改成自绘无边框标题栏后，从 create_window 到 React 挂载这段
// 用户看到的是一个**完全空白的方块**，会以为程序坏了/白屏了。
//
// 所以改成：立刻渲染 App（App 内部对 cfg 未就绪有加载态外壳，
// 见 App.jsx 的 app-frame/boot 分支），桥接就绪只是不再阻塞首屏。
const root = createRoot(document.getElementById('root'))
root.render(<App />)

// 桥接就绪后再打一发，App 内部的轮询会立刻停止重试。
// 这里刻意不 reload —— reload 会让用户看到第二次白屏。
waitReady().then(() => {
  window.dispatchEvent(new CustomEvent('vt-bridge-ready'))
})