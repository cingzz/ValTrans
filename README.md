# ValTrans — 《无畏契约》外服实时语音翻译

把队友的外语语音实时变成中文字幕；按住按键说中文，自动翻译成外语复制进剪贴板。
**同传式体验**：队友还在说话时字幕就开始出草稿，说完自动替换最终稿。
纯云端方案（本机零大模型、玩游戏不掉帧），代码全部自研，BYOK（用户自备免费 API Key）。

## 快速开始

1. 从 [Releases](https://github.com/cingzz/ValTrans/releases/latest) 下载安装包
   （**下载后请核对发布页附带的 SHA256 校验文件**）
2. 首次运行完成向导（免责声明 → 音频模式 → 填 API Key → 游戏显示模式提示）
3. 音频模式二选一：
   - **免驱动模式（推荐，30 秒上手）**：不装任何驱动，游戏内语音输出保持耳机即可；
     代价是会混入游戏音效，识别准确率略降
   - **虚拟声卡模式（进阶，识别更准）**：一键安装官方免费 VB-CABLE，
     游戏内「语音聊天输出设备」选 `CABLE Input`
4. 主页点「▷ 开始翻译」，进游戏即可

API Key 注册：[硅基流动](https://cloud.siliconflow.cn)（免费注册即送额度，识别+翻译+朗读共用一个 Key）。
巴西服（葡语）等可在设置页切换 Groq 预设。

## 功能

- **同传草稿字幕**：说话期间每秒出增量草稿，说完最终稿自动替换
- 队友语音 → 中文字幕浮窗（原文+译文，宽高可调，字号自适应，锁定后鼠标穿透）
- PTT 反向翻译：按住热键说中文 → 译成外语 → 自动复制剪贴板 + 朗读
- **CosyVoice2 云端音色**（超自然，支持克隆自己的声音；失败自动回落本地 edge-tts）
- 中文黑话谐音纠错（奶妈/尚勃勒/单摸…）、云端↔本地术语交叉校对、误报众包词库
  （点「提交误报」攒共识 → PR 进公共词库 → 全体用户经 CDN 自动更新，全程不收集隐私）
- 网络丢段/失败可见（明确提示，不装死）；相同文本缓存；多服务商自动降级
- API Key 经 Windows DPAPI 加密存储；驱动安装前校验官方数字签名

## 技术架构

```
游戏语音 → (虚拟声卡 / Loopback) → 16kHz 采集(soxr) → silero VAD 断句(onnxruntime, 1.2MB, 0.13ms/块)
        → 同传草稿支路（说话期间每秒增量识别+翻译）+ 最终段两级流水线（识别/翻译并行）
        → 云端 ASR (Qwen3-ASR) → 本地黑话表(1300+ 条, 0ms) → 云端翻译 (Qwen2.5-14B，失败降级链)
        → WinForms 原生浮窗（零 WebView 子进程）
```

本地零大模型、零 GPU 占用。安全约束：出站请求统一走安全模块（拒绝环回/私有/保留地址，
DNS 校验）；无服务器、无账号、无遥测——语音只发给你自己配置的云服务商。

## 从源码运行

需要 **Python 3.11+** 与 **Node.js 18+**。

```bash
git clone https://github.com/cingzz/ValTrans.git
cd ValTrans

python -m venv .venv
.venv\Scripts\activate                # Windows
# source .venv/bin/activate           # macOS / Linux

pip install -r requirements.txt

cd webui
npm install
npm run build                         # 产物在 webui/dist/

cd ..
python -m src.main                    # 启动
```

首次运行会走引导页：**确认合规声明 → 填你自己申请的 API Key → 选音频采集方式**。

> **API Key 是你自己的，软件不内置任何 Key。** 每个用户都要自己填，
> 不会共用、也不会被作者看到。Key 用 Windows DPAPI 加密存在
> `%APPDATA%\ValTrans\config.json`，绑定本机账户。

### 音频采集的两种方式

| 方式 | 说明 |
|---|---|
| **软件监听（推荐先用这个）** | WASAPI loopback，免驱动。选你的耳机/音箱即可 |
| **虚拟声卡** | 装 VB-CABLE（`assets/drivers/` 里是官方原版），游戏里输出选 `CABLE Input` |

### 打包

```bash
pyinstaller packaging/valtrans.spec                        # 先清残留进程，否则 PermissionError
tools/bin/inno/ISCC.exe packaging/setup.iss                # 生成安装包
```

可选代码签名：设 `VALTRANS_SIGN_THUMBPRINT` 后跑 `packaging/sign.ps1`；
发布物附 SHA256 校验文件。**发版时记得把 `src/version.py` 的 `VERSION`
与 `packaging/setup.iss` 的 `AppVersion` 改成同一个值**（ISCC 不读 Python，
不会自动同步）。

## 目录

| 路径 | 内容 |
|---|---|
| `src/core/` | 音频采集、VAD 断句、两级流水线、安全模块 |
| `src/services/` | 云端 ASR/翻译引擎、本地黑话表、词库同步、TTS、PTT、反馈草稿 |
| `src/uiweb/` | WebView2 主窗 + WinForms 原生浮窗 |
| `assets/` | silero VAD、图标、VB-CABLE 官方包、音频样本 |
| `scripts/` | 安全闸门（提交前检查密钥）与自证脚本 |
| `webui/` | React 前端源码（主窗） |

## 许可

GPL-3.0 开源；闭源/商用需向作者申请商业授权（见 LICENSE 与 LICENSE-COMMERCIAL.md）。
欢迎 PR：黑话词条、翻译误报、bug 修复都收——词条请附来源（解说/视频/对局）。

## 免责声明

本软件与 Riot Games 及《无畏契约》官方无任何关联。仅通过系统接口读取音频，不注入游戏进程、
不读取游戏内存、不修改游戏文件。使用第三方软件存在被反作弊系统处理的理论风险，请自行评估承担。
