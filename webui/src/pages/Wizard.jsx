import React, { useEffect, useState } from 'react'
import { bus, call } from '../api.js'

export default function Wizard({ cfg, patchCfg, onDone }) {
  const [step, setStep] = useState(0)
  const [agree, setAgree] = useState(cfg.disclaimer_accepted)
  const [audio, setAudio] = useState({ state: '正在检测虚拟声卡…', cable: null })
  const [skipAudio, setSkipAudio] = useState(false)
  const [key, setKey] = useState(cfg.asr_keys[cfg.asr_preset] || '')
  const [keyState, setKeyState] = useState('')
  const [testing, setTesting] = useState(false)

  useEffect(() => {
    if (step === 1) call('detect_audio').then(setAudio).catch(() => {})
  }, [step])

  useEffect(() => {
    const off = bus.on('keytest', r => { setKeyState(r.text); setTesting(false) })
    return off
  }, [])

  const installDriver = async () => {
    // v0.2.10：install_driver 以前是静默的（找不到 exe 或 ShellExecute
    // 失败都 return/pass），用户点了没反应也不知道哪里错了。
    // 现在它返回 {ok, msg}，这里如实显示 —— 失败必须看得见。
    let r
    try {
      r = await call('install_driver')
    } catch (e) {
      r = { ok: false, msg: `调用失败：${e && e.message ? e.message : e}` }
    }
    if (r && r.ok) {
      setAudio(a => ({ ...a, state: r.msg }))
      setTimeout(() => setAudio(a => ({ ...a, redetect: true })), 500)
    } else {
      setAudio(a => ({ ...a, state: (r && r.msg) || '安装器未能启动，请手动以管理员身份运行 assets/drivers/VBCABLE_Setup_x64.exe' }))
    }
  }

  const redetect = async () => setAudio(await call('detect_audio'))

  // ★ v0.2.19：免驱动 Loopback 提到推荐位（LiveCaptions 教训：零配置路径
  //   前置 = 新用户流失的关键）。有虚拟声卡时推荐位互换（识别更准）。
  const useLoopback = async () => {
    setSkipAudio(true)
    await patchCfg({ capture_mode: 'loopback' })
    setStep(2)
  }
  const useCable = async () => {
    setSkipAudio(false)
    await patchCfg({ capture_mode: 'cable' })
    setStep(2)
  }

  const next = async () => {
    if (step === 0) { if (!agree) return; await patchCfg({ disclaimer_accepted: true }) }
    if (step === 1) await patchCfg({ capture_mode: skipAudio ? 'loopback' : 'cable' })
    if (step === 2) {
      if (key.trim()) await patchCfg({ asr_key: key.trim(), mt_key: key.trim() })
    }
    if (step === 3) {
      await patchCfg({ first_run_done: true })
      onDone()
      return
    }
    setStep(s => s + 1)
  }

  const canNext = step !== 0 || agree

  return (
    <div className="modal-mask">
      <div className="modal">
        <div className="row" style={{ marginBottom: 18 }}>
          <h1 className="h1" style={{ fontSize: 18 }}>
            {['欢迎使用 ValTrans', '音频一键配置', '云端服务配置', '最后一步'][step]}
          </h1>
          <span className="grow" />
          <div className="step-dots">{[0, 1, 2, 3].map(i => <i key={i} className={i === step ? 'on' : ''} />)}</div>
        </div>

        {step === 0 && (
          <div>
            <p style={{ lineHeight: 1.8 }}>把队友的外语语音实时变成中文字幕，并把你说的话翻译成外语发给队友。<br />开始前请阅读并同意以下声明：</p>
            <div className="card" style={{ background: '#FBFAF8', boxShadow: 'none', border: '1px solid var(--stroke)', margin: '12px 0', padding: 14 }}>
              <div className="muted" style={{ lineHeight: 1.9 }}>
                1. 本软件与 Riot Games /《无畏契约》官方无关；<br />
                2. 仅读取系统音频，不注入游戏、不读内存；<br />
                3. 使用第三方软件存在理论封号风险，请自行评估承担；<br />
                4. 云端识别/翻译使用你自己注册的 API 服务，费用与额度以服务商为准。
              </div>
            </div>
            <label className="row" style={{ gap: 8 }}>
              <input type="checkbox" checked={agree} onChange={e => setAgree(e.target.checked)} />
              我已阅读并同意上述声明
            </label>
          </div>
        )}

        {step === 1 && (
          <div>
            <p style={{ lineHeight: 1.8 }}>{audio.state}</p>
            {audio.cable === true ? (
              <>
                <div className="card" style={{ background: '#FBFAF8', boxShadow: 'none', border: '1px solid var(--stroke)', margin: '12px 0', padding: 14, lineHeight: 1.9 }}>
                  ✅ 检测到虚拟声卡已就绪 —— 推荐<b>虚拟声卡模式</b>：只采队友语音、不混游戏音效，识别最准。
                  <div style={{ marginTop: 8 }}>
                    <button className="btn primary" onClick={useCable}>用虚拟声卡模式继续（推荐）</button>
                  </div>
                </div>
                <div className="card muted" style={{ background: '#FBFAF8', boxShadow: 'none', border: '1px solid var(--stroke)', margin: '12px 0', padding: 14, lineHeight: 1.9 }}>
                  免驱动 Loopback 模式：不装驱动也能用，但会混入电脑全部声音，准确率下降。
                  <div style={{ marginTop: 8 }}>
                    <button className="btn" onClick={useLoopback}>改用免驱动模式</button>
                  </div>
                </div>
              </>
            ) : (
              <>
                <div className="card" style={{ background: '#FBFAF8', boxShadow: 'none', border: '1px solid var(--stroke)', margin: '12px 0', padding: 14, lineHeight: 1.9 }}>
                  <b>免驱动模式（推荐 · 30 秒上手）</b><br />
                  不用安装任何驱动：游戏内 设置→音频→「输出设备」保持你的耳机/扬声器即可。<br />
                  代价：会混入电脑全部声音，识别准确率略降。
                  <div style={{ marginTop: 8 }}>
                    <button className="btn primary" onClick={useLoopback}>免驱动模式（推荐）— 继续</button>
                  </div>
                </div>
                <div className="card muted" style={{ background: '#FBFAF8', boxShadow: 'none', border: '1px solid var(--stroke)', margin: '12px 0', padding: 14, lineHeight: 1.9 }}>
                  <b>进阶：虚拟声卡模式（识别更准）</b> —— 只采队友语音，需要装官方免费驱动（点安装会弹 UAC，<b>绝不静默安装</b>）。
                  <div style={{ marginTop: 8 }}>
                    {audio.cable === false && (
                      <button className="btn" onClick={installDriver}>🔧 一键安装虚拟声卡（官方 VB-CABLE）</button>
                    )}
                    {audio.redetect && <button className="btn" style={{ marginLeft: 8 }} onClick={redetect}>🔄 重新检测</button>}
                  </div>
                  <div style={{ marginTop: 8 }}>
                    装好后游戏内 设置→音频→「语音聊天输出设备」选 <b>CABLE Input</b>；<br />
                    其余全自动（软件级监听回耳机，无回声）。装好后点下面按钮继续。
                  </div>
                  <div style={{ marginTop: 8 }}>
                    <button className="btn" onClick={useCable}>装好了，用虚拟声卡模式继续</button>
                  </div>
                </div>
              </>
            )}
          </div>
        )}

        {step === 2 && (
          <div>
            <p style={{ lineHeight: 1.8 }}>
              与同类软件不同：本软件不收费、无账号——识别和翻译直接调用<b>你自己注册的免费云端模型</b>，
              只需一次性配置 Key（之后永久有效）。
            </p>
            <div className="card muted" style={{ background: '#FBFAF8', boxShadow: 'none', border: '1px solid var(--stroke)', margin: '12px 0', padding: 14, lineHeight: 1.9 }}>
              · 语音识别：Qwen3-ASR（阿里开源）——中/日/韩/英/粤，实测比旧默认快 10 倍且更准<br />
              · 翻译：Qwen2.5-14B —— 游戏社区黑话最准，说人话不说书面语<br />
              · 免费额度个人游戏完全够用；葡语等可切 Groq 预设；云端失败自动降级不崩
            </div>
            <div className="row" style={{ marginBottom: 10 }}>
              <button className="btn" onClick={() => call('open_url', 'https://cloud.siliconflow.cn/account/register')}>① 打开注册页面</button>
              <button className="btn" onClick={() => call('open_url', 'https://cloud.siliconflow.cn/account/ak')}>② 打开密钥页面</button>
            </div>
            <div className="row">
              <input className="grow" type="text" placeholder="粘贴 sk- 开头的密钥（识别+翻译共用）"
                     value={key} onChange={e => setKey(e.target.value)} />
              <button className="btn primary" disabled={testing || !key.startsWith('sk-')}
                      onClick={async () => { setTesting(true); setKeyState('测试中…'); await call('test_key', key.trim()) }}>
                {testing ? '测试中…' : '测试'}
              </button>
            </div>
            <div className="muted" style={{ marginTop: 8 }}>{keyState}</div>
          </div>
        )}

        {step === 3 && (
          <div>
            <p style={{ lineHeight: 2 }}>
              游戏内把显示模式改为<b>「无边框窗口」</b>（设置→视频→显示模式），否则浮窗会被游戏盖住。<br /><br />
              点击完成后，回到主页按「开始翻译」即可。祝把把超神！
            </p>
          </div>
        )}

        <div className="row" style={{ marginTop: 22 }}>
          {step > 0 && <button className="btn" onClick={() => setStep(s => s - 1)}>上一步</button>}
          <span className="grow" />
          <button className="btn primary" disabled={!canNext} onClick={next}>
            {step === 3 ? '完成' : '下一步'}
          </button>
        </div>
      </div>
    </div>
  )
}
