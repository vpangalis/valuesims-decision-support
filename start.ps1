# CoSolve startup script

Write-Host "Activating virtual environment..." -ForegroundColor Cyan
.venv\Scripts\activate

# Kill ALL uvicorn/python processes to clear orphaned workers
Write-Host "Stopping all uvicorn/python processes..." -ForegroundColor Cyan
Get-Process -Name "python", "uvicorn" -ErrorAction SilentlyContinue | ForEach-Object {
    Write-Host "Killing $($_.Name) PID $($_.Id)..." -ForegroundColor Yellow
    $_ | Stop-Process -Force
}
Start-Sleep -Seconds 2
Write-Host "All processes cleared." -ForegroundColor Green

# Always sync with origin before starting — prevents running stale local code
Write-Host "Syncing with origin/architecture-refactor..." -ForegroundColor Cyan
$dirty = git status --porcelain
if ($dirty) {
    Write-Host "WARNING: uncommitted local changes detected:" -ForegroundColor Yellow
    Write-Host $dirty -ForegroundColor Yellow
    Write-Host "Fetching and hard-resetting to origin/architecture-refactor..." -ForegroundColor Yellow
    git fetch origin architecture-refactor
    git reset --hard origin/architecture-refactor
} else {
    git pull origin architecture-refactor
}

Write-Host "Starting CoSolve server on port 8010..." -ForegroundColor Cyan
uvicorn backend.app:app --workers 4 --port 8010 --log-level info
