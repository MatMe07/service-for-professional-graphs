$professions = @(
    "python_developer",
    "java_developer", 
    "frontend_developer",
    "fullstack_developer",
    "dotnet_developer",
    "cpp_developer",
    "mobile_developer",
    "devops_engineer",
    "qa_engineer",
    "system_analyst",
    "business_analyst",
    "data_analyst",
    "data_engineer",
    "data_scientist",
    "machine_learning_engineer"
)

$env:PYTHONPATH = "$PWD\src"

foreach ($prof in $professions) {
    Write-Host "=== Собираем $prof ===" -ForegroundColor Cyan
    python -m graph_service hh-requests --profession $prof --max-pages 3
    Write-Host "=== Готово $prof ===" -ForegroundColor Green
}
