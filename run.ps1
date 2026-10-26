param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]] $Rest
)

# Запуск mic-monitor: создаёт venv при первом старте, доставляет зависимости
# и открывает оверлей (pythonw — без лишнего консольного окна).

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$venv = Join-Path $root '.venv'
$python = Join-Path $venv 'Scripts\python.exe'
$script = Join-Path $root 'mic_monitor.py'

if (-not (Test-Path $python)) {
    Write-Host 'Первая настройка: создаю виртуальное окружение...'
    python -m venv $venv
    & $python -m pip install --upgrade pip --quiet
}

& $python -m pip install -r (Join-Path $root 'requirements.txt') --quiet

$pyw = Join-Path $venv 'Scripts\pythonw.exe'
if ($Rest -and $Rest.Count -gt 0) {
    & $python $script @Rest
    exit $LASTEXITCODE
}

if (Test-Path $pyw) {
    Start-Process -FilePath $pyw -ArgumentList $script -WorkingDirectory $root
} else {
    & $python $script
}
