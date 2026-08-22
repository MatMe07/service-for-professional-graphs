param(
    [int]$MaxPages = 3,
    [int]$MaxVacancies = 50,
    [int]$PeriodDays = 30,
    [int]$PauseBetweenProfessionsSeconds = 10
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$pythonExecutable = if ($env:GRAPH_SERVICE_PYTHON) {
    $env:GRAPH_SERVICE_PYTHON
} else {
    (Get-Command python -ErrorAction Stop).Source
}
$professions = @(
    'python_developer',
    'java_developer',
    'frontend_developer',
    'fullstack_developer',
    'dotnet_developer',
    'cpp_developer',
    'mobile_developer',
    'devops_engineer',
    'qa_engineer',
    'system_analyst',
    'business_analyst',
    'data_analyst',
    'data_engineer',
    'data_scientist',
    'machine_learning_engineer'
)

if ($MaxPages -lt 1 -or $MaxPages -gt 100) {
    throw 'MaxPages must be between 1 and 100.'
}
if ($MaxVacancies -lt 1) {
    throw 'MaxVacancies must be at least 1 for a batch run.'
}
if ($PeriodDays -lt 1 -or $PeriodDays -gt 3650) {
    throw 'PeriodDays must be between 1 and 3650.'
}
if ($PauseBetweenProfessionsSeconds -lt 0) {
    throw 'PauseBetweenProfessionsSeconds cannot be negative.'
}

Set-Location -LiteralPath $projectRoot

if (Test-Path -LiteralPath '.env') {
    Get-Content -LiteralPath '.env' | ForEach-Object {
        $line = $_.Trim()
        if ($line -and -not $line.StartsWith('#')) {
            $name, $value = $line -split '=', 2
            if (-not $name -or $null -eq $value) {
                throw "Invalid .env entry: $line"
            }
            Set-Item -Path "env:$($name.Trim())" -Value $value.Trim()
        }
    }
}

$env:PYTHONPATH = Join-Path $projectRoot 'src'
$failures = @()

for ($index = 0; $index -lt $professions.Count; $index++) {
    $profession = $professions[$index]
    Write-Host "=== Собираем $profession ===" -ForegroundColor Cyan

    & $pythonExecutable -m graph_service hh-requests `
        --profession $profession `
        --period-days $PeriodDays `
        --max-pages $MaxPages `
        --max-vacancies $MaxVacancies

    if ($LASTEXITCODE -ne 0) {
        $failures += $profession
        Write-Warning "Сбор вакансий для $profession завершился с ошибкой; учебные материалы пропущены."
    } else {
        $runDir = Get-ChildItem -LiteralPath 'data/runs' -Directory |
            Where-Object { $_.Name -like "*${profession}*" } |
            Sort-Object LastWriteTime -Descending |
            Select-Object -First 1

        if ($runDir) {
            Write-Host "=== Собираем учебные материалы для $profession ===" -ForegroundColor Yellow
            & $pythonExecutable scripts/generate_learning_catalog.py `
                --nodes (Join-Path $runDir.FullName 'input/nodes.json') `
                --output (Join-Path $runDir.FullName 'learning_resources.json')
            if ($LASTEXITCODE -ne 0) {
                $failures += "$profession (learning)"
                Write-Warning "Сбор учебных материалов для $profession завершился с ошибкой."
            }
        } else {
            $failures += "$profession (run directory)"
            Write-Warning "Не найдена папка результата для $profession."
        }
    }

    if ($index -lt $professions.Count - 1 -and $PauseBetweenProfessionsSeconds -gt 0) {
        Write-Host "Пауза $PauseBetweenProfessionsSeconds сек. перед следующей профессией..."
        Start-Sleep -Seconds $PauseBetweenProfessionsSeconds
    }
}

if ($failures.Count -gt 0) {
    throw "Не завершены этапы: $($failures -join ', ')"
}

Write-Host '=== Все профессии успешно обработаны ===' -ForegroundColor Green
