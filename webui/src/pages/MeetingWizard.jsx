import React, { useCallback, useEffect, useState } from 'react'
import { call } from '../api.js'

// 各家会议软件把麦克风改到 CABLE Output 的菜单路径。
// ★ 为什么必须逐个列出来，而不是笼统写「在设置里改麦克风」
//   笼统说法必然失败：用户看到「改麦克风」不知道要去哪改，
//   于是跑去改系统默认麦克风（完全另一回事），问题依然存在。
//   路径按 2026 年各客户端的实际菜单写的；版本不同文案可能有出入，
//   所以下面还给了「找不到时的通用找法」。
const APPS = [
  { name: 'Zoom', path: '右下角「…」→ 音频 → 麦克风' },
  { name: '腾讯会议', path: '会前「设置」→ 音频 → 麦克风' },
  { name: 'Microsoft Teams', path: '右上「…」→「设置」→「音频和视频」' },
  { name: 'Google Meet', path: '点「…」→「设备设置」→「音频」' },
  { name: 'Discord', path: '左下齿轮 → 语音和视频 → 输入设备' },
  { name: 'Slack', path: '右上头像 → 设置 → 音频' },
]

const ICON = { ok: '✓', todo: '○', wait: '…' }

export default function MeetingWizard({ cfg, patchCfg, running, onStart, onClose }) {
  const [rep, setRep] = useState(null)
  const [busy, setBusy] = useState('')
  const [level, setLevel] = useState(0)
  const [showApps, setShowApps] = useState(false)

  const refresh = useCallback(async () => {
    try {
      const r = await call('meeting_check')
      setRep(r)
      if (typeof r.level === 'number' && r.level >= 0) setLevel(r.level)
      return r
    } catch (e) {
      setRep({ error: String(e && e.message ? e.message : e) })
      return null
    }
  }, [])

  useEffect(() => { refresh() }, [refresh])

  // 只在**确实在跑**的时候轮询电平。没在跑时轮询毫无意义，
  // 而空转的 setInterval 在关闭后没清掉是最常见的内存泄漏。
  useEffect(() => {
    if (!running) return
    const t = setInterval(async () => {
      try { setLevel(await call('get_level')) } catch (_) {}
    }, 700)
    return () => clearInterval(t)
  }, [running])

  const step = (k) => (rep?.steps || []).find(s => s.key === k) || null
  const cable = step('cable')
  const capture = step('capture')
  const levelStep = step('level')

  const install = async () => {
    setBusy('install')
    try {
      const r = await call('install_driver')
      // ★ 如实显示失败原因。install_driver 以前是静默 return/pass，
      //   用户点了没反应也不知道哪错了 —— 那是本项目明令禁止的反模式。
      if (!r?.ok) setBusy(r?.msg || '安装器未能启动')
      else {
        setBusy('已调起安装器，装完后点「重新检测」')
        setTimeout(() => refresh(), 1500)
      }
    } catch (e) {
      setBusy('调起失败：' + (e && e.message ? e.message : e))
    }
  }

  const useCable = async () => { await patchCfg({ capture_mode: 'cable' }); refresh() }

  return (
    <div className="modal-mask">
      <div className="modal" style={{ maxWidth: 620 }}>
        <div className="row" style={{ marginBottom: 16 }}>
          <h1 className="h1" style={{ fontSize: 18 }}>会议 / 通话同传</h1>
          <span className="grow" />
          <button className="btn" onClick={onClose}>关闭</button>
        </div>

        <p style={{ lineHeight: 1.8, marginTop: 0 }}>
          让对方在 Zoom / 腾讯会议 / Teams 里说外语时，直接出中文字幕。
          原理和打游戏一样——<b>虚拟声卡</b>把对方的声音送进软件，
          区别只在<b>两端接的东西不一样</b>。
        </p>

        {rep?.error && <div className="notice"><span className="grow">检查失败：{rep.error}</span></div>}
        {rep && !rep.error && (
          <div className="card" style={{
            background: rep.ready ? '#F4FBF6' : '#FBFAF8',
            boxShadow: 'none',
            border: '1px solid var(--stroke)',
            margin: '12px 0', padding: 14, lineHeight: 1.8,
          }}>
            <b>{rep.headline}</b>
          </div>
        )}

        {/* ---- 1 虚拟声卡 ---- */}
        <div className="card" style={{ background: '#FBFAF8', boxShadow: 'none', border: '1px solid var(--stroke)', margin: '10px 0', padding: 14 }}>
          <div style={{ fontWeight: 600 }}>{ICON[cable?.ok ? 'ok' : 'todo']} 1. 虚拟声卡（VB-CABLE）</div>
          <div className="muted" style={{ marginTop: 4 }}>{cable?.detail || '检测中…'}</div>
          {cable && !cable.ok && (
            <div style={{ marginTop: 8 }}>
              <button className="btn primary" disabled={busy === 'install'} onClick={install}>
                {busy === 'install' ? '正在调起…' : '🔧 一键安装官方驱动（约 30 秒，会弹 UAC）'}
              </button>
              <button className="btn" style={{ marginLeft: 8 }} onClick={refresh}>重新检测</button>
              {busy && busy !== 'install' && <span className="muted" style={{ marginLeft: 8 }}>{busy}</span>}
            </div>
          )}
        </div>

        {/* ---- 2 会议软件里改麦克声卡 ---- */}
        <div className="card" style={{ background: '#FBFAF8', boxShadow: 'none', border: '1px solid var(--stroke)', margin: '10px 0', padding: 14 }}>
          <div style={{ fontWeight: 600 }}>{ICON[cable?.ok ? 'ok' : 'wait']} 2. 在会议软件里把麦克风改成 CABLE Output</div>
          <div className="muted" style={{ marginTop: 4, lineHeight: 1.8 }}>
            这一步<b>不做就完全没有声音</b>——而现象是「软件启动了但不出字」，
            很容易被当成软件坏了。会议软件要把它<b>发出去的</b>麦克风
            指向虚拟声卡。
          </div>
          <button className="btn" style={{ marginTop: 8 }} onClick={() => setShowApps(s => !s)}>
            {showApps ? '收起各家路径' : '查我用的会议软件怎么改'}
          </button>
          {showApps && (
            <div style={{ marginTop: 8, fontSize: 13 }}>
              {APPS.map(a => (
                <div key={a.name} className="row" style={{ padding: '3px 0' }}>
                  <b style={{ minWidth: 132 }}>{a.name}</b>
                  <span className="grow muted">{a.path}</span>
                </div>
              ))}
              <div className="muted" style={{ marginTop: 6 }}>
                找不到？通用找法：会议软件「设置 / 偏好设置 → 音频 → 麦克风 / 输入设备」，
                下拉里选名字带 <b>CABLE Output</b> 或 <b>VB-Audio Virtual Cable</b> 的那一项。
              </div>
            </div>
          )}
        </div>

        {/* ---- 3 本软件侧 ---- */}
        <div className="card" style={{ background: '#FBFAF8', boxShadow: 'none', border: '1px solid var(--stroke)', margin: '10px 0', padding: 14 }}>
          <div style={{ fontWeight: 600 }}>{ICON[capture?.ok ? 'ok' : 'todo']} 3. 本软件的采集方式</div>
          <div className="muted" style={{ marginTop: 4 }}>{capture?.detail || '读取中…'}</div>
          {capture && !capture.ok && (
            <button className="btn primary" style={{ marginTop: 8 }} onClick={useCable}>
              改成虚拟声卡模式
            </button>
          )}
          {capture?.ok && capture.detail.includes('免驱动') && (
            <div className="muted" style={{ marginTop: 6 }}>
              免驱动模式在会议里会把你自己的声音也采进去。想只要对方的声音，
              <button className="btn" style={{ marginLeft: 6 }} onClick={useCable}>改用虚拟声卡</button>
            </div>
          )}
        </div>

        {/* ---- 4 自检：唯一一条「事实」 ---- */}
        <div className="card" style={{ background: '#FBFAF8', boxShadow: 'none', border: '1px solid var(--stroke)', margin: '10px 0', padding: 14 }}>
          <div style={{ fontWeight: 600 }}>
            {ICON[levelStep?.ok ? 'ok' : running ? 'todo' : 'wait']} 4. 自检：声音真的进来了吗
          </div>
          <div className="muted" style={{ marginTop: 4, lineHeight: 1.8 }}>
            前面几项都是<b>配置</b>，只有这一条是<b>事实</b>。
            全对但电平为 0，说明线没接上——回到第 2 步。
          </div>
          <div style={{ marginTop: 10 }}>
            <div className="row" style={{ marginBottom: 4 }}>
              <span className="muted grow">输入电平</span>
              <span className="muted">{running ? level : '未启动'}</span>
            </div>
            <div style={{ height: 8, background: 'var(--stroke)', borderRadius: 4, overflow: 'hidden' }}>
              <div style={{
                width: (running ? Math.min(100, level) : 0) + '%',
                height: '100%', borderRadius: 4,
                background: level > 3 ? 'var(--ok)' : 'var(--stroke)',
                transition: 'width .18s',
              }} />
            </div>
          </div>
          <div className="row" style={{ marginTop: 10 }}>
            {!running ? (
              <button className="btn primary" onClick={onStart}>开始翻译并检测</button>
            ) : (
              <button className="btn" onClick={refresh}>重新检测</button>
            )}
            <span className="grow" />
            <span className="muted">对着麦克风说一句话试试</span>
          </div>
          {levelStep && !levelStep.ok && levelStep.action && (
            <div className="muted" style={{ marginTop: 8 }}>💡 {levelStep.action}</div>
          )}
        </div>

        {/* ---- 5 其余检查项（Key 等）---- */}
        <div className="card" style={{ background: '#FBFAF8', boxShadow: 'none', border: '1px solid var(--stroke)', margin: '10px 0', padding: 14 }}>
          <div style={{ fontWeight: 600, marginBottom: 6 }}>其余检查项</div>
          {(rep?.steps || [])
            .filter(s => !['cable', 'capture', 'level'].includes(s.key))
            .map(s => (
              <div key={s.key} style={{ padding: '4px 0' }}>
                <div>{ICON[s.ok ? 'ok' : 'todo']} {s.title}</div>
                {!s.ok && s.detail && <div className="muted" style={{ paddingLeft: 18 }}>{s.detail}</div>}
                {!s.ok && s.action && <div className="muted" style={{ paddingLeft: 18 }}>→ {s.action}</div>}
              </div>
            ))}
        </div>

        <div className="row" style={{ marginTop: 16 }}>
          <span className="grow" />
          <button className="btn" onClick={onClose}>知道了</button>
        </div>
      </div>
    </div>
  )
}