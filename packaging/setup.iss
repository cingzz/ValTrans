; ValTrans 安装包脚本（Inno Setup 6）
; 构建: tools/bin/inno/ISCC.exe packaging/setup.iss
; 注意：AppVersion 必须与 src/version.py 的 VERSION 保持一致
;       （tests/verify_src.py 会自动比对，不一致即报错）

#define AppName "ValTrans"
#define AppVersion "0.2.22"
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
