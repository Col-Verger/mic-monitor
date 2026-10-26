param(
    [switch] $SkipIcon
)

# Сборка MicMonitor.exe (один файл, без консольного окна) + копия на рабочий стол.

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $root '.venv\Scripts\python.exe'

if (-not (Test-Path $python)) {
    python -m venv (Join-Path $root '.venv')
    & $python -m pip install --upgrade pip --quiet
}

& $python -m pip install -q -r (Join-Path $root 'requirements.txt')
& $python -m pip install -q -r (Join-Path $root 'requirements-dev.txt')

if (-not $SkipIcon) {
    & $python (Join-Path $root 'tools\make_icon.py')
}

Push-Location $root
try {
    & $python -m PyInstaller `
        --noconfirm --clean --onefile --noconsole `
        --name MicMonitor `
        --icon (Join-Path $root 'mic.ico') `
        --version-file (Join-Path $root 'version_info.txt') `
        (Join-Path $root 'mic_monitor.py')
} finally {
    Pop-Location
}

$exe = Join-Path $root 'dist\MicMonitor.exe'
if (-not (Test-Path $exe)) { throw "сборка не дала exe: $exe" }

$desktop = [Environment]::GetFolderPath('Desktop')
Copy-Item $exe (Join-Path $desktop 'MicMonitor.exe') -Force

$size = [math]::Round((Get-Item $exe).Length / 1MB, 1)
Write-Host "готово: $exe ($size МБ)"
Write-Host "копия:  $(Join-Path $desktop 'MicMonitor.exe')"
