; ValTrans 安装包脚本（Inno Setup 6）
;
; 构建（顺序不能反，每一步都依赖上一步的产物）：
;   1. cd webui && npm.cmd run build      -> webui/dist（前端）
;      ★ 用 npm.cmd 不是 npm —— PowerShell 的执行策略会挡 npm.ps1
;   2. rmdir /s /q dist\ValTrans          -> 必须先删干净
;      ★ PyInstaller 的 COLLECT 只覆盖不删除。砍 Qt 之前那次如果没先删，
;        47.3MB 的 PySide6 会原封不动留在 _internal/ 里，跟着新包一起
;        被下面这一步打进安装器，而全程没有任何一步会报警。
;   3. python -m PyInstaller packaging\valtrans.spec --noconfirm --clean
;   4. ISCC.exe packaging\setup.iss       -> dist\ValTransSetup-<版本>.exe
;
;   ISCC 的位置随安装方式而变：winget 装的是每用户
;   （%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe），
;   官方安装包装的是全局（%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe）。
;   本机现状用 `winget list --id JRSoftware.InnoSetup` 一查便知。
;
; 注意：AppVersion 必须与 src/version.py 的 VERSION 保持一致
;       （tests/verify_src.py 会自动比对，不一致即报错）

#define AppName "ValTrans"
#define AppVersion "0.3.0"
#define AppPublisher "ValTrans Project"
#define AppExeName "ValTrans.exe"

[Setup]
AppId={{7C6D2E14-5B34-4A0F-9E7C-VALTRANS0001}}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
OutputDir=..\dist
OutputBaseFilename=ValTransSetup-{#AppVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
UninstallDisplayIcon={app}\{#AppExeName}
CloseApplications=yes
RestartApplications=no

[CustomMessages]
lang=chs
WelcomeLabel2=安装 ValTrans（{#AppVersion}）

[Languages]
Name: "chinesesimplified"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加任务:"
Name: "autostart"; Description: "开机自动启动（后台托盘）"; GroupDescription: "附加任务:"; Flags: unchecked

[Files]
Source: "..\dist\ValTrans\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "ValTrans"; ValueData: """{app}\{#AppExeName}"""; Flags: uninsdeletevalue; Tasks: autostart

[Run]
Filename: "{app}\{#AppExeName}"; Description: "启动 {#AppName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}"
