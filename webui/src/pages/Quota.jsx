import React, { useEffect, useState } from 'react'
import { bus, call } from '../api.js'

export default function Quota() {
  const [cards, setCards] = useState({})
  const [loading, setLoading] = useState(false)

  const refresh = async () => {
    setLoading(true)
    await call('refresh_quota')
  }
  useEffect(() => {
    const off = bus.on('quota', data => { setCards(data); setLoading(false) })
    refresh()
    return off
  }, [])

  return (
    <div>
      <div className="row" style={{ marginBottom: 16 }}>
        <h1 className="h1">我的额度</h1>
        <span className="grow" />
        <button className="btn primary" onClick={refresh} disabled={loading}>
          {loading ? '查询中…' : '查询云端余额'}
        </button>
      </div>
      <div className="grid2">
        {Object.entries(cards).map(([name, c]) => (
          <div className="card" key={name}>
            <h2 className="h2" style={{ textTransform: 'none' }}>{name}</h2>
            <div style={{ marginTop: 10, fontSize: 14, color: c.ok ? 'var(--text)' : 'var(--danger)', whiteSpace: 'pre-wrap' }}>
              {c.text}
            </div>
          </div>
        ))}
        {Object.keys(cards).length === 0 && !loading && (
          <div className="card muted">点「查询云端余额」获取各服务商额度状态。</div>
        )}
      </div>
      <div className="card muted" style={{ marginTop: 16 }}>
        说明：本软件不内置账号体系，云端额度即各服务商 API 免费额度，以服务商官网为准。
        硅基流动余额接口已下线，请登录 cloud.siliconflow.cn 控制台查看。
      </div>
    </div>
  )
}
