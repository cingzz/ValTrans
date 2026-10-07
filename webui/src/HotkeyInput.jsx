// 热键录制输入框：点击后直接按下组合键即捕获，替代「一个字母一个字母地打字」。
//
// 存储格式沿用 pynput 的 '<ctrl>+<alt>+<shift>+<cmd>+key'，
// 显示格式转成 'Ctrl + Alt + Q' 给人看。
import React, { useEffect, useRef, useState } from 'react'

const MODS = [
  { code: 'Control', flag: 'ctrl', label: 'Ctrl' },
  { code: 'Alt', flag: 'alt', label: 'Alt' },
  { code: 'Shift', flag: 'shift', label: 'Shift' },
  { code: 'Meta', flag: 'cmd', label: 'Win' },
]

// 单独按这些键不算「组合完成」，先攒着
const PASSIVE = new Set([
  'Control', 'Alt', 'Shift', 'Meta', 'OS', 'CapsLock', 'NumLock', 'ScrollLock',
  'ContextMenu', 'Escape', 'Tab', 'Backquote',
])

export function prettyHotkey(raw) {
  if (!raw) return '未设置'
  return raw
    .split('+')
    .map(s => {
      const t = s.replace(/[<>]/g, '')
      return MODS.find(m => m.flag === t)?.label
        || (t.length === 1 ? t.toUpperCase() : t)
    })
    .join(' + ')
}

function conflictOf(hk, all) {
  if (!hk) return ''
  const hit = all.find(o => o && o.value === hk)
  return hit ? `与「${hit.label}」重复` : ''
}

export default function HotkeyInput({ value, onChange, label, hint, siblings = [], allowSingle = false }) {
  const [recording, setRecording] = useState(false)
  const [err, setErr] = useState('')
  const boxRef = useRef(null)
  const accRef = useRef({ mods: [], key: null })

  useEffect(() => {
    if (!recording) return
    // 录制期间阻止默认行为，避免 Ctrl+Q 触发浏览器/系统快捷键
    const onKeyDown = e => {
      e.preventDefault()
      e.stopPropagation()
      if (e.code === 'Escape') { setRecording(false); setErr(''); return }
      const mod = MODS.find(m => m.code === e.code)
      if (mod) {
        if (!accRef.current.mods.includes(mod.flag)) accRef.current.mods.push(mod.flag)
        return
      }
      if (PASSIVE.has(e.code)) return
      // pynput 的键名规则（实测）：只认「单字符字母/数字」或「<特殊键>」尖括号形式。
      // 裸写 f5 / space 会直接 ValueError，所以这里做严格归一。
      let rawKey = e.key.length === 1 ? e.key.toLowerCase() : null
      const SPECIAL = { ArrowUp: 'up', ArrowDown: 'down', ArrowLeft: 'left', ArrowRight: 'right',
                        Enter: 'enter', Home: 'home', End: 'end', PageUp: 'page_up',
                        PageDown: 'page_down', Space: 'space', Backquote: '',
                        Tab: 'tab', Backspace: 'backspace', Delete: 'delete' }
      if (rawKey === null && SPECIAL[e.code]) {
        rawKey = '<' + SPECIAL[e.code] + '>'
      } else if (rawKey === null) {
        setErr('主键请用字母或数字（如 D / F / 1）。功能键 F1-F12、空格暂不支持')
        return
      }
      accRef.current.key = rawKey
      const { mods, key } = accRef.current
      if (mods.length === 0 && !allowSingle) {
        setErr('请至少加一个修饰键（Ctrl / Alt / Shift），避免和游戏按键冲突')
        return
      }
      const raw = [...mods.map(m => `<${m}>`), key].join('+')
      onChange(raw)
      setRecording(false)
      setErr('')
      accRef.current = { mods: [], key: null }
    }
    const onKeyUp = e => {
      const mod = MODS.find(m => m.code === e.code)
      if (mod) accRef.current.mods = accRef.current.mods.filter(f => f !== mod.flag)
    }
    window.addEventListener('keydown', onKeyDown, true)
    window.addEventListener('keyup', onKeyUp, true)
    return () => {
      window.removeEventListener('keydown', onKeyDown, true)
      window.removeEventListener('keyup', onKeyUp, true)
    }
  }, [recording, onChange])

  const dup = conflictOf(value, siblings)
  const bad = err || dup

  return (
    <div style={{ marginBottom: 12 }}>
      <div className="form-row" style={{ marginBottom: 6 }}>
        <label style={{ width: 96, flexShrink: 0, color: 'var(--muted)', fontSize: 13 }}>{label}</label>
        <button
          ref={boxRef}
          type="button"
          className={'grow' + (recording ? ' recording' : '')}
          style={{
            textAlign: 'left', cursor: 'pointer', fontWeight: recording ? 700 : 500,
            borderColor: recording ? 'var(--primary)' : undefined,
            background: recording ? 'var(--primary-soft)' : undefined,
            color: recording ? 'var(--primary-text)' : undefined,
          }}
          onClick={() => { accRef.current = { mods: [], key: null }; setErr(''); setRecording(r => !r) }}
        >
          {recording ? '请按下组合键…（Esc 取消）' : prettyHotkey(value)}
        </button>
        {value && !recording && (
          <button className="btn" style={{ flexShrink: 0 }}
                  onClick={() => onChange('')}>清除</button>
        )}
      </div>
      <div className="muted" style={{ color: bad ? 'var(--danger)' : undefined }}>
        {recording ? (allowSingle ? '直接按下想要的按键即可，单键也可以（如 V）' : '直接按下想要的组合键，例如 Ctrl + Shift + D') : (hint || '点击后按组合键即可设置')}
        {bad ? ' · ' + bad : ''}
      </div>
    </div>
  )
}