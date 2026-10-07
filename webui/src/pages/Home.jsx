import React, { useEffect, useState } from 'react'
import { bus, call } from '../api.js'
import HotkeyInput, { prettyHotkey } from '../HotkeyInput.jsx'

export default function Home({ cfg, patchCfg, running, status, onToggle, toggling,
                               showOriginal, setShowOriginal, ttsEnabled, setTtsEnabled,
                               streamer, setStreamer, goSettings }) {
  const [latency, setLatency] = useState(null)
  const [voice, setVoice] = useState(cfg.tts_voice || '')
  const [voices, setVoices] = useState([])
  const [previewing, setPreviewing] = useState(false)
  const [pttKey, setPttKey] = useState(cfg.hotkey_ptt || '')

  useEffect(() => {
    call('get_voices').then(setVoices).catch(() => {})
    const offSub = bus.on('subtitle', ev => setLatency(ev.latency_ms))
    // 试听结束/被停止后复位按钮，避免永远卡在「试听中…」
    const offPrev = bus.on('test_result', d => { if (d.kind === 'preview') setPreviewing(false) })
    const t = setTimeout(() => setPreviewing(false), 12000)   // 兜底自动复位
    return () => { offSub(); offPrev(); clearTimeout(t) }
  }, [])

  const modeText = cfg.capture_mode === 'cable' ? '虚拟声卡线路' : '整机采集 Loopback'
  const statusBig = running
    ? (status.kind === 'recognizing' ? '识别+翻译中…' : '监听中')
    : (status.kind === 'error' ? status.text : '准备就绪')

  // v0.2.11：轮询浮窗**实际可见性**。
  // 为什么必须轮询而不是只在配置变化时更新：`overlay_enabled` 不变，
  // 但浮窗会因懒创建而出现、因停止翻译而隐藏 —— 配置事件捕捉不到这种
  // 「配置没变但实际状态变了」的情况。
  useEffect(() => {
    if (!cfg.overlay_enabled) return
    let alive = true
    const tick = async () => {
      if (!alive) return
      try {
        const st = await call('get_overlay_state')
        if (alive && typeof st?.overlay_visible === 'boolean'
            && st.overlay_visible !== cfg.overlay_visible) {
          patchCfg({ ...cfg, overlay_visible: st.overlay_visible })
        }
      } catch (_) { /* 未就绪时忽略 */ }
    }
    tick()
    const t = setInterval(tick, 2000)
    return () => { alive = false; clearInterval(t) }
  }, [cfg.overlay_enabled, cfg.overlay_visible])

  return (
    <div>
      <div className="row" style={{ alignItems: 'flex-start', marginBottom: 16 }}>
        <div className="card grow">
          <div className="row" style={{ justifyContent: 'space-between' }}>
            <h2 className="h2">翻译</h2>
            <button className="btn ghost" style={{ padding: '6px 10px' }} onClick={goSettings} title="设置">⚙</button>
          </div>
          <div className="row" style={{ margin: '10px 0 14px', flexWrap: 'wrap' }}>
            <span className="pill">{modeText}</span>
            <span className="pill gray">自动复制译文</span>
            {ttsEnabled && !streamer && <span className="pill gray">播放译文语音</span>}
            {streamer && <span className="pill green">主播模式</span>}
          </div>
          <div style={{ fontSize: 30, fontWeight: 800, margin: '6px 0 18px' }}>{statusBig}</div>
          <button className={'btn primary big'} onClick={onToggle} disabled={toggling}>
            {running ? '■  停止翻译' : '▶  开始翻译'}
          </button>
          <div className="row" style={{ marginTop: 14 }}>
            <span className="muted">
              {running ? (status.desc || '监听队友语音中') : '队友说话后，字幕将自动出现在游戏画面上'}
            </span>
          </div>
          {cfg.capture_mode === 'loopback' && (
            <div className="muted" style={{ color: 'var(--warn)', marginTop: 10 }}>
              ⚠ 整机采集模式：电脑里的所有声音都会被识别。只翻译队友请到 设置 → 采集模式 改为「虚拟声卡线路」。
            </div>
          )}
        </div>

        <div className="card" style={{ width: 300, flexShrink: 0 }}>
          <h2 className="h2">当前音色</h2>
          <select value={voice} style={{ margin: '12px 0' }}
                  onChange={async e => { setVoice(e.target.value); await patchCfg({ tts_voice: e.target.value }) }}>
            <option value="">自动（按语言选多语人声）</option>
            {voices.map(([name, label]) => <option key={name} value={name}>{label}</option>)}
          </select>
          <div className="row">
            <button className="btn primary grow" disabled={previewing}
                    onClick={async () => {
              setPreviewing(true)
              try { await call('preview_tts') } catch (e) { setPreviewing(false); bus.emit('notice', { text: '试听启动失败：' + e }) }
            }}>
              {previewing ? '🔊 试听中…' : '🔊 试听音色'}
            </button>
            <button className="btn" style={{ flexShrink: 0 }} title="立即停止朗读"
                    onClick={() => { setPreviewing(false); call('stop_tts').catch(() => {}) }}>■ 停止</button>
          </div>
          <div className="row" style={{ marginTop: 8 }}>
            <button className="btn" style={{ flex: 1 }} onClick={goSettings}>音色调节</button>
          </div>
          <div className="muted" style={{ marginTop: 10 }}>
            识别中会自动暂停朗读，防止回声误触发。
          </div>
        </div>
      </div>

      <div className="card" style={{ marginBottom: 16 }}>
        <div className="row" style={{ justifyContent: 'space-between' }}>
          <h2 className="h2">按住说话（反向翻译）</h2>
          <span className="grow" />
          <span className="pill">{pttKey ? prettyHotkey(pttKey) : '未设置'}</span>
        </div>
        <div className="muted" style={{ margin: '8px 0 12px', lineHeight: 1.8 }}>
          按住 <b>{pttKey ? prettyHotkey(pttKey) : '下方设置的组合键'}</b> 说中文 → 松开后自动
          识别、翻译成队友语言{cfg.auto_copy ? '并复制到剪贴板' : ''}，直接 <b>Ctrl+V</b> 发出去。
          游戏中无需切回本软件。
        </div>
        <HotkeyInput label="按住说话" value={pttKey} allowSingle hint="点这里然后按键即可，单键也行（如 V）——按住不放说话，松开翻译"
                      siblings={[{ label: '锁定穿透', value: cfg.hotkey_lock },
                                { label: '回看字幕', value: cfg.hotkey_review },
                                { label: '固定/拖动', value: cfg.hotkey_move }]}
                      onChange={async v => {
                        const nc = await patchCfg({ hotkey_ptt: v })
                        setPttKey(v)
                        if (v) bus.emit('notice', { text: '按住说话热键已设为 ' + prettyHotkey(v) })
                        return nc
                      }} />
        <div className="row" style={{ flexWrap: 'wrap', marginTop: 2 }}>
          <button className="btn" onClick={goSettings}>更多设置</button>
          <span className="muted">
            麦克风：{cfg.mic_device || '系统默认'} · 目标语言：{cfg.reverse_target_lang === 'en' ? '英语' : cfg.reverse_target_lang}
          </span>
        </div>
      </div>
      <div className="card" style={{ marginBottom: 16 }}>
        <div className="row" style={{ justifyContent: 'space-between' }}>
          <h2 className="h2">字幕开关</h2>
          <button className={'toggle' + (cfg.overlay_enabled ? ' on' : '')}
                  title={cfg.overlay_enabled
                    ? '字幕已开启，点击关闭' : '字幕已关闭，点击打开'}
                  onClick={async () => {
                    const want = !cfg.overlay_enabled
                    try {
                      await patchCfg({ overlay_enabled: want })
                      bus.emit('notice', { text: want ? '字幕已开启，出现字幕时会自动显示面板'
                                                     : '字幕已关闭' })
                    } catch (e) { /* patchCfg 已提示 */ }
                  }} />
        </div>
        <div className="row" style={{ marginTop: 12, flexWrap: 'wrap' }}>
          <label className="row" style={{ gap: 6 }}>
            <input type="checkbox" checked={showOriginal}
                   onChange={e => { setShowOriginal(e.target.checked); patchCfg({ show_original: e.target.checked }) }} />
            显示原文
          </label>
          <label className="row" style={{ gap: 6 }}>
            <input type="checkbox" checked={ttsEnabled}
                   onChange={e => { setTtsEnabled(e.target.checked); patchCfg({ tts_enabled: e.target.checked }) }} />
            译文朗读
          </label>
          <label className="row" style={{ gap: 6 }}>
            <input type="checkbox" checked={streamer}
                   onChange={e => { setStreamer(e.target.checked); patchCfg({ streamer_mode: e.target.checked }) }} />
            主播模式
          </label>
          <span className="grow" />
          {/* v0.2.11：改三态（Styles.jsx 同一判据，两处不能各写一套 ——
              项目约定：同一个判断只能有一份实现）。
              原来拿 `overlay_enabled`（含义是「**允许**显示字幕」）当成
              「正在显示」。但浮窗是**懒创建**的：队友不说话就不建窗。
              于是「配置开着、屏幕上没窗」时也显示绿色「字幕显示中」——
              真机 原话：「字幕没有显示，它那边的状态框却打到了
              绿色，显示为『已显示』。我需要重新把它关了再开，字幕才会出来。」

              懒创建是 刻意设计（避免空窗在屏幕上闪），
              不能为了迁就状态灯改成常驻窗口；正确做法是**如实显示实际状态**。*/}
          {!cfg.overlay_enabled
            ? <span className="pill gray">字幕已关闭</span>
            : cfg.overlay_visible === true
              ? <span className="pill green">字幕显示中 · 可在游戏画面查看</span>
              : <span className="pill orange">已开启 · 等队友说话时自动出现</span>}
          <button className="btn" style={{ flexShrink: 0 }} onClick={() => call('review_overlay').catch(() => {})}>
            把面板叫回屏幕
          </button>
          <span className="muted" style={{ flexBasis: '100%', marginTop: 4 }}>
            {cfg.overlay_enabled
              ? `面板默认固定并鼠标穿透；按 ${cfg.hotkey_move ? prettyHotkey(cfg.hotkey_move) : '设置里的热键'} 可临时解锁拖动`
              : '字幕总开关是关闭的，此时不会出现任何面板。请先打开上面的开关。'}
          </span>
        </div>
      </div>

      <div className="grid2">
        <div className="card">
          <h2 className="h2">运行状态</h2>
          <div className="muted" style={{ margin: '10px 0 6px' }}>端到端延迟</div>
          <div style={{ fontSize: 26, fontWeight: 800 }}>{latency != null ? latency + ' ms' : '—'}</div>
          <div className="muted" style={{ marginTop: 4 }}>语音结束 → 中文字幕显示</div>
        </div>
        <div className="card">
          <h2 className="h2">快捷操作</h2>
          <div className="row" style={{ marginTop: 12, flexWrap: 'wrap' }}>
            <button className="btn" onClick={async () => {
              const r = await call('review_overlay').catch(e => ({ ok: false, reason: String(e) }))
              if (!r || !r.ok) bus.emit('notice', { text: '字幕面板未能显示，请查看设置或日志' })
            }}>回看最近字幕</button>
            <button className="btn" onClick={() => call('toggle_lock').catch(() => {})}>锁定/解锁浮窗</button>
            <button className="btn" onClick={() => call('open_url', 'https://cloud.siliconflow.cn/account/ak').catch(() => {})}>查额度官网</button>
          </div>
          <div className="muted" style={{ marginTop: 10 }}>
            提示：浮窗锁定后鼠标穿透，不会挡住游戏操作（默认 Ctrl+Alt+Q）。
          </div>
        </div>
      </div>
    </div>
  )
}
