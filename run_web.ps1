param(
    [int]$Port = 8765
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$bundledPython = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$pythonExecutable = if ($env:GRAPH_SERVICE_PYTHON) {
    $env:GRAPH_SERVICE_PYTHON
} elseif (Test-Path -LiteralPath $bundledPython) {
    $bundledPython
} else {
    (Get-Command python -ErrorAction Stop).Source
}

Set-Location -LiteralPath $projectRoot
$env:PYTHONPATH = Join-Path $projectRoot 'src'
$address = "http://127.0.0.1:$Port"

Write-Host "Professional Graphs: $address" -ForegroundColor Cyan
Write-Host 'Остановить сервер: Ctrl+C'
Start-Process $address
& $pythonExecutable -m graph_service serve --project-root $projectRoot --host 127.0.0.1 --port $Port
