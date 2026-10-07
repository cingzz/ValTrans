import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { resolve } from 'path'

// 单入口：index.html 主控窗。
// overlay.html（游戏内字幕浮窗）已随 2026-10-04 原生浮窗（NativeOverlay）退役：
// 浮窗不再经过 WebView2，改由 WinForms+GDI+ 在主进程内绘制。
export default defineConfig({
  plugins: [react()],
  base: './',
})
