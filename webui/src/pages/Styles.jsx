import React, { useEffect, useRef, useState } from 'react'
import { call } from '../api.js'

export default function Styles({ cfg, patchCfg }) {
  const [fontSize, setFontSize] = useState(cfg.overlay_font_size)
  // v0.2.11：高度跟随真实配置（此前无高度调节）
  const [height, setHeight] = useState(cfg.overlay_height || 380)
  const [opacity, setOpacity] = useState(Math.round(cfg.overlay_opacity * 100))
  const [width, setWidth] = useState(cfg.overlay_width)
  const timer = useRef(null)

  // 配置在别处被改（比如浮窗自己保存了尺寸）时同步回来，
  // 否则滑杆会一直显示旧值，和真实窗口不一致 —— 这和用户报的
  // 「状态与实际不符」是同一类问题。
  useEffect(() => {
    setHeight(cfg.overlay_height || 380)
    setWidth(cfg.overlay_width)
    setFontSize(cfg.overlay_font_size)
  }, [cfg.overlay_height, cfg.overlay_width, cfg.overlay_font_size])

  // 显式传值而不是依赖闭包：数字输入时 state 更新有延迟，
  // 依赖闭包可能把上一次的值又写回去，导致输入框"回弹"。
  const push = (w = width) => {
    clearTimeout(timer.current)
    timer.current = setTimeout(() => {
      patchCfg({ overlay_font_size: fontSize, overlay_opacity: opacity / 100, overlay_width: w })
    }, 300)
  }

  return (
    <div>
      <div className="row" style={{ marginBottom: 16 }}>
        <h1 className="h1">字幕样式</h1>
        <span className="grow" />
        <span className="muted">字幕显示</span>
        <button className={'toggle' + (cfg.overlay_enabled ? ' on' : '')}
                title={cfg.overlay_enabled
                  ? '字幕已开启，点击关闭' : '字幕已关闭，点击打开'}
                onClick={async () => {
                  const want = !cfg.overlay_enabled
                  try { await patchCfg({ overlay_enabled: want }) } catch (e) { /* 已提示 */ }
                }} />
        {/* v0.2.11：改三态。
            原来只有 开/关 两态，UI 拿 `overlay_enabled`（含义是「**允许**显示」）
            当成「正在显示」来渲染。但浮窗是**懒创建**的（队友不说话就不建窗），
            于是出现「配置是开的、屏幕上没窗、状态框却是绿的『已显示』」。

            真机 原话：「打开软件时字幕没有显示，它那边的状态框却
            打到了绿色，显示为『已显示』。我需要重新把它关了再开，字幕才会出来。」

            现在以 Python 侧报的 `overlay_visible`（实际可见性）为准：
              关闭     -> 灰「已关闭」
              允许但还没建窗 -> 橙「已开启 · 等待说话」（这是正常状态，不是 bug）
              真的在屏幕上   -> 绿「显示中」
            懒创建是刻意设计，不能为了迎合状态灯而改成常驻窗口。*/}
        <span className={'pill ' + (
          !cfg.overlay_enabled ? 'gray'
            : cfg.overlay_visible === true ? 'green'
              : 'orange')}>
          {!cfg.overlay_enabled ? '已关闭'
            : cfg.overlay_visible === true ? '显示中'
              : '已开启 · 等待说话'}
        </span>
      </div>

      <div className="card" style={{ marginBottom: 16 }}>
        <div className="form-row">
          <label style={{ width: 96 }}>字号 {fontSize}</label>
          <input type="range" min="14" max="30" value={fontSize}
                 onChange={e => { setFontSize(+e.target.value); push() }} />
        </div>
        <div className="form-row">
          <label style={{ width: 96 }}>透明度 {opacity}%</label>
          <input type="range" min="30" max="100" value={opacity}
                 onChange={e => { setOpacity(+e.target.value); push() }} />
        </div>
        <div className="form-row" style={{ marginBottom: 0 }}>
          <label style={{ width: 96 }}>宽度</label>
          <input type="range" min="260" max="900" step="10" value={width}
                 onChange={e => { const v = +e.target.value; setWidth(v); push(v) }} />
          <input type="number" className="w-num" min="260" max="900" step="10"
                 value={width}
                 onChange={e => {
                   const v = Math.max(260, Math.min(900, +e.target.value || 260))
                   setWidth(v); push(v)
                 }} />
          <span className="muted" style={{ flexShrink: 0 }}>像素</span>
        </div>
        {/* v0.2.11：字幕高度（此前只有宽度可调，高度硬编码 380）。
            需求「字幕只有左右宽度，没有上下高度，无法进行上下调节」。
            范围 240~520：太矮放不下「译文 + 原文」两行，太高会挡住游戏画面。*/}
        <div className="form-row">
          <label style={{ width: 96 }}>高度</label>
          <input type="range" min="240" max="520" step="10" value={height}
                 onChange={e => {
                   const v = +e.target.value
                   setHeight(v)
                   patchCfg({ overlay_height: v })
                 }} />
          <input type="number" className="w-num" min="240" max="520" step="10"
                 value={height}
                 onChange={e => {
                   const v = Math.max(240, Math.min(520, +e.target.value || 380))
                   setHeight(v); patchCfg({ overlay_height: v })
                 }} />
          <span className="muted" style={{ flexShrink: 0 }}>像素</span>
        </div>
        <div className="muted" style={{ marginTop: 2 }}>
          宽度可拖滑杆，也可直接输入数字。窄一点在游戏里更不挡视线（建议 300~420）。
          高度默认 380；要放下更多历史行可以调高，但会占更多屏幕。
        </div>
        <div className="muted" style={{ marginTop: 10 }}>
          调整即时生效；透明度 = 游戏内字幕面板的整体透明程度。
        </div>
      </div>

      {/* 实时预览：与游戏内浮窗同一套样式与结构（上=队友 / 分隔线 / 下=我） */}
      <div className="card">
        <h2 className="h2" style={{ marginBottom: 12 }}>实时预览（与游戏内浮窗一致）</h2>
        <div style={{ background: 'repeating-conic-gradient(#efece6 0 25%, #f8f6f2 0 50%) 50%/24px 24px',
                      borderRadius: 12, padding: '18px 14px', display: 'flex', justifyContent: 'center' }}>
          <div style={{ width: Math.min(width, 620), height: 380,
                        background: 'rgba(104,108,114,0.66)', borderRadius: 10,
                        padding: '10px 16px 6px', boxShadow: '0 6px 22px rgba(0,0,0,0.14)',
                        display: 'flex', flexDirection: 'column', gap: 8 }}>
            {/* 上卡：队友 */}
            <div style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column', gap: 6 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12, color: 'rgba(255,255,255,0.75)' }}>
                <span className="pill" style={{ padding: '2px 10px', background: 'rgba(155,231,255,0.22)', color: '#9BE7FF' }}>队友</span>
                <span style={{ flex: 1 }} />
                <span style={{ color: 'rgba(255,255,255,0.62)', fontSize: 11 }}>
                  {cfg.overlay_locked ? '已锁定' : `未锁定 · ${cfg.hotkey_lock || 'Ctrl + Alt + Q'} 锁定`}
                </span>
              </div>
              <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', justifyContent: 'center' }}>
                <div style={{ fontSize, fontWeight: 700, color: '#FBFCFD', lineHeight: 1.3, textShadow: '0 1px 3px rgba(0,0,0,0.35)' }}>
                  敌人在转点 B，小心！
                </div>
                {cfg.show_original !== false && (
                  <div style={{ color: 'rgba(251,252,253,0.75)', fontSize: 12, marginTop: 2 }}>
                    Enemy rotating to B, careful!
                  </div>
                )}
              </div>
            </div>
            <div style={{ height: 1, background: 'rgba(255,255,255,0.22)', flexShrink: 0 }} />
            {/* 下卡：我 */}
            <div style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column', gap: 6 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12, color: 'rgba(255,255,255,0.75)' }}>
                <span className="pill" style={{ padding: '2px 10px', background: 'rgba(155,231,255,0.9)', color: '#0B2740' }}>我</span>
              </div>
              <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', justifyContent: 'center' }}>
                <div style={{ fontSize: fontSize - 2, fontWeight: 700, color: '#FBFCFD', lineHeight: 1.3, textShadow: '0 1px 3px rgba(0,0,0,0.35)' }}>
                  集合打大龙，别分散。
                </div>
                <div style={{ color: '#9BE7FF', fontSize: 12, marginTop: 2 }}>
                  Group up for the Baron, don't split.
                </div>
              </div>
            </div>
            <div style={{ alignSelf: 'flex-end', color: 'rgba(255,255,255,0.5)', fontSize: 10.5, letterSpacing: 1, flexShrink: 0 }}>
              · ValTrans ·
            </div>
          </div>
        </div>
        <div className="muted" style={{ marginTop: 10 }}>
          游戏内把显示模式改为「无边框窗口」才能看到浮窗；浮窗未锁定时可拖动位置，锁定后鼠标穿透。
        </div>
      </div>
    </div>
  )
}
