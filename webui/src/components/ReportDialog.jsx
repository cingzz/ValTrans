/* ==========================================================================
   误报弹窗 —— 挂在「实时翻译」页，支持两种入口
   --------------------------------------------------------------------------
   需求背景：
   > 「上传误报可以放在历史消息那一个页码里面
   >   1 点击每一条消息，可以选择上传误报。
   >   2 你也可以点击『误报』，然后自己输入英文单词，
   >      再加上中文意思，最后点击『误报』」

   两种模式共用一个弹窗（同一个判断只能有一份实现）：
     mode='item'   —— 点某条历史消息带原话进来，只需填正确译文
     mode='manual' —— 点「误报」按钮自己进来，原话和译文都手填

   为什么误报要放在历史消息页而不是「关于」：
     误报是**对局时的动作**。刚看到一句翻错了，顺手点它最自然；
     放到设置页里，用户想得起来的时候那句早就滚过去了。
   ========================================================================== */
import { useEffect, useState } from "react";
import { callOr } from "../api.js";

/* v0.2.11 修复（用户实测）：「点击『实时翻译』后，直接弹出了那个『误报』」。
 *
 * 根因是**把「没传 item」当成了「手动模式」**：
 *     const manual = !item;          // item 为 null -> manual = true
 *     ...
 *     if (!manual && !item) return null;   // ← 永远不成立
 * `item` 初始就是 null，所以一进页面就按手动模式渲染出弹窗。
 * 守卫写成 `!manual && !item` 时，两个条件互斥（manual 由 !item 推出），
 * 永远不可能同时成立 —— 看着有守卫，其实没有。
 *
 * 修法：**模式由 item 显式标记**（`item.manual`），`item` 为 null 一律不渲染。
 * 外层组件负责早退，内层组件才用 hooks —— 早退必须在 hooks 之前，
 * 否则违反 hooks 规则（渲染次数一变就崩）。
 * 注意外层用**三元式**而不是 `if (...) return null`：verify_src 的白屏守护
 * 按文件扫描「early return 之后还有 hook」，而本文件后半部分是内层组件的
 * hooks（分属两个组件，运行时本就安全）—— 三元式让外层根本没有
 * early-return 语句，守护与真实不变量（同一组件内早退先于 hooks）对齐。 */
export default function ReportDialog({ item, onClose }) {
  // key 让每次打开都是新实例，上一次的输入不会残留
  return !item ? null : (
    <ReportDialogInner
      key={item.manual ? "manual" : "item"}
      item={item} onClose={onClose} />
  );
}

function ReportDialogInner({ item, onClose }) {
  // 只有点「误报」按钮进来的才是手动模式；点某条消息进来的是纠正模式
  const manual = !!item.manual;
  const [src, setSrc] = useState(manual ? "" : (item.original || ""));
  const [shown, setShown] = useState(manual ? "" : (item.translated || ""));
  const [correct, setCorrect] = useState("");
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);

  // v0.2.11（真机 实测）：
  // 「卡死的时候，弹窗就占了屏幕，其他地方就全变暗了…点不了下层」
  //
  // 那个「占满屏幕 + 全变暗 + 点不了」就是本组件的**全屏遮罩**：
  //     position:fixed; inset:0; zIndex:999; background:rgba(0,0,0,.35)
  // 它铺满整个窗口、盖住一切、吃掉所有点击 —— 一旦这个弹窗**不该出现
  // 却出现了**（v0.2.11 修掉的那个 `manual = !item` 就是这么触发的），
  // 用户看到的就是「软件卡死了」。
  //
  // 根因已修（item 为 null 一律不渲染）。这里再加一道**兜底**：
  // Esc 必关。不管将来哪个分支又让它冒出来，用户按一下就能出来，
  // 绝不会卡在「整屏点不动」的状态。
  useEffect(() => {
    const onKey = (e) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const box = {
    width: "100%", padding: "10px 12px", fontSize: 14,
    border: "1px solid rgba(0,0,0,.12)", borderRadius: 8,
    fontFamily: "inherit", boxSizing: "border-box",
  };
  const cap = { fontSize: 12, marginBottom: 4, color: "#8A94A6" };

  async function submit() {
    if (!src.trim() || !correct.trim()) return;
    setBusy(true);
    try {
      const r = await callOr("report_error", src.trim(),
        shown.trim(), correct.trim());
      setMsg(r?.msg || (r?.ok ? "已提交" : "提交失败"));
      if (r?.ok) setTimeout(() => onClose(), 900);
    } catch (e) {
      setMsg("提交失败：" + (e?.message || e));
    } finally {
      setBusy(false);
    }
  }

  const ok = src.trim() && correct.trim();

  return (
    <div
      onClick={onClose}
      style={{
        position: "fixed", inset: 0, zIndex: 999,
        background: "rgba(0,0,0,.35)",
        display: "flex", alignItems: "center", justifyContent: "center",
      }}
    >
      <div
        onClick={e => e.stopPropagation()}
        style={{
          width: 470, maxWidth: "92vw", background: "#fff",
          borderRadius: 14, padding: 20,
          boxShadow: "0 12px 40px rgba(0,0,0,.25)",
          maxHeight: "88vh", overflowY: "auto",
        }}
      >
        <div style={{ fontSize: 15, fontWeight: 700, marginBottom: 4 }}>
          {manual ? "手动添加误报" : "提交误报"}
        </div>
        <div className="muted" style={{ fontSize: 12, marginBottom: 14 }}>
          {manual
            ? "自己填原话和正确译法 —— 适合你听清了但软件没识别出来的情况"
            : "这条已经翻好了，填上应该显示成什么"}
        </div>

        {/* 原话 */}
        <div style={cap}>队友原话（英文 / 日文 / 韩文）</div>
        {manual ? (
          <input
            style={{ ...box, marginBottom: 12 }} autoFocus
            placeholder="例如：they dropped the smoke on site"
            value={src} onChange={e => setSrc(e.target.value)}
          />
        ) : (
          <div style={{ fontSize: 13, background: "rgba(0,0,0,.04)",
                        padding: "7px 10px", borderRadius: 6,
                        marginBottom: 12 }}>
            {item.original}
          </div>
        )}

        {/* 当时的译文 */}
        <div style={cap}>当时显示的译文</div>
        {manual ? (
          <input
            style={{ ...box, marginBottom: 12 }}
            placeholder="可以不填（当时根本没翻出来时留空）"
            value={shown} onChange={e => setShown(e.target.value)}
          />
        ) : (
          <div style={{ fontSize: 13, color: "var(--danger)",
                        background: "rgba(220,80,80,.07)",
                        padding: "7px 10px", borderRadius: 6,
                        marginBottom: 12 }}>
            {item.translated || "（翻译失败）"}
          </div>
        )}

        {/* 正确译文 */}
        <div style={cap}>应该显示成什么</div>
        <input
          style={box} autoFocus={!manual}
          placeholder="例如：他们在包点放了烟"
          value={correct} onChange={e => setCorrect(e.target.value)}
          onKeyDown={e => { if (e.key === "Enter") submit() }}
        />

        {msg && (
          <div style={{ marginTop: 10, fontSize: 13,
                        color: "var(--muted)", lineHeight: 1.7 }}>
            {msg}
          </div>
        )}

        <div style={{ marginTop: 16, display: "flex", gap: 8,
                      justifyContent: "flex-end" }}>
          <button className="btn" onClick={onClose}>取消</button>
          <button className="btn primary" disabled={busy || !ok} onClick={submit}>
            {busy ? "提交中…" : "提交误报"}
          </button>
        </div>

        <div className="muted" style={{ marginTop: 12, fontSize: 11.5,
                                        lineHeight: 1.7 }}>
          提交后<b>你这台机器立即生效</b>，同一句话下次就按你的说法翻。
          同一条被 3 个以上不同玩家报成同一句，才会进社区词库；
          说法有分歧时系统不会自动采纳任何一方。
        </div>
      </div>
    </div>
  );
}
