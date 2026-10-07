/* ==========================================================================
   上报反馈弹窗（v0.2.22）
   --------------------------------------------------------------------------
   用户的需求原话：
   > 「点击『上报反馈』，系统会自动上传整个日志。
   >  填写用户的详细反馈信息，以及需要优化的地方。
   >  如果有截图，就上传截图。」

   ★ 关于「自动上传」的一处诚实实现
   --------------------------------
   GitHub 创建 issue 的接口**必须带密钥**，而密钥不能随安装包分发给每个
   用户（等于把仓库写权限公开）。所以这里不是偷偷改成别的东西，而是：

       点「打开 GitHub 提交」→ 浏览器打开新建 issue 页，
       环境信息 + 日志尾巴 + 你写的反馈 都已经填好了，点一下就发出去。

   也就是「一键」这件事由浏览器完成，本程序负责把内容备齐。

   三个步骤对应需求的三句话：
     ① 系统自动上传日志  → get_feedback_draft() 取诊断信息 + 日志尾巴
     ② 填详细反馈/待优化 → 顶部文本框，用户写
     ③ 有截图就上传      → 选图 + 一键复制，粘到 GitHub 的编辑器里
        （截图没法走 URL 预填，只能让用户拖/粘一次）

   为什么日志只带尾部
   ------------------
   GitHub 单条 issue 正文上限约 64KB，实测 webui.log 有 282KB。
   整份塞进去用户还得自己删。出问题的时间点一定在最后，所以取尾部。
   完整日志在面板里给了路径，要细节可以自己把文件拖进 issue。
   ========================================================================== */
import { useEffect, useMemo, useRef, useState } from "react";
import { callOr } from "../api.js";

const URL_LIMIT = 7500;   // 多数服务器/代理对 URL 长度的上限，保守留余量

function readFileAsDataURL(file) {
  return new Promise((resolve, reject) => {
    const fr = new FileReader();
    fr.onload = () => resolve(fr.result);
    fr.onerror = reject;
    fr.readAsDataURL(file);
  });
}

export default function FeedbackDialog({ onClose }) {
  const [draft, setDraft] = useState(null);
  const [err, setErr] = useState("");
  const [text, setText] = useState("");
  const [shot, setShot] = useState(null);      // {name, dataUrl}
  const [copied, setCopied] = useState("");
  const taRef = useRef(null);
  const fileRef = useRef(null);

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const d = await callOr("get_feedback_draft");
        if (!alive) return;
        if (!d || !d.ok) { setErr((d && d.msg) || "读取诊断信息失败"); return; }
        setDraft(d);
      } catch (e) {
        if (alive) setErr("读取诊断信息失败：" + (e && e.message ? e.message : e));
      }
    })();
    return () => { alive = false; };
  }, []);

  // 正文 = 用户写的反馈 + 系统诊断 + 日志尾巴
  const body = useMemo(() => {
    if (!draft) return "";
    return [
      text.trim() || "_（请在这里写下你遇到的问题，以及希望怎么改进）_",
      "",
      "---",
      "",
      draft.env_block,
      "",
      "### 日志（末尾部分）",
      "",
      "```",
      draft.log_tail,
      "```",
      "",
      draft.log_files.length
        ? "> 完整日志在本机：" + draft.log_dir + "（需要的话可以把文件拖进本 issue）"
        : "",
    ].join("\n");
  }, [draft, text]);

  // URL 太长时逐步砍日志，保证一定打得开
  const { url, trimmed } = useMemo(() => {
    if (!draft) return { url: "", trimmed: 0 };
    const mk = (logText) => draft.issue_url + "?" + new URLSearchParams({
      title: "[反馈] ",
      body,
      labels: "",
    }).toString().replace(/labels=(&|$)/, "$1") +
      (logText === draft.log_tail ? "" : "");
    // 逐步缩短：日志 3000 -> 2000 -> 1200 -> 600 -> 0
    let logText = draft.log_tail;
    let u = mk(logText);
    for (const cap of [2000, 1200, 600, 0]) {
      if (u.length <= URL_LIMIT) break;
      logText = draft.log_tail.slice(-cap);
      const b = [
        text.trim() || "_（请在这里写下你遇到的问题，以及希望怎么改进）_",
        "", "---", "", draft.env_block,
        "", "### 日志（末尾部分）", "",
        "```", logText, "```", "",
        draft.log_files.length
          ? "> 完整日志在本机：" + draft.log_dir + "（可把文件拖进本 issue）"
          : "",
      ].join("\n");
      u = draft.issue_url + "?" + new URLSearchParams({
        title: "[反馈] ", body: b,
      }).toString();
    }
    return { url: u, trimmed: draft.log_tail.length - logText.length };
  }, [draft, text, body]);

  async function pickShot(e) {
    const f = e.target.files && e.target.files[0];
    if (!f) return;
    if (f.size > 12 * 1024 * 1024) {
      setErr("截图太大了（超过 12MB），换一张小的试试");
      return;
    }
    try {
      const url = await readFileAsDataURL(f);
      setShot({ name: f.name, dataUrl: url });
      setErr("");
    } catch (_) {
      setErr("读取图片失败");
    }
  }

  async function copyShot() {
    if (!shot) return;
    try {
      const blob = await (await fetch(shot.dataUrl)).blob();
      // ClipboardItem 只在部分环境可用，失败也不该阻断主流程
      await navigator.clipboard.write([new ClipboardItem({ [blob.type]: blob })]);
      setCopied("已复制，去 GitHub 编辑框里按 Ctrl+V 粘贴");
    } catch (_) {
      setCopied("复制失败：请手动把上面对话框里的图片拖进 GitHub 编辑框");
    }
    setTimeout(() => setCopied(""), 6000);
  }

  async function copyAll() {
    try {
      await navigator.clipboard.writeText(body);
      setCopied("全部内容已复制");
    } catch (_) {
      setCopied("复制失败，可以手动全选下面的文本框复制");
    }
    setTimeout(() => setCopied(""), 4000);
  }

  async function submit() {
    await callOr("open_url", url);
  }

  return (
    <div
      onClick={onClose}
      style={{
        position: "fixed", inset: 0, zIndex: 1000,
        background: "rgba(0,0,0,.62)",
        display: "flex", alignItems: "center", justifyContent: "center",
        padding: 24,
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          width: "min(760px, 100%)", maxHeight: "88vh", overflow: "auto",
          background: "var(--panel, #fff)", color: "var(--text)",
          borderRadius: 14, padding: 20,
          boxShadow: "0 20px 70px rgba(0,0,0,.5)",
        }}
      >
        <div style={{ fontSize: 16, fontWeight: 700, marginBottom: 4 }}>
          上报反馈
        </div>
        <div className="muted" style={{ fontSize: 12.5, lineHeight: 1.75,
                                         marginBottom: 14 }}>
          环境信息和日志尾巴<b>已经自动填好</b>，你只要写清楚哪里不好用、
          希望怎么改进，然后点「打开 GitHub 提交」。
          <br />
          本程序不会自动发送任何内容 —— 最后那一步在浏览器里由你确认。
        </div>

        {err && (
          <div style={{ color: "var(--danger)", fontSize: 13, marginBottom: 10 }}>
            {err}
          </div>
        )}

        {!draft && !err && (
          <div className="muted" style={{ fontSize: 13 }}>正在收集诊断信息…</div>
        )}

        {draft && (
          <>
            {/* ① 反馈正文 */}
            <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 6 }}>
              ① 你遇到的问题 / 希望优化的地方
            </div>
            <textarea
              ref={taRef}
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder={
                "例如：\n" +
                "· 浮窗在 2K 显示器上位置跑出屏幕了\n" +
                "· 日语队友说话时字幕要等 3 秒才出来\n" +
                "· 希望能把浮窗透明度调低一点"
              }
              style={{
                width: "100%", minHeight: 130, resize: "vertical",
                padding: 10, fontSize: 13, lineHeight: 1.7,
                fontFamily: "inherit", boxSizing: "border-box",
              }}
            />

            {/* ② 日志 */}
            <div style={{ fontSize: 13, fontWeight: 600, margin: "14px 0 6px" }}>
              ② 日志（已自动附带，共 {(draft.log_tail.length / 1000).toFixed(1)}k 字符）
            </div>
            <pre
              style={{
                maxHeight: 130, overflow: "auto", fontSize: 11.5,
                lineHeight: 1.6, whiteSpace: "pre-wrap", fontFamily: "inherit",
                color: "var(--muted)", background: "rgba(0,0,0,.04)",
                padding: 10, borderRadius: 8, margin: 0,
              }}
            >
              {draft.env_block}
              {"\n\n"}
              {draft.log_tail.slice(-600)}…
            </pre>
            <div className="muted" style={{ fontSize: 11.5, marginTop: 6,
                                             lineHeight: 1.7 }}>
              {draft.log_files.length
                ? "完整日志在本机：" + draft.log_dir
                : "没找到日志文件"}
              {draft.log_redacted > 0
                ? `（已自动隐去 ${draft.log_redacted} 处疑似密钥）` : ""}
              {trimmed > 0
                ? ` · 为控制提交长度，日志已缩到尾部 ${draft.log_tail.length - trimmed} 字符`
                : ""}
              <br />
              日志里只有程序做了什么，不含你的语音内容与 API Key；
              但仍可能含本机路径，发前请扫一眼。
            </div>

            {/* ③ 截图 */}
            <div style={{ fontSize: 13, fontWeight: 600, margin: "14px 0 6px" }}>
              ③ 有截图的话（可选）
            </div>
            <input ref={fileRef} type="file" accept="image/*"
                   onChange={pickShot} style={{ display: "none" }} />
            <div style={{ display: "flex", gap: 8, alignItems: "center",
                          flexWrap: "wrap" }}>
              <button className="btn" onClick={() => fileRef.current?.click()}>
                选择截图
              </button>
              {shot && (
                <button className="btn" onClick={copyShot}>
                  复制这张图，去 GitHub 里粘贴
                </button>
              )}
              {shot && (
                <span className="muted" style={{ fontSize: 12 }}>
                  已选：{shot.name}
                </span>
              )}
            </div>
            {shot && (
              <img
                src={shot.dataUrl}
                alt="截图预览"
                style={{
                  marginTop: 10, maxHeight: 180, maxWidth: "100%",
                  borderRadius: 8, border: "1px solid rgba(0,0,0,.12)",
                }}
              />
            )}
            <div className="muted" style={{ fontSize: 11.5, marginTop: 6,
                                             lineHeight: 1.7 }}>
              截图无法走链接预填（图片不进 URL），所以复制后要在 GitHub 的
              编辑框里按 Ctrl+V 粘一次。
            </div>

            {copied && (
              <div style={{ marginTop: 12, fontSize: 12.5,
                            color: "var(--accent)" }}>
                {copied}
              </div>
            )}

            {/* 底部 */}
            <div style={{ display: "flex", gap: 8, marginTop: 18,
                          justifyContent: "flex-end", flexWrap: "wrap" }}>
              <button className="btn" onClick={copyAll}>
                复制全部内容
              </button>
              <button className="btn" onClick={() => callOr("open_log_folder")}>
                打开日志文件夹
              </button>
              <button className="btn primary" onClick={submit}>
                打开 GitHub 提交
              </button>
              <button className="btn" onClick={onClose}>取消</button>
            </div>

            <div className="muted" style={{ fontSize: 11, marginTop: 10,
                                             lineHeight: 1.7 }}>
              提交链接长度 {url.length} 字符
              {url.length > URL_LIMIT ? "（超长，已尽量裁剪）" : ""} ·
              仓库 {draft.repo}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
