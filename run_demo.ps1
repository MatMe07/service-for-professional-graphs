$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
python -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)"
if ($LASTEXITCODE -ne 0) {
    throw 'Нужен Python 3.12 или новее. Установите его и убедитесь, что команда python указывает на новую версию.'
}
$env:PYTHONPATH = Join-Path $projectRoot 'src'
Set-Location -LiteralPath $projectRoot
python -m graph_service run `
    --config 'examples/profession_config.json' `
    --runs-root 'data/runs'
