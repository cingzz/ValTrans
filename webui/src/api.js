// 桥接层：事件总线 + pywebview api 访问
const listeners = {}

export const bus = {
  on(name, fn) {
    ;(listeners[name] = listeners[name] || []).push(fn)
    return () => { listeners[name] = listeners[name].filter(f => f !== fn) }
  },
  emit(name, data) {
    ;(listeners[name] || []).forEach(f => { try { f(data) } catch (e) { console.error(e) } })
  },
}

window.__vt = bus   // Python 端 evaluate_js 调 window.__vt.emit(...)

// JS 错误回传 Python 日志（file:// / 生产环境排障）
window.addEventListener('error', e => {
  try { window.pywebview?.api?.js_error(`JS错误: ${e.message} @ ${e.filename}:${e.lineno}`) } catch (_) {}
})
window.addEventListener('unhandledrejection', e => {
  try { window.pywebview?.api?.js_error(`Promise拒绝: ${e.reason && (e.reason.stack || e.reason.message) || e.reason}`) } catch (_) {}
})

export function api() {
  return window.pywebview?.api
}

export async function call(name, ...args) {
  const a = api()
  if (!a) throw new Error('桥接未就绪')
  return await a[name](...args)
}

// 桥接调用失败不再静默：统一冒泡到 notice 横幅（避免"点了没反应"无从排查）
export async function callOr(name, ...args) {
  try {
    return await call(name, ...args)
  } catch (e) {
    bus.emit('notice', { text: `调用 ${name} 失败：${e && e.message ? e.message : e}` })
    throw e
  }
}

export function waitReady() {
  // pywebviewready 事件可能在模块执行前就已派发：轮询 + 事件双保险
  return new Promise(resolve => {
    if (window.pywebview?.api) return resolve()
    const t = setInterval(() => {
      if (window.pywebview?.api) { clearInterval(t); resolve() }
    }, 50)
    window.addEventListener('pywebviewready', () => { clearInterval(t); resolve() }, { once: true })
  })
}
