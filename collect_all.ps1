$professions = @(
    "python_developer"
    # "java_developer", 
    # "frontend_developer",
    # "fullstack_developer",
    # "dotnet_developer",
    # "cpp_developer",
    # "mobile_developer",
    # "devops_engineer",
    # "qa_engineer",
    # "system_analyst",
    # "business_analyst",
    # "data_analyst",
    # "data_engineer",
    # "data_scientist",
    # "machine_learning_engineer"
)

if (Test-Path ".env") {
    Get-Content ".env" | ForEach-Object {
        $name, $value = $_ -split '=', 2
        Set-Item -Path "env:$name" -Value $value
    }
}

$env:PYTHONPATH = "$PWD\src"

foreach ($prof in $professions) {
    Write-Host "=== Собираем $prof ===" -ForegroundColor Cyan
    
    python -m graph_service hh-requests --profession $prof --max-pages 1 --max-vacancies 1
    
    $runDir = Get-ChildItem -Path "data/runs" -Directory | Where-Object { $_.Name -like "*${prof}*" } | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    
    if ($runDir) {
        Write-Host "=== Собираем учебные материалы для $prof ===" -ForegroundColor Yellow
        python scripts/generate_learning_catalog.py --nodes "$($runDir.FullName)/input/nodes.json" --output "$($runDir.FullName)/learning_resources.json"
    }
    
    Write-Host "=== Готово $prof ===" -ForegroundColor Green
}
