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
import MeetingWizard from './pages/MeetingWizard.jsx'
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
  const [page, setPage] = useState(() => {
    // ★ 仅测试模式：允许用 VALTRANS_TEST_PAGE 直接落在某个页面上。
    //   为什么要它：验「新增的设置页渲染对不对」时，靠坐标点击去切页签
    //   极不可靠（布局一动坐标就失效，而失效的表现是「截到了首页」
    //   却报成通过）。VALTRANS_TEST 已有的先例是 VALTRANS_TEST=1
    //   跳过热键注册，这里同源。
    if (window.__VT_TEST_PAGE__) return window.__VT_TEST_PAGE__
    return 'home'
  })
  const [cfg, setCfg] = useState(null)
  const [version, setVersion] = useState('')
  const [running, setRunning] = useState(false)
  const [status, setStatus] = useState({ text: '未启动', kind: 'idle' })
  const [notice, setNotice] = useState(null)
  const [showWizard, setShowWizard] = useState(false)
  const [showMeeting, setShowMeeting] = useState(
    () => !!window.__VT_TEST_OPEN_MEETING__)
  const [selectResult, setSelectResult] = useState(null)
  const [showOriginal, setShowOriginal] = useState(true)
  const [ttsEnabled, setTtsEnabled] = useState(true)
  const [streamer, setStreamer] = useState(false)
  const [learnPrompt, setLearnPrompt] = useState(null)

  useEffect(() => {
    if (!window.__VT_TEST_SCROLL__) return
    // 仅测试模式：滚到指定位置。设置页的 TTS 下拉 / 划词热键在首屏之下。
    //
    // 判据选「**形状对**」而不是「猜一个名字」：我第一版写的是
    // querySelector('main')，但真正能滚的是 .content（shell.css:236
    // overflow-y:auto）。页面本身没滚动条，所以 document.scrollingElement
    // 也滚不动 —— 结果三张图一模一样，而我差点当成「页面没问题」。
    // 教训和 AGENTS.md 那条一致：判据要能区分「没滚」和「没有内容」。
    // 依赖里必须带 cfg：挂载那一刻 cfg 还是 null，设置页内容还没渲染，
    // 滚动容器根本不存在 —— 只依赖 [page] 的话这个 effect 只会在
    // 空壳上跑一次，然后静默无效。（第二轮又踩了一次，截图差异 0.43%
    // 才暴露出来。）
    const el = [...document.querySelectorAll('.content, .main, main, .scroll')]
      .find(e => e.scrollHeight > e.clientHeight + 20)
    if (el) el.scrollTop = window.__VT_TEST_SCROLL__
    else console.warn('[vt-test] 找不到可滚动容器，__vt_scroll 未生效')
  }, [page, cfg])

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
    // ★ v0.3.0：划词翻译的结果。译文已经进了剪贴板，但那只是
    //   「拿去粘贴」—— 用户按完热键通常想先**看一眼**对不对。
    //   不监听的话后端 emit 出去就没人收，属于「发到空处」。
    //   8 秒后自动消失：这个窗口不是常驻面板，
    //   留着不走会挡住用户正在做的事。
    const offSelect = bus.on('select_result', r => {
      if (!r) return
      setSelectResult(r)
    })

    return () => {
      alive = false
      window.removeEventListener('vt-bridge-ready', offReady)
      offStatus()
      offNotice()
      offSelect()
    }
  }, [])

  useEffect(() => {
    if (!selectResult) return
    const t = setTimeout(() => setSelectResult(null), 8000)
    return () => clearTimeout(t)
  }, [selectResult])

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
                      setStreamer={setStreamer} goSettings={() => setPage('settings')}
                      openMeeting={() => setShowMeeting(true)} />
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
              {showMeeting && (
                <MeetingWizard cfg={cfg} patchCfg={patchCfg} running={running}
                               onStart={toggleRun}
                               onClose={() => setShowMeeting(false)} />
              )}

              {selectResult && (
                <div className="notice" style={{
                  position: 'fixed', right: 20, bottom: 20, zIndex: 60,
                  maxWidth: 420, boxShadow: '0 8px 28px rgba(0,0,0,.28)',
                  display: 'block', lineHeight: 1.7,
                }}>
                  <div className="muted" style={{
                    fontSize: 12, marginBottom: 4,
                    overflow: 'hidden', textOverflow: 'ellipsis',
                    whiteSpace: 'nowrap', maxWidth: 380,
                  }}>{selectResult.original}</div>
                  <div style={{ fontWeight: 600 }}>{selectResult.translated}</div>
                  <button onClick={() => setSelectResult(null)}
                          style={{ position: 'absolute', right: 6, top: 4 }}>
                    ✕
                  </button>
                </div>
              )}
            </div>
          )}
        </div>
      </main>
    </div>
  )
}