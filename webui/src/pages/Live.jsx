import React, { useEffect, useRef, useState } from 'react'
import { bus } from '../api.js'
import ReportDialog from '../components/ReportDialog'
import '../styles/donate.css'

export default function Live() {
  const [subs, setSubs] = useState([])
  const [level, setLevel] = useState(0)
  const [ptt, setPtt] = useState('就绪')
  const [avg, setAvg] = useState({ sum: 0, n: 0 })
  // v0.2.19（P2）：失败/丢段一律以后端 stats 为真值。
  // 旧实现是前端数 ev.fallback —— 刷新/切页归零、事件丢了就少���，
  // 而 stats 是管线自己累加的，跨页面、跨刷新都不丢。
  const [fails, setFails] = useState(0)
  const [dropped, setDropped] = useState(0)
  // v0.2.11：点某条历史消息 -> 弹误报窗
  const [reportItem, setReportItem] = useState(null)
  const feedRef = useRef(null)

  useEffect(() => {
    const off1 = bus.on('subtitle', ev => {
      setSubs(list => [...list.slice(-49), ev])
      // 累计平均延迟要覆盖全部历史，subs 只保留最近 50 条，
      // 因此另用 running 累加器统计（旧代码拿 50 条之和除以全部条数，越到后面越偏小）
      setAvg(a => ({ sum: a.sum + (ev.latency_ms || 0), n: a.n + 1 }))
      if (ev.fallback) setFails(f => f + 1)
    })
    const off3 = bus.on('ptt', s => setPtt({ recording: '录音中…', translating: '翻译中…', ready: '就绪' }[s] || s))
    // 电平表：JS 主动轮询（轻量，200ms）
    const t = setInterval(() => {
      window.pywebview?.api?.get_level?.().then(v => setLevel(v)).catch(() => {})
    }, 200)
    // v0.2.19（P2）：失败/丢段读后端真值。
    // 用 try/catch 包住且**失败时不动 state** —— 接口异常不该把
    // 计数清零（那正是「明明有问题却显示 0」的假绿）。
    const t2 = setInterval(() => {
      const api = window.pywebview?.api
      if (!api?.get_state) return
      api.get_state().then(r => {
        const st = (r && r.stats) || null
        if (!st) return
        if (typeof st.fail === 'number') setFails(st.fail)
        if (typeof st.dropped === 'number') setDropped(st.dropped)
      }).catch(() => {})
    }, 3000)
    return () => { off1(); off3(); clearInterval(t); clearInterval(t2) }
  }, [])

  useEffect(() => {
    if (feedRef.current) feedRef.current.scrollTop = feedRef.current.scrollHeight
  }, [subs])

  const avgMs = avg.n ? Math.round(avg.sum / avg.n) : null

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      <div className="row" style={{ marginBottom: 14 }}>
        <h1 className="h1">实时翻译</h1>
        <span className="grow" />
        {/* v0.2.11：手动添加误报的入口。
            需求背景：「你也可以点击『误报』，然后自己输入英文单词，
            再加上中文意思」—— 用于「听清了但软件没识别出来」的情况：
            那种情况没有现成的历史消息可点，所以必须能自己填原话。*/}
        <button className="btn" onClick={() => setReportItem({ manual: true })}>
          误报
        </button>
        <span className="pill gray">本局 {avg.n} 条</span>
        <span className="pill gray">平均延迟 {avgMs != null ? avgMs + 'ms' : '—'}</span>
        <span className="pill gray">失败 {fails}</span>
        {/* v0.2.19（P2）：丢段是**静默**的（队列满时丢最旧的一段），
            字幕断一截而用户不知道为什么。>0 才显示，0 时不占地方。 */}
        {dropped > 0 && (
          <span
            className="pill"
            title={`已丢弃 ${dropped} 段：识别/翻译队列积压，本局有句子没显示出来`}
            style={{ background: '#FFF1E6', color: '#B26A00' }}
          >
            丢段 {dropped}
          </span>
        )}
      </div>

      <div ref={feedRef} className="grow" style={{ overflowY: 'auto', minHeight: 0 }}>
        {subs.length === 0 ? (
          <div className="empty">
            <div className="big-ico">💬</div>
            <div>还没有收到队友的语音</div>
            <div>点「开始翻译」后，队友的外语会在这里实时变成中文字幕</div>
          </div>
        ) : subs.map((s, i) => (
          <div className="sub-item" key={i}>
            {/* v0.2.21：队友说中文时 translate_gate 照抄，original===translated，
                无条件画两行就是**同一句话显示两遍**（真机 截图）。
                ★ 判断在**后端**算好了送过来（SubtitleEvent.show_original），
                这里只读不算 —— 「是不是中文」只有一份实现（translate_gate.
                looks_chinese），让 JS 再判一次必然漂移。 */}
            {s.show_original !== false && <div className="orig">{s.original}</div>}
            <div className="trans" style={{ color: s.translated ? 'var(--text)' : 'var(--danger)' }}>
              {s.translated || s.error || '翻译失败'}
            </div>
            <div className="meta">
              {s.time} · {s.latency_ms}ms{s.fallback ? ' · 降级' : ''}{s.mine ? ' · 我' : ''}
              {/* v0.2.11：误报入口挂在**每条历史消息**上。
                  需求「『误报』根本就不应该放在『关于』里面。
                  其实可以放到『历史消息』那一栏里面」—— 判断正确：
                  误报是**对局时的动作**，刚看到翻错顺手点最自然；
                  放到设置页里，用户想得起来时那句早滚过去了。
                  只给「队友说的」句子显示「误报」—— 我自己说的那句
                  （PTT）是用户主动输入的，翻译错了是自己没说清楚，
                  报误报没有意义。 */}
              {!s.mine && (
                <button
                  className="sub-report"
                  title="这条翻译不准？点一下纠正它"
                  onClick={() => setReportItem(s)}
                >
                  误报
                </button>
              )}
            </div>
          </div>
        ))}
      </div>

      <div className="card" style={{ marginTop: 12, padding: '14px 18px' }}>
        <div className="row">
          <span className="muted" style={{ width: 96 }}>队友语音电平</span>
          <div className="prog grow"><div style={{ width: level + '%' }} /></div>
          <span className="muted" style={{ width: 120, textAlign: 'right' }}>PTT: {ptt}</span>
        </div>
      </div>

      <ReportDialog item={reportItem} onClose={() => setReportItem(null)} />
    </div>
  )
}
