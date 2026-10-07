/* ==========================================================================
   赞赏区
   --------------------------------------------------------------------------
   v0.2.11 需求背景：
   > 「赞赏码千万不要折叠起来，要直接展开放在那里。还要调大一点，不要太小了。」

   之前做成了 <details> 折叠（我以为"不打扰"优先），但那是**误判**：
   折叠起来的结果是**没人看见**，等于白做。用户是认可了这个软件才来
   这个页面的，看到二维码是给他一个表达的方式，藏起来反而是不信任读者。

   所以：默认展开、图放大到 200px、去掉折叠箭头。
   ========================================================================== */
import { useEffect, useState } from "react";

// 文件名必须与下方一致；改名会导致图片永远不显示
// ★ v0.2.22：微信码由 donate-wechat.jpg 改为 donate-wechat.png。
//   原因：新码是 500×500 的 PNG（头像/姓名版是 jpg）。文件名不同步的话
//   页面会走 onError 分支显示「把文件放到 webui/public/」的提示，
//   **看着像用户没放图，实际是组件里还写着旧名字** —— 这种错很难一眼看出。
export const DonateImg = {
  wechat: "/donate-wechat.png",
  alipay: "/donate-alipay.png",
};

/* v0.2.11（真机 实测）：
   「还有一个带照片的赞助框，应该要有这样一个功能：点开照片，照片就自动放大」
   —— 二维码只有 200px，看不清/不好扫，点一下放大到接近整屏。
   点任意处或按 Esc 关闭。 */
function Lightbox({ src, alt, onClose }) {
  useEffect(() => {
    const onKey = (e) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div
      onClick={onClose}
      style={{
        position: "fixed", inset: 0, zIndex: 1000,
        background: "rgba(0,0,0,.78)",
        display: "flex", alignItems: "center", justifyContent: "center",
        cursor: "zoom-out",
      }}
    >
      <img
        src={src} alt={alt}
        onClick={(e) => e.stopPropagation()}
        style={{
          maxWidth: "82vw", maxHeight: "82vh",
          imageRendering: "auto",
          borderRadius: 10,
          background: "#fff", padding: 10,
          boxShadow: "0 16px 60px rgba(0,0,0,.5)",
        }}
      />
      <div style={{
        position: "absolute", bottom: 26, left: 0, right: 0,
        textAlign: "center", color: "rgba(255,255,255,.75)", fontSize: 13,
      }}>
        点击任意处或按 Esc 关闭
      </div>
    </div>
  );
}

function Qr({ src, alt, hint }) {
  const [missing, setMissing] = useState(false);
  const [zoom, setZoom] = useState(false);
  useEffect(() => { setMissing(false); setZoom(false); }, [src]);
  return (
    <div className="donate-qr">
      {!missing && (
        <img
          src={src} alt={alt}
          onClick={() => setZoom(true)}
          onError={() => setMissing(true)}
          title="点击放大"
          style={{ cursor: "zoom-in" }}
        />
      )}
      {missing && <span>{hint}</span>}
      {zoom && <Lightbox src={src} alt={alt} onClose={() => setZoom(false)} />}
    </div>
  );
}

export default function Donate() {
  return (
    <div className="donate">
      <div className="donate-title">支持一下 ValTrans</div>

      <p className="donate-note">
        这个软件<b>完全免费、无广告、不联机收费</b>，
        翻译走你自己提供的 API Key，没有任何中间商。
        如果它帮你在对局里少挨了几次打，可以请作者喝杯奶茶 ——
        这也是唯一的支持方式。
      </p>

      <div className="donate-grid">
        <div className="donate-item">
          <Qr src={DonateImg.wechat} alt="微信赞赏码"
              hint="把 donate-wechat.png 放到 webui/public/ 即显示" />
          <div className="donate-item-cap">微信</div>
        </div>
        <div className="donate-item">
          <Qr src={DonateImg.alipay} alt="支付宝收款码"
              hint="把 donate-alipay.png 放到 webui/public/ 即显示" />
          <div className="donate-item-cap">支付宝</div>
        </div>
      </div>

      <p className="donate-thanks">
        赞赏不会解锁任何功能，也不会改变翻译行为 ——
        翻译质量取决于你的 API Key 和本地词库，与赞赏无关。
        <br />
        如果你想帮忙但不打算花钱，更实在的支持方式是
        <b>在「实时翻译」页点某条消息上的「误报」</b>：
        你纠正一条，整个社区都受益。
      </p>
    </div>
  );
}
