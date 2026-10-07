/* ==========================================================================
   检查更新面板
   --------------------------------------------------------------------------
   完整链路（就是你说的那种通用做法）：

     你（作者）                          用户点「检查更新」
     ────────                          ──────────────────
     在 GitHub Releases 发一个 tag      程序拉 /releases/latest
     把安装包拖上去                        ↓
                                         显示：哪个版本 / 改了什么 / 多大
                                            ↓
                                         用户点「前往下载」
                                            ↓
                                         浏览器下载安装包
                                            ↓
                                         用户双击安装 → 覆盖安装

   为什么**不**做「静默下载 + 自动替换 exe」：

     · 静默下载 60MB 并替换**正在运行**的程序是所有软件最招人烦的行为
     · 安装包没做**代码签名**时，静默替换等于绕过 Windows 的安全提示，
       而绕过安全提示的行为，杀毒软件和用户都会当成木马
     · 覆盖安装只需要双击一下，跳过这一步没有任何收益

   所以流程是「点一下 → 看清 → 确认 → 浏览器下载 → 双击安装」。
   少一次点击，但换来用户知道发生了什么。
   ========================================================================== */
import { useState } from "react";

export default function UpdatePanel({ version, onCheck, openUrl }) {
  const [busy, setBusy] = useState(false);
  const [r, setR] = useState(null);
  const [open, setOpen] = useState(false);

  async function doCheck(silent) {
    setBusy(true);
    try {
      const res = await onCheck();
      setR(res || {});
      if (!silent && res && res.has_update) setOpen(true);
    } finally {
      setBusy(false);
    }
  }

  const has = r && r.has_update;

  return (
    <div className="card" style={{ marginTop: 12 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <h2 className="h2" style={{ margin: 0, flex: 1 }}>检查更新</h2>
        <button className="btn" disabled={busy} onClick={() => doCheck(false)}>
          {busy ? "检查中…" : "检查更新"}
        </button>
      </div>

      <div className="muted" style={{ marginTop: 8, fontSize: 13, lineHeight: 1.7 }}>
        当前 v{version}。更新会从 GitHub 官方 Releases 下载，不经过任何第三方。
      </div>

      {r && !r.ok && (
        <div className="muted" style={{ marginTop: 8, fontSize: 13 }}>
          {r.msg}
        </div>
      )}

      {r && r.ok && !has && (
        <div className="muted" style={{ marginTop: 8, fontSize: 13 }}>
          {r.msg || "已是最新"}
        </div>
      )}

      {has && (
        <div style={{ marginTop: 12 }}>
          <div style={{ fontSize: 14, fontWeight: 600, color: "var(--accent)" }}>
            发现新版本 v{r.remote}
          </div>

          {r.assets && r.assets.length > 0 && (
            <div style={{ marginTop: 10 }}>
              {r.assets.map((a) => (
                <div
                  key={a.url}
                  style={{
                    display: "flex", alignItems: "center", gap: 10,
                    padding: "8px 10px", marginBottom: 6,
                    background: "rgba(0,0,0,.03)", borderRadius: 8,
                    fontSize: 13,
                  }}
                >
                  <span style={{ flex: 1 }}>{a.name}</span>
                  <span className="muted">{a.size_mb} MB</span>
                  <button className="btn" onClick={() => openUrl(a.url)}>
                    下载
                  </button>
                </div>
              ))}
            </div>
          )}

          {r.notes && (
            <details style={{ marginTop: 10 }}>
              <summary style={{ cursor: "pointer", fontSize: 13 }}>
                更新内容
              </summary>
              <pre
                style={{
                  marginTop: 8, fontSize: 12, lineHeight: 1.7,
                  whiteSpace: "pre-wrap", fontFamily: "inherit",
                  color: "var(--muted)",
                }}
              >
                {r.notes}
              </pre>
            </details>
          )}

          <div style={{ marginTop: 12, display: "flex", gap: 8 }}>
            <button
              className="btn primary"
              onClick={() => openUrl(r.latest_url)}
            >
              前往下载页
            </button>
          </div>
          <div className="muted" style={{ marginTop: 8, fontSize: 12, lineHeight: 1.7 }}>
            下载后双击安装包覆盖安装即可，个人设置和词库都会保留。
          </div>
        </div>
      )}
    </div>
  );
}
