# Запуск API из корня папки backend (нужен Python с зависимостями проекта).
Set-Location $PSScriptRoot
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
