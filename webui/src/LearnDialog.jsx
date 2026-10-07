/* 自学习确认弹窗 —— 「检测到这几个词使用频繁，是否要加入？」
   设计要点见 src/services/learning.py 与 项目约定。 */
import React, { useEffect, useRef, useState } from 'react'

const call = (m, ...a) => window.pywebview?.api?.[m]?.(...a)

function LearnDialog({ items, onClose }) {
  const [auto, setAuto] = useState(false)
  const [busy, setBusy] = useState(false)
  const boxRef = useRef(null)

  useEffect(() => {
    const onKey = (e) => {
      if (e.key === 'Escape') onClose()
      if (e.key === 'Enter' && !busy) { e.preventDefault(); confirmAll() }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [busy])

  async function confirmAll() {
    if (busy || !items?.length) return
    setBusy(true)
    try {
      await call('learn_confirm', items, auto)
    } finally {
      setBusy(false)
      onClose()
    }
  }

  async function dismiss() {
    if (busy) return
    setBusy(true)
    try { await call('learn_dismiss') } finally { setBusy(false); onClose() }
  }

  if (!items?.length) return null

  const n = items.length

  return (
    <div className="ld-backdrop" ref={boxRef}>
      <div className="ld-card" role="dialog" aria-modal="true">
        <div className="ld-head">
          <div className="ld-badge">{'✦'}</div>
          <div>
            <h2>检测到 {n} 句常用表达</h2>
            <p>这些是队友反复说、但本地词库里还没有的句子。加入后 0 毫秒即时命中，不再消耗云端。</p>
          </div>
        </div>

        <div className="ld-list">
          {items.map((it, i) => (
            <div className="ld-item" key={it.src + i}
                 style={{ animationDelay: `${i * 45}ms` }}>
              <div className="ld-src">{it.src}</div>
              <div className="ld-row">
                <span className="ld-arrow">→</span>
                <span className="ld-dst">{it.dst}</span>
                <span className="ld-meta">说了 {it.count} 次 · 跨 {it.span_min} 分钟</span>
              </div>
            </div>
          ))}
        </div>

        <div className="ld-foot">
          <label className="ld-check" onClick={e => e.stopPropagation()}>
            <input type="checkbox" checked={auto} disabled={busy}
                   onChange={e => setAuto(e.target.checked)} />
            <span>下次不用询问，自动加入</span>
          </label>
          <div className="ld-btns">
            <button className="ld-btn ghost" onClick={dismiss} disabled={busy}>
              暂不
            </button>
            <button className="ld-btn primary" onClick={confirmAll} disabled={busy}>
              {busy ? '加入中…' : '加入全部'}
            </button>
          </div>
        </div>
      </div>

      <style>{`
        .ld-backdrop {
          position: fixed; inset: 0; z-index: 9000;
          background: rgba(16, 20, 28, 0.42);
          backdrop-filter: blur(10px) saturate(120%);
          -webkit-backdrop-filter: blur(10px) saturate(120%);
          display: flex; align-items: center; justify-content: center;
          animation: ldFade .18s ease-out;
        }
        .ld-card {
          width: min(560px, 92vw);
          background: linear-gradient(180deg, #FFFFFF 0%, #FBFCFE 100%);
          border: 1px solid rgba(255,255,255,.7);
          border-radius: 18px;
          box-shadow:
            0 1px 2px rgba(16,24,40,.06),
            0 12px 32px -8px rgba(16,24,40,.18),
            0 40px 80px -24px rgba(16,24,40,.24);
          overflow: hidden;
          animation: ldRise .26s cubic-bezier(.16,1,.3,1);
        }
        .ld-head {
          display: flex; gap: 13px; align-items: flex-start;
          padding: 20px 22px 14px;
        }
        .ld-badge {
          flex: none; width: 34px; height: 34px; border-radius: 11px;
          display: grid; place-items: center; font-size: 15px;
          background: linear-gradient(135deg, #4C8DFF, #2F6FE0);
          color: #fff; font-weight: 700;
          box-shadow: 0 3px 10px -2px rgba(47,111,224,.5);
        }
        .ld-head h2 {
          margin: 0 0 4px; font-size: 15.5px; font-weight: 700;
          color: #131820; letter-spacing: -.01em;
        }
        .ld-head p {
          margin: 0; font-size: 12.5px; line-height: 1.65; color: #6B7684;
        }
        .ld-list {
          max-height: 46vh; overflow-y: auto;
          padding: 2px 14px 4px; margin: 0 0 2px;
        }
        .ld-item {
          padding: 9px 11px; border-radius: 11px; margin-bottom: 5px;
          background: #F7F9FC; border: 1px solid #EDF0F5;
          opacity: 0; transform: translateY(6px);
          animation: ldItem .28s cubic-bezier(.16,1,.3,1) forwards;
        }
        .ld-item:last-child { margin-bottom: 0; }
        .ld-src {
          font: 500 12.5px/1.5 ui-monospace, SFMono-Regular, Consolas, monospace;
          color: #7A8699; word-break: break-word;
        }
        .ld-row { display: flex; align-items: baseline; gap: 8px; margin-top: 2px; }
        .ld-arrow { color: #C3CBD8; font-size: 12px; }
        .ld-dst { font-size: 13.5px; font-weight: 600; color: #131820; }
        .ld-meta {
          margin-left: auto; font-size: 11px; color: #98A2B3;
          white-space: nowrap; flex: none;
        }
        .ld-foot {
          display: flex; align-items: center; justify-content: space-between;
          gap: 14px; padding: 14px 18px 16px;
          border-top: 1px solid #EEF1F5;
          background: linear-gradient(180deg, rgba(250,251,253,0), #F7F9FC);
        }
        .ld-check {
          display: flex; align-items: center; gap: 7px;
          font-size: 12.5px; color: #55606F; cursor: pointer; user-select: none;
        }
        .ld-check input {
          width: 15px; height: 15px; accent-color: #2F6FE0; cursor: pointer;
        }
        .ld-btns { display: flex; gap: 8px; }
        .ld-btn {
          border: none; border-radius: 9px; padding: 8px 17px;
          font-size: 13px; font-weight: 600; cursor: pointer;
          transition: transform .12s, box-shadow .12s, background .12s;
        }
        .ld-btn:active:not(:disabled) { transform: translateY(1px); }
        .ld-btn:disabled { opacity: .55; cursor: default; }
        .ld-btn.ghost {
          background: #EDF0F5; color: #55606F;
        }
        .ld-btn.ghost:hover:not(:disabled) { background: #E3E7EE; }
        .ld-btn.primary {
          background: linear-gradient(180deg, #3B7BEE, #2F6FE0);
          color: #fff; box-shadow: 0 2px 8px -1px rgba(47,111,224,.42);
        }
        .ld-btn.primary:hover:not(:disabled) {
          box-shadow: 0 4px 14px -2px rgba(47,111,224,.55);
        }
        @keyframes ldFade { from { opacity: 0 } to { opacity: 1 } }
        @keyframes ldRise {
          from { opacity: 0; transform: translateY(14px) scale(.975) }
          to   { opacity: 1; transform: none }
        }
        @keyframes ldItem {
          to { opacity: 1; transform: none }
        }
        @media (prefers-reduced-motion: reduce) {
          .ld-backdrop, .ld-card, .ld-item { animation: none; opacity: 1; }
        }
      `}</style>
    </div>
  )
}

export default LearnDialog
