param(
    [switch] $SkipApp
)

# Сборка установщика: сначала exe (build.ps1), затем MicMonitor-Setup-<версия>.exe через Inno Setup.

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path

if (-not $SkipApp) {
    & pwsh -NoProfile -File (Join-Path $root 'build.ps1')
}

$iscc = @(
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
    "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    "C:\Program Files\Inno Setup 6\ISCC.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1

if (-not $iscc) {
    throw "Не найден ISCC.exe. Установите Inno Setup 6: winget install --id JRSoftware.InnoSetup -e"
}

& $iscc (Join-Path $root 'installer\mic-monitor.iss') | Select-Object -Last 6
if ($LASTEXITCODE -ne 0) { throw "ISCC завершился с кодом $LASTEXITCODE" }

Get-ChildItem (Join-Path $root 'dist') -Filter 'MicMonitor-Setup-*.exe' |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1 |
    ForEach-Object { Write-Host ("установщик: {0} ({1} МБ)" -f $_.FullName, [math]::Round($_.Length / 1MB, 1)) }
