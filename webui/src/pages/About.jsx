import React, { useState } from 'react'
import Donate from '../components/Donate'
import UpdatePanel from '../components/UpdatePanel'
import FeedbackDialog from '../components/FeedbackDialog'
import { callOr } from '../api'
import '../styles/donate.css'

// v0.2.11 精简：需求背景「关于里面的内容是不是太杂了呀？很多人根本不会
// 完全看的，你要精简一点。」
//
// 精简的做法不是删信息，是**分层**：首屏只留「是什么 / 作者 / 授权」三件事，
// 其余（隐私、开源细节、合规全文）收进「详情」——点开才看，不点不占地方。
// 一屏能看完，才有人愿意看。
export default function About({ version }) {
  const [showFeedback, setShowFeedback] = useState(false)

  return (
    <div>
      <h1 className="h1" style={{ marginBottom: 16 }}>关于</h1>

      <div className="card">
        <div style={{ fontFamily: 'Bahnschrift, "Segoe UI", sans-serif',
                      fontSize: 20, fontWeight: 700 }}>
          ValTrans <span style={{ color: 'var(--muted)', fontWeight: 400 }}>
            v{version}</span>
        </div>
        <div className="muted" style={{ marginTop: 8, lineHeight: 1.8 }}>
          瓦罗兰特外服实时语音翻译。队友说外语，屏幕上出中文字幕。
          <br />
          翻译走你自己的 API Key，<b>不经过任何服务器</b>，无广告、无内购。
        </div>
        <div className="muted" style={{ marginTop: 10, fontSize: 12.5 }}>
          作者 <b>cingzz</b> ·
          <a href="https://github.com/cingzz" target="_blank" rel="noreferrer"
             style={{ color: 'var(--accent)' }}> github.com/cingzz</a>
          <span style={{ marginLeft: 10 }}>GPL-3.0 + 商业授权</span>
        </div>
      </div>

      <UpdatePanel
        version={version}
        onCheck={() => callOr('check_update')}
        openUrl={(u) => callOr('open_url', u)}
      />

      {/* ★ v0.2.22：上报反馈入口。
          为什么放在「关于」页而不是首页：对局中不该被打断，
          而「关于」本来就是「版本/作者/求助」这类信息的归处。
          为什么不静默上传：GitHub 建 issue 必须带密钥，
          密钥不能随安装包分发 —— 详见 FeedbackDialog.jsx 顶部说明。 */}
      <div className="card" style={{ marginTop: 12,
                                     display: 'flex', alignItems: 'center',
                                     gap: 10 }}>
        <h2 className="h2" style={{ margin: 0, flex: 1 }}>上报反馈</h2>
        <button className="btn" onClick={() => setShowFeedback(true)}>
          上报反馈
        </button>
      </div>
      <div className="muted" style={{ marginTop: 6, fontSize: 12.5,
                                       lineHeight: 1.7, marginBottom: 12 }}>
        遇到装不上、浮窗不显示、翻译明显不对这类问题时，点这里会自动附上
        版本、系统与日志尾巴，再把你写的说明带到 GitHub 提交。
        本程序不会自动发送，最后一步在浏览器里由你确认。
      </div>

      <Donate />

      <details className="card" style={{ marginTop: 12, cursor: 'pointer' }}>
        <summary style={{ fontSize: 13, fontWeight: 600, color: 'var(--muted)' }}>
          隐私 · 开源 · 合规
        </summary>
        <div className="muted" style={{ marginTop: 10, fontSize: 12.5,
                                        lineHeight: 1.85 }}>
          <b>你的数据在哪</b><br />
          只上传你点「提交误报」的那一条文本。不上传完整对局记录、音频、
          API Key、设备信息、时间戳、用户身份。本地词库和历史全部存在你自己电脑上。
          <br /><br />

          <b>翻译不准怎么办</b><br />
          在「实时翻译」页点某条消息上的<b>误报</b>，填上正确的说法 ——
          你这台机器立即生效。同一条被 3 个以上不同玩家报成同一句，
          才会进社区词库（<a href="https://github.com/cingzz/valtrans-lexicon"
          target="_blank" rel="noreferrer" style={{ color: 'var(--accent)' }}>
            valtrans-lexicon</a>）；说法有分歧时系统不会自动采纳任何一方。
          <br /><br />

          <b>开源授权</b><br />
          代码 GPL-3.0 + 商业授权：改代码可以，分发时必须公开源码；
          想闭源使用或拿去卖，需向作者申请商业授权。
          词库是单独的 CC0（公有领域），任何人可自由取用 ——
          约束力加在代码上，不加在数据上。
          <br /><br />

          <b>合规边界</b><br />
          与 Riot Games 官方无关。仅读取系统音频（WASAPI），不注入、不 hook、
          不读内存、不静默装驱动（虚拟声卡为 VB-Audio 官方包，由用户确认后安装）。
          使用第三方软件存在理论封号风险，请自行评估。
        </div>
      </details>

      {showFeedback && <FeedbackDialog onClose={() => setShowFeedback(false)} />}
    </div>
  )
}
