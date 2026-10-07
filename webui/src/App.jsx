import React, { useEffect, useState } from 'react'
import { bus, call } from './api.js'
import { IconHome, IconLive, IconQuota, IconStyle, IconGear, IconHelp, IconInfo } from './icons.jsx'
import Home from './pages/Home.jsx'
import Live from './pages/Live.jsx'
import Quota from './pages/Quota.jsx'
import Styles from './pages/Styles.jsx'
import Settings from './pages/Settings.jsx'
import Help from './pages/Help.jsx'
import About from './pages/About.jsx'
import Wizard from './pages/Wizard.jsx'
import LearnDialog from './LearnDialog.jsx'
import TitleBar from './TitleBar.jsx'

const NAV = [
  ['home', '翻译', IconHome],
  ['live', '实时翻译', IconLive],
  ['quota', '我的额度', IconQuota],
  ['styles', '字幕样式', IconStyle],
  ['settings', '设置', IconGear],
  ['help', '帮助', IconHelp],
  ['about', '关于', IconInfo],
]

export default function App() {
  const [page, setPage] = useState('home')
  const [cfg, setCfg] = useState(null)
  const [version, setVersion] = useState('')
  const [running, setRunning] = useState(false)
  const [status, setStatus] = useState({ text: '未启动', kind: 'idle' })
  const [notice, setNotice] = useState(null)
  const [showWizard, setShowWizard] = useState(false)
  const [showOriginal, setShowOriginal] = useState(true)
  const [ttsEnabled, setTtsEnabled] = useState(true)
  const [streamer, setStreamer] = useState(false)
  const [learnPrompt, setLearnPrompt] = useState(null)

  useEffect(() => {
    let alive = true
    let tries = 0
    const load = async () => {
      while (alive && tries < 200) {
        try {
          const st = await call('get_state')
          if (!alive) return
          setCfg(st.cfg)
          setVersion(st.version)
          setShowWizard(!st.cfg.first_run_done || !st.cfg.disclaimer_accepted)
          setShowOriginal(!!st.cfg.show_original)
          setTtsEnabled(!!st.cfg.tts_enabled)
          setStreamer(!!st.cfg.streamer_mode)
          if (st.notice) {
            setNotice(typeof st.notice === 'string' ? st.notice : (st.notice.text || null))
          }
          return
        } catch (e) {
          tries += 1
          await new Promise(r => setTimeout(r, 50))
        }
      }
      if (alive) setNotice('桥接长时间未就绪，请重启软件；若反复出现请看 %APPDATA%/ValTrans/logs/webui.log')
    }
    load()

    const offReady = () => { tries = 0; load() }
    window.addEventListener('vt-bridge-ready', offReady)

    const offStatus = bus.on('status', s => {
      setStatus(s)
      setRunning(s.kind === 'listening' || s.kind === 'recognizing')
    })
    const offNotice = bus.on('notice', n => {
      const t = n && typeof n === 'object' ? (n.text || '') : (typeof n === 'string' ? n : '')
      setNotice(t || null)
    })

    return () => {
      alive = false
      window.removeEventListener('vt-bridge-ready', offReady)
      offStatus()
      offNotice()
    }
  }, [])

  const patchCfg = async (patch) => {
    try {
      const nc = await call('save_cfg', patch)
      setCfg(nc)
      return nc
    } catch (e) {
      const msg = e && e.message ? e.message : String(e)
      setNotice(`设置未保存：${msg}`)
      bus.emit('notice', { text: `设置未保存：${msg}` })
      throw e
    }
  }

  const [toggling, setToggling] = useState(false)
  const toggleRun = async () => {
    if (toggling) return
    const want = !running
    setToggling(true)
    setRunning(want)
    try {
      if (!want) {
        await call('stop')
      } else {
        const r = await call('start')
        if (!r?.ok) {
          setRunning(false)
          bus.emit('status', {
            kind: 'error',
            text: '启动失败: ' + (r?.error || r?.desc || '未知原因'),
          })
        }
      }
    } catch (e) {
      setRunning(!want)
      bus.emit('status', { kind: 'error', text: '操作失败: ' + (e?.message || e) })
    } finally {
      setToggling(false)
    }
  }

  useEffect(() => {
    let alive = true
    const tick = async () => {
      if (!alive) return
      try {
        const st = await call('get_state')
        if (!alive || !st) return
        const real = st.running === true || st.running === '1'
        setRunning((prev) => (prev === real ? prev : real))
      } catch (_) {}
    }
    const t = setInterval(tick, 3000)
    return () => { alive = false; clearInterval(t) }
  }, [])

  const LEARN_DIALOG_ENABLED = false
  useEffect(() => {
    if (!LEARN_DIALOG_ENABLED) return
    let alive = true
    let lastShown = 0
    const tick = async () => {
      if (!alive) return
      try {
        const r = await call('get_learn_prompt')
        if (!alive) return
        if (r?.show && r.items?.length && Date.now() - lastShown > 90000) {
          lastShown = Date.now()
          setLearnPrompt(r.items)
        }
        if (r?.auto_adopted) window.dispatchEvent(
          new CustomEvent('vt-learn-auto', { detail: r.auto_adopted }))
      } catch (e) {}
    }
    tick()
    const h = setInterval(tick, 30000)
    return () => { alive = false; clearInterval(h) }
  }, [])

  const statusColor = { idle: 'var(--muted)', listening: 'var(--ok)', recognizing: 'var(--warn)', error: 'var(--danger)' }[status.kind] || 'var(--muted)'

  return (
    <div className="app-frame">
      <div className="bg" aria-hidden="true">
        <div className="bg__img" />
        <div className="bg__veil" />
      </div>

      <TitleBar version={version} />

      <nav className="rail" aria-label="主导航">
        {NAV.map(([key, text, Icon]) => (
          <button key={key}
                  className={'rail-item' + (page === key ? ' on' : '')}
                  onClick={() => setPage(key)}
                  aria-current={page === key ? 'page' : undefined}
                  title={text}>
            <Icon size={20} strokeWidth={1.9} />
            <span className="rail-label">{text}</span>
          </button>
        ))}
        <div className="rail-state" title={`● ${status.text}`}>
          <i style={{ background: statusColor }} />
          <span className="rail-state-text">{status.text}</span>
        </div>
      </nav>

      <main className="main"
            onMouseMove={(e) => {
              const r = e.currentTarget.getBoundingClientRect()
              e.currentTarget.style.setProperty('--mx', (e.clientX - r.left) + 'px')
              e.currentTarget.style.setProperty('--my', (e.clientY - r.top) + 'px')
            }}>
        <div className="content">
          {!cfg ? (
            <div className="boot">
              <div className="boot-spin" aria-hidden="true" />
              <div className="boot-text">正在连接翻译服务…</div>
            </div>
          ) : (
            <div className="page">
              {learnPrompt && (
                <LearnDialog items={learnPrompt}
                             onClose={() => setLearnPrompt(null)} />
              )}

              {notice && (
                <div className="notice">
                  <span className="grow">{notice}</span>
                  <button onClick={() => { setNotice(null); call('dismiss_notice') }}>✕</button>
                </div>
              )}

              {page === 'home' && (
                <Home cfg={cfg} patchCfg={patchCfg} running={running} status={status}
                      onToggle={toggleRun} toggling={toggling} showOriginal={showOriginal}
                      setShowOriginal={setShowOriginal} ttsEnabled={ttsEnabled}
                      setTtsEnabled={setTtsEnabled} streamer={streamer}
                      setStreamer={setStreamer} goSettings={() => setPage('settings')} />
              )}
              {page === 'live' && <Live />}
              {page === 'quota' && <Quota />}
              {page === 'styles' && <Styles cfg={cfg} patchCfg={patchCfg} />}
              {page === 'settings' && <Settings cfg={cfg} patchCfg={patchCfg} />}
              {page === 'help' && <Help />}
              {page === 'about' && <About version={version} />}

              {showWizard && (
                <Wizard cfg={cfg} patchCfg={patchCfg}
                        onDone={() => setShowWizard(false)} />
              )}
            </div>
          )}
        </div>
      </main>
    </div>
  )
}