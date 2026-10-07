import React, { useEffect, useState } from 'react'
import { bus, call } from '../api.js'
import HotkeyInput, { prettyHotkey } from '../HotkeyInput.jsx'

export default function Settings({ cfg, patchCfg }) {
  const [f, setF] = useState({
    capture_mode: cfg.capture_mode, cable_output_device: cfg.cable_output_device,
    mic_device: cfg.mic_device, vad_mode: cfg.vad_mode,
    rms_threshold: Math.round(cfg.rms_threshold * 1000),
    asr_preset: cfg.asr_preset, asr_key: cfg.asr_keys[cfg.asr_preset] || '',
    mt_preset: cfg.mt_preset, mt_key: cfg.mt_keys[cfg.mt_preset] || '',
    tts_voice: cfg.tts_voice, tts_rate: cfg.tts_rate, tts_pitch: cfg.tts_pitch,
    hotkey_lock: cfg.hotkey_lock, hotkey_review: cfg.hotkey_review,
    hotkey_ptt: cfg.hotkey_ptt, hotkey_move: cfg.hotkey_move || '<ctrl>+<shift>+d',
    auto_copy: cfg.auto_copy, asr_mode: cfg.asr_mode,
  })
  const [devices, setDevices] = useState({ capture: [], mics: [] })
  const [presets, setPresets] = useState({ asr: {}, mt: {} })
  const [voices, setVoices] = useState([])
  const [asrHint, setAsrHint] = useState('提示：SenseVoice 支持中/英/日/韩/粤；葡语等请切换 Groq/OpenAI 预设。')
  const [mtHint, setMtHint] = useState('')
  const [micHint, setMicHint] = useState('回声测试：开启后对着麦克风说话，耳机里会立刻听到自己（30 秒自动停止）。')
  const [selftest, setSelftest] = useState('')
  const [saved, setSaved] = useState(false)
  const [echoOn, setEchoOn] = useState(false)
  // v0.2.6：用量统计 / 自学习候选 / 版本信息
  const [usage, setUsage] = useState(null)
  // v0.2.11：旧学习模块（学云端自己的输出）已停用，改为新自学习统计。
  // 保留 legacy 计数只为如实展示历史量，见 selflearn_stats() 的说明。
  const [sl, setSl] = useState({ by_kind: {}, legacy_candidates: {}, threshold: 3 })
  useEffect(() => {
    call('selflearn_stats').then(setSl).catch(() => {})
  }, [])
  const [upd, setUpd] = useState(null)
  // v0.2.9：音色目录（已精简到 8 个，每个自带性格，不再需要人设层）
  const [vc, setVc] = useState({ languages: {}, total: 0 })
  const [playingVoice, setPlayingVoice] = useState('')

  useEffect(() => {
    call('get_devices').then(setDevices).catch(() => {})
    call('get_presets').then(setPresets).catch(() => {})
    call('get_voices').then(setVoices).catch(() => {})
    const off = bus.on('test_result', d => {
      if (d.kind === 'asr') setAsrHint(d.text)
      if (d.kind === 'mt') setMtHint(d.text)      // 翻译结果单列，不再混进识别提示框
      if (d.kind === 'mic') {
        setMicHint(d.text)
        if (d.state) setEchoOn(d.state === 'running')
      }
      if (d.kind === 'selftest') setSelftest(d.text)
    })
    return () => { off(); call('mic_test_stop').catch(() => {}) }   // 离开页面必须释放麦克风
  }, [])

  const set = (k, v) => setF(o => ({ ...o, [k]: v }))

  const save = async () => {
    await patchCfg({
      capture_mode: f.capture_mode, cable_output_device: f.cable_output_device,
      mic_device: f.mic_device, vad_mode: f.vad_mode,
      rms_threshold: f.rms_threshold / 1000,
      asr_preset: f.asr_preset, asr_key: f.asr_key,
      mt_preset: f.mt_preset, mt_key: f.mt_key,
      tts_voice: f.tts_voice, tts_rate: +f.tts_rate, tts_pitch: +f.tts_pitch,
      hotkey_lock: f.hotkey_lock, hotkey_review: f.hotkey_review,
      hotkey_ptt: f.hotkey_ptt, hotkey_move: f.hotkey_move,
      auto_copy: f.auto_copy, asr_mode: f.asr_mode,
    })
    setSaved(true); setTimeout(() => setSaved(false), 2500)
  }

  return (
    <div>
      {/* 内联样式：放在组件内，外部裸 <style> 在 jsx 里非法 */}
      <style>{`

      /* ---- v0.2.7 音色人设卡 ---- */

      /* ---- v0.2.9 音色说明（替代人设卡）---- */
      .voice-hint {
        margin-top: 8px; font-size: 12px; color: #8A7F74;
        display: flex; align-items: center; gap: 10px; flex-wrap: wrap;
      }
      .voice-hint .cnt {
        background: var(--brand-050); color: var(--brand-800);
        padding: 1px 8px; border-radius: var(--r-full); font-weight: 600;
      }

      /* ---- v0.2.6 设置页新增卡片 ---- */
      .cardhead {
        display: flex; align-items: center; justify-content: space-between;
        margin-bottom: 10px; font-weight: 700; font-size: 14px;
      }
      .usagebar {
        height: 10px; border-radius: 5px; overflow: hidden;
        background: rgba(255, 138, 0, 0.18); margin-bottom: 10px;
      }
      .usagebar-local {
        height: 100%; background: linear-gradient(90deg, #34C77B, #1F9D55);
        transition: width .3s;
      }
      .usagestats {
        display: flex; flex-wrap: wrap; gap: 14px 22px;
        font-size: 12.5px; color: #5B6472;
      }
      .usagestats b { font-size: 15px; color: #1E2430; }
      .usagestats span { margin-left: 3px; }
      .hintline {
        margin-top: 10px; font-size: 12px; color: #8A94A6; line-height: 1.7;
      }
      .linkbtn {
        border: none; background: none; color: #2F7DE1; cursor: pointer;
        font-size: 12px; padding: 0 0 0 8px; text-decoration: underline;
      }
      .tag {
        font-size: 11px; color: #8A94A6; background: #EEF1F5;
        padding: 2px 7px; border-radius: 20px;
      }
      .tag.ok { background: rgba(31, 157, 85, 0.12); color: #1F9D55; }
      .featlist { margin-top: 10px; font-size: 12px; color: #6B7280; line-height: 1.85; }

      `}</style>
      {/* ---------- v0.2.6：翻译用量（本地 vs 云端） ---------- */}
      {usage && (
        <div className="card" style={{ marginBottom: 14 }}>
          <div className="cardhead">
            <span>翻译用量</span>
            <span style={{ fontSize: 12, color: '#8A94A6' }}>
              本地命中 0 token，云端才计费
            </span>
          </div>
          <div className="usagebar">
            <div className="usagebar-local"
                 style={{ width: `${Math.round(usage.local_ratio * 100)}%` }} />
          </div>
          <div className="usagestats">
            <div>
              <b style={{ color: '#1F9D55' }}>
                {Math.round((usage.local_ratio || 0) * 100)}%
              </b>
              <span> 本地翻译占比</span>
            </div>
            <div>
              <b>{(usage.local_hits || 0).toLocaleString()}</b>
              <span> 本地命中（0 成本）</span>
            </div>
            <div>
              <b>{(usage.cloud_hits || 0).toLocaleString()}</b>
              <span> 云端模型（{usage.cloud_tokens_in || 0} 入 / {usage.cloud_tokens_out || 0} 出 tok）</span>
            </div>
            <div>
              <b style={{ color: usage.est_cost_cny > 0 ? '#C2410C' : '#1F9D55' }}>
                ¥{(usage.est_cost_cny || 0).toFixed(5)}
              </b>
              <span> 预估云端花费</span>
            </div>
          </div>
          <div className="hintline">
            本地占比越高越省钱。把反复出现的云端句子采纳进词库，占比就会上去。
            <button className="linkbtn" onClick={() =>
              call('reset_usage_stats').then(() =>
                call('get_usage_stats').then(setUsage))}>清零统计</button>
          </div>
        </div>
      )}

      {/* ---------- v0.2.11 自学习（替换 v0.2.7 旧机制）---------- */}
      <div className="card" style={{ marginBottom: 14 }}>
        <div className="cardhead">
          <span>自学习词库</span>
          <span style={{ fontSize: 12, color: '#8A94A6' }}>
            学会的是**你确认过的**说法，不是云端自己的输出
          </span>
        </div>

        <div className="usagestats">
          <div><b>{sl.total_entries || 0}</b><span> 记忆库总条数</span></div>
          <div><b>{sl.user_taught || 0}</b><span> 你教的</span></div>
          <div><b>{sl.public || 0}</b><span> 社区词库</span></div>
          <div><b>{sl.seed || 0}</b><span> 内置已核实</span></div>
        </div>

        <div className="usagestats" style={{ marginTop: 8 }}>
          <div><b>{sl.reports || 0}</b><span> 提交过的误报</span></div>
          <div><b>{sl.local_only || 0}</b><span> 仅本机生效</span></div>
          <div><b>{sl.consensus || 0}</b><span> 已达共识</span></div>
          <div><b>{sl.conflict || 0}</b><span> 有分歧待人工审</span></div>
        </div>

        <div className="hintline">
          提交误报在<b>「关于」页</b>（手动填，或从实时翻译页的历史记录里点「误报」）。
          <br />
          同一条被 <b>{sl.threshold || 3} 个以上不同玩家</b>报成同一句，才会进公共词库；
          说法有分歧时<b>不会自动采纳任何一方</b> —— 游戏黑话有地域差异，
          硬投票会把少数但正确的说法覆盖掉。
        </div>

        {!!sl.legacy_candidates?.ready && (
          <div className="hintline" style={{ marginTop: 8, color: '#B45309' }}>
            注意：旧版自学习（学习云端自己的输出）还攒了
            {' '}{sl.legacy_candidates.ready} 条待确认。这些可能包含云端的错译，
            已不再自动入库；确认无误可在下方手动处理。
          </div>
        )}
      </div>

      {/* ---------- v0.2.6：更新      {/* ---------- v0.2.6：更新 / 能力清单 ---------- */}
      {upd && (
        <div className="card" style={{ marginBottom: 14 }}>
          <div className="cardhead">
            <span>版本与词库规模</span>
            <span style={{ fontSize: 12, color: '#8A94A6' }}>v{upd.version}</span>
          </div>
          <div className="usagestats">
            <div><b>{(upd.lexicon_total || 0).toLocaleString()}</b><span> 词条总数</span></div>
            <div><b>{upd.agents}</b><span> 英雄</span></div>
            <div><b>{upd.weapons}</b><span> 武器</span></div>
            <div><b>{upd.ja}</b><span> 日语黑话</span></div>
            <div><b>{upd.ko + (upd.ko_roma || 0)}</b><span> 韩语黑话（含罗马音）</span></div>
            <div><b>{upd.user_lexicon}</b><span> 我教会的</span></div>
          </div>
          <div className="featlist">
            {(upd.features || []).map((f, i) => (
              <div className="feat" key={i}>· {f}</div>
            ))}
          </div>
        </div>
      )}

      <div className="row" style={{ marginBottom: 16 }}>
        <h1 className="h1">设置</h1>
        <span className="grow" />
        {saved && <span className="pill green">已保存 ✓</span>}
        <button className="btn primary" onClick={save}>保存全部设置</button>
      </div>

      <div className="card" style={{ marginBottom: 16 }}>
        <h2 className="h2" style={{ marginBottom: 14 }}>音频</h2>
        <div className="form-row">
          <label>采集模式</label>
          <select className="grow" value={f.capture_mode} onChange={e => set('capture_mode', e.target.value)}>
            <option value="cable">虚拟声卡线路（推荐 · 只采队友人声）</option>
            <option value="loopback">整机输出 Loopback（免驱动 · 含电脑全部声音）</option>
          </select>
        </div>
        <div className="form-row">
          <label>采集源设备</label>
          <select className="grow" value={f.cable_output_device}
                  onChange={e => set('cable_output_device', e.target.value)}>
            {devices.capture.map(d => <option key={d} value={d}>{d}</option>)}
          </select>
        </div>
        <div className="form-row">
          <label>我的麦克风</label>
          <select className="grow" value={f.mic_device} onChange={e => set('mic_device', e.target.value)}>
            <option value="">系统默认</option>
            {devices.mics.map(d => <option key={d} value={d}>{d}</option>)}
          </select>
          <button className={'btn' + (echoOn ? ' danger' : '')} style={{ flexShrink: 0 }}
                  onClick={async () => {
                    const r = await call(echoOn ? 'mic_test_stop' : 'mic_test_start')
                    setEchoOn(!!(r && r.running))
                  }}>{echoOn ? '■ 停止回声' : '🎙 回声测试'}</button>
        </div>
        <div className="form-row">
          <label>断句方式</label>
          <select className="grow" value={f.vad_mode} onChange={e => set('vad_mode', e.target.value)}>
            <option value="silero">Silero 智能断句（推荐）</option>
            <option value="rms">纯音量阈值（零模型）</option>
          </select>
        </div>
        <div className="form-row">
          <label>音量阈值</label>
          <input type="range" min="1" max="100" value={f.rms_threshold}
                 onChange={e => set('rms_threshold', +e.target.value)} />
        </div>
        <div className="muted">{micHint}</div>
      </div>

      <div className="card" style={{ marginBottom: 16 }}>
        <h2 className="h2" style={{ marginBottom: 14 }}>云服务（BYOK：填入你自己注册的 API Key）</h2>
        <div className="form-row">
          <label>语音识别</label>
          <select style={{ maxWidth: 300 }} value={f.asr_preset}
                  onChange={e => set('asr_preset', e.target.value)}>
            {Object.entries(presets.asr).map(([k, p]) => (
        <option key={k} value={k}>
          {typeof p === 'string' ? p
            : `${p.label}${p.price ? '  ·  ' + p.price : ''}`}
        </option>
      ))}
          </select>
          <input className="grow" type="text" placeholder="粘贴 API Key" value={f.asr_key}
                 onChange={e => set('asr_key', e.target.value)} />
          <button className="btn" style={{ flexShrink: 0 }} onClick={() => call('test_asr', f.asr_key)}>测试</button>
        </div>
        <div className="form-row">
          <label>翻译</label>
          <select style={{ maxWidth: 300 }} value={f.mt_preset} onChange={e => set('mt_preset', e.target.value)}>
            {Object.entries(presets.mt).map(([k, p]) => (
        <option key={k} value={k}>
          {typeof p === 'string' ? p
            : `${p.label}${p.price ? '  ·  ' + p.price : ''}`}
        </option>
      ))}
          </select>
          <input className="grow" type="text" placeholder="粘贴 API Key" value={f.mt_key}
                 onChange={e => set('mt_key', e.target.value)} />
          <button className="btn" style={{ flexShrink: 0 }} onClick={() => call('test_mt', f.mt_key)}>测试</button>
        </div>
        <div className="muted">{asrHint}</div>
        {mtHint && <div className="muted">{mtHint}</div>}
      </div>

      <div className="card" style={{ marginBottom: 16 }}>
        <h2 className="h2" style={{ marginBottom: 14 }}>译文朗读音色（本地播放，队友听不到）</h2>
        <div className="form-row">
          <label>音色</label>
          <select className="grow" value={f.tts_voice} onChange={e => set('tts_voice', e.target.value)}>
            <option value="">自动（按语言选多语人声）</option>
            {voices.map(([name, label]) => <option key={name} value={name}>{label}</option>)}
          </select>
          <button className="btn" style={{ flexShrink: 0 }} onClick={() => call('preview_tts')}>🔊 试听</button>
        </div>
        <div className="form-row">
          <label>语速 {f.tts_rate > 0 ? '+' : ''}{f.tts_rate}%</label>
          <input type="range" min="-50" max="50" value={f.tts_rate}
                 onChange={e => set('tts_rate', +e.target.value)} />
        </div>
        <div className="form-row">
          <label>音调 {f.tts_pitch > 0 ? '+' : ''}{f.tts_pitch}Hz</label>
          <input type="range" min="-50" max="50" value={f.tts_pitch}
                 onChange={e => set('tts_pitch', +e.target.value)} />
        </div>
        <div className="muted">多语人声念外语更自然（服务端偶发不可用时自动换普通音色）；语速 +20% 更接近实战报点。</div>
      </div>

      <div className="card">
        <h2 className="h2" style={{ marginBottom: 14 }}>热键（点击后直接按组合键，不用手打）</h2>
        <HotkeyInput label="锁定穿透" value={f.hotkey_lock} hint="锁定后鼠标穿透浮窗，不挡游戏操作"
                      siblings={[{ label: '回看字幕', value: f.hotkey_review },
                                { label: '固定/拖动', value: f.hotkey_move },
                                { label: '按住说话', value: f.hotkey_ptt }]}
                      onChange={v => set('hotkey_lock', v)} />
        <HotkeyInput label="回看字幕" value={f.hotkey_review} hint="随时把字幕面板叫回屏幕"
                      siblings={[{ label: '锁定穿透', value: f.hotkey_lock },
                                { label: '固定/拖动', value: f.hotkey_move },
                                { label: '按住说话', value: f.hotkey_ptt }]}
                      onChange={v => set('hotkey_review', v)} />
        <HotkeyInput label="固定/拖动" value={f.hotkey_move} hint="游戏中一键切换：固定（穿透）↔ 可拖动"
                      siblings={[{ label: '锁定穿透', value: f.hotkey_lock },
                                { label: '回看字幕', value: f.hotkey_review },
                                { label: '按住说话', value: f.hotkey_ptt }]}
                      onChange={v => set('hotkey_move', v)} />
        <HotkeyInput label="按住说话" value={f.hotkey_ptt} allowSingle hint="可设单键（如 V）或组合键，按住不放说话，松开即翻译并复制"
                      siblings={[{ label: '锁定穿透', value: f.hotkey_lock },
                                { label: '回看字幕', value: f.hotkey_review },
                                { label: '固定/拖动', value: f.hotkey_move }]}
                      onChange={v => set('hotkey_ptt', v)} />

        <div className="form-row">
          <label style={{ width: 96 }}>字幕面板</label>
          <button className={'toggle' + (cfg.overlay_pinned ? '' : ' on')}
                  onClick={() => patchCfg({ overlay_pinned: !cfg.overlay_pinned })} />
          <span className="grow" />
          <span className="muted">
            {cfg.overlay_pinned
              ? '已固定：鼠标穿透，按热键可临时解锁拖动'
              : '可拖动：按住面板拖到任意位置，或用下方按钮归位'}
          </span>
        </div>
        <div className="row" style={{ flexWrap: 'wrap', marginTop: 4 }}>
          <button className="btn" onClick={() => call('move_overlay_to_corner', 'br')}>右下角</button>
          <button className="btn" onClick={() => call('move_overlay_to_corner', 'bl')}>左下角</button>
          <button className="btn" onClick={() => call('move_overlay_to_corner', 'tr')}>右上角</button>
          <button className="btn" onClick={() => call('move_overlay_to_corner', 'tl')}>左上角</button>
          <button className="btn" onClick={() => call('toggle_pin')}>
            {cfg.overlay_pinned ? '临时解锁拖动' : '立即固定'}
          </button>
          <button className="btn" onClick={() => call('review_overlay').catch(() => {})}>叫回面板</button>
        </div>
        <div className="muted" style={{ marginTop: 8 }}>
          游戏中无需回主界面：按 {f.hotkey_move ? prettyHotkey(f.hotkey_move) : '「固定/拖动」热键'}
          即可切换面板能否拖动，当前热键也会显示在面板右上角。
        </div>
      </div>

      <div className="card" style={{ marginTop: 16 }}>
        <h2 className="h2" style={{ marginBottom: 14 }}>翻译模式与自测</h2>
        <div className="form-row" style={{ marginBottom: 8 }}>
          <label style={{ width: 96 }}>翻译模式</label>
          <select style={{ maxWidth: 280 }} value={f.asr_mode} onChange={e => set('asr_mode', e.target.value)}>
            <option value="fast">快速模式</option>
            <option value="precision">精准模式（更高质量 · 稍慢）</option>
          </select>
          <label className="row" style={{ gap: 6, width: 'auto' }}>
            <input type="checkbox" checked={f.auto_copy}
                   onChange={e => set('auto_copy', e.target.checked)} /> PTT 译文自动复制
          </label>
        </div>
        <div className="row" style={{ flexWrap: 'wrap' }}>
          <button className="btn primary" onClick={() => { setSelftest('自测运行中…（3 句，约 15 秒，请勿重复点击）'); call('selftest') }}>
            ▶ 一键自测（3 句）
          </button>
          <span className="muted">逐句独立计时，单句失败不会影响其它句；免费 API 高峰期偶发超时属正常。</span>
        </div>
        {selftest && (
          <div style={{ marginTop: 10, whiteSpace: 'pre-wrap', fontSize: 12.5, lineHeight: 1.8,
                        background: '#FBFAF8', border: '1px solid var(--stroke)',
                        borderRadius: 10, padding: '12px 14px' }}>{selftest}</div>
        )}
      </div>    </div>
  )
}

