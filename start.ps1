# CoSolve startup script
Write-Host "Activating virtual environment..." -ForegroundColor Cyan
.venv\Scripts\activate

Write-Host "Starting CoSolve server on port 8005..." -ForegroundColor Cyan
uvicorn backend.app:app --reload --port 8005 --log-level info
