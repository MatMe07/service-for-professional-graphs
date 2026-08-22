param(
    [switch]$SkipTests
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$bundledPython = Join-Path $env:USERPROFILE 'venv\Scripts\python.exe'
$pythonExecutable = if ($env:GRAPH_SERVICE_PYTHON) {
    $env:GRAPH_SERVICE_PYTHON
} elseif (Test-Path -LiteralPath $bundledPython) {
    $bundledPython
} else {
    (Get-Command python -ErrorAction Stop).Source
}

& $pythonExecutable -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)"
if ($LASTEXITCODE -ne 0) {
    throw 'Python 3.12 or newer is required. Set GRAPH_SERVICE_PYTHON if needed.'
}

Set-Location -LiteralPath $projectRoot
$env:PYTHONPATH = Join-Path $projectRoot 'src'

if (-not $SkipTests) {
    & $pythonExecutable -m unittest discover -s tests
    if ($LASTEXITCODE -ne 0) { throw 'Tests failed.' }
}

& $pythonExecutable -m graph_service check-config --config 'examples/hh_profession_config.json'
if ($LASTEXITCODE -ne 0) { throw 'Project configuration validation failed.' }

$runOutput = & $pythonExecutable -m graph_service run `
    --config 'examples/hh_profession_config.json' `
    --runs-root 'data/runs'
if ($LASTEXITCODE -ne 0) { throw 'Pipeline failed.' }
$report = ($runOutput | Out-String) | ConvertFrom-Json

& $pythonExecutable -m graph_service check-run --run-dir $report.run_directory
if ($LASTEXITCODE -ne 0) { throw 'Run directory integrity validation failed.' }

$latestPath = Join-Path $projectRoot 'data\LATEST_RUN.json'
$report | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $latestPath -Encoding UTF8

Write-Host ''
Write-Host 'First working version completed successfully.' -ForegroundColor Green
Write-Host "Result: $($report.run_directory)"
Write-Host "HTML report: $(Join-Path $report.run_directory 'review_report.html')"
