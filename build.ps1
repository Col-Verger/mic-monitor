param(
    [string] $Version = "",
    [switch] $NoDesktopCopy
)

# Сборка MicMonitor.exe (один файл, без консольного окна).
# Версия берётся из mic_monitor.py (__version__), если не передана явно.

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $root '.venv\Scripts\python.exe'

if (-not (Test-Path $python)) {
    python -m venv (Join-Path $root '.venv')
    & $python -m pip install --upgrade pip --quiet
}

& $python -m pip install -q -r (Join-Path $root 'requirements.txt')
& $python -m pip install -q -r (Join-Path $root 'requirements-dev.txt')

if (-not $Version) {
    $Version = (& $python -c "import sys; sys.path.insert(0, r'$root'); import mic_monitor; print(mic_monitor.__version__)").Trim()
}
Write-Host "версия: $Version"

& $python (Join-Path $root 'tools\make_icon.py')

$infoFile = Join-Path $root "build\version_info.txt"
& $python (Join-Path $root 'tools\make_version_info.py') $Version $infoFile | Out-Null

Push-Location $root
try {
    & $python -m PyInstaller `
        --noconfirm --clean --onefile --noconsole `
        --name MicMonitor `
        --icon (Join-Path $root 'mic.ico') `
        --version-file $infoFile `
        (Join-Path $root 'mic_monitor.py')
} finally {
    Pop-Location
}

$exe = Join-Path $root 'dist\MicMonitor.exe'
if (-not (Test-Path $exe)) { throw "сборка не дала exe: $exe" }

if (-not $NoDesktopCopy) {
    $desktop = [Environment]::GetFolderPath('Desktop')
    Copy-Item $exe (Join-Path $desktop 'MicMonitor.exe') -Force
    Write-Host "копия:  $(Join-Path $desktop 'MicMonitor.exe')"
}

$size = [math]::Round((Get-Item $exe).Length / 1MB, 1)
Write-Host "готово: $exe ($size МБ)"
