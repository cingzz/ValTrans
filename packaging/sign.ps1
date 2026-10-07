# ValTrans 发布物代码签名（可选；证书未配置时自动跳过，不打断发布）
#
# 用法（在打包完 PyInstaller / ISCC 之后调用）：
#   powershell -NoProfile -ExecutionPolicy Bypass -File packaging\sign.ps1 ^
#     -Files dist\ValTrans\ValTrans.exe, dist\ValTransSetup-0.2.18.exe
#
# 证书二选一（推荐证书商店方式，密码不落盘）：
#   方式 A：证书装进当前用户/本机证书商店，设环境变量
#       VALTRANS_SIGN_THUMBPRINT = 证书指纹（40 位十六进制，无空格）
#   方式 B：PFX 文件
#       VALTRANS_SIGN_PFX      = 证书文件路径
#       VALTRANS_SIGN_PFX_PASS = PFX 密码
#
# signtool 查找顺序：PATH → Windows Kits\10\bin 下最新版本的 x64。
param(
    [Parameter(Mandatory = $true)][string[]]$Files,
    [string]$Thumbprint = $env:VALTRANS_SIGN_THUMBPRINT,
    [string]$Pfx = $env:VALTRANS_SIGN_PFX,
    [string]$PfxPassword = $env:VALTRANS_SIGN_PFX_PASS
)

$ErrorActionPreference = "Stop"

function Find-Signtool {
    $cmd = Get-Command signtool.exe -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    $kits = Get-ChildItem "C:\Program Files (x86)\Windows Kits\10\bin" -Directory -ErrorAction SilentlyContinue |
        Sort-Object Name -Descending
    foreach ($k in $kits) {
        $p = Join-Path $k.FullName "x64\signtool.exe"
        if (Test-Path $p) { return $p }
    }
    return $null
}

if (-not $Thumbprint -and -not $Pfx) {
    Write-Host "[sign] 未配置签名证书（VALTRANS_SIGN_THUMBPRINT 或 VALTRANS_SIGN_PFX），跳过签名。"
    Write-Host "[sign] 购买 OV 代码签名证书后，把指纹设进环境变量即可启用（见本文件头注释）。"
    exit 0
}

$tool = Find-Signtool
if (-not $tool) {
    Write-Warning "[sign] 找不到 signtool.exe（请安装 Windows SDK 的 Signing Tools）——跳过签名。"
    exit 0
}
Write-Host "[sign] signtool = $tool"

$timestamp = "http://timestamp.digicert.com"
foreach ($f in $Files) {
    if (-not (Test-Path $f)) { Write-Warning "[sign] 文件不存在，跳过：$f"; continue }
    if ($Thumbprint) {
        & $tool sign /sha1 $Thumbprint /fd SHA256 /tr $timestamp /td SHA256 $f
    } else {
        & $tool sign /f $Pfx /p $PfxPassword /fd SHA256 /tr $timestamp /td SHA256 $f
    }
    if ($LASTEXITCODE -ne 0) { throw "签名失败：$f" }
    & $tool verify /pa /all $f
    if ($LASTEXITCODE -ne 0) { throw "签名校验失败：$f" }
    Write-Host "[sign] 已签名并验证：$f"
}
Write-Host "[sign] 完成。"
