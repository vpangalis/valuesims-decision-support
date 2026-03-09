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

# Always sync with origin/main before starting
Write-Host "Syncing with origin/main..." -ForegroundColor Cyan
$dirty = git status --porcelain
if ($dirty) {
    Write-Host "WARNING: uncommitted local changes detected:" -ForegroundColor Yellow
    Write-Host $dirty -ForegroundColor Yellow
    Write-Host "Fetching and hard-resetting to origin/main..." -ForegroundColor Yellow
    git fetch origin main
    git reset --hard origin/main
} else {
    git pull origin main
}

Write-Host "Starting CoSolve server on port 8010..." -ForegroundColor Cyan
# NOTE: Windows does not support uvicorn multiprocessing socket sharing reliably.
# Single worker is correct for local dev/demo. For production, use a Linux host
# with gunicorn or a process manager.
uvicorn backend.app:app --port 8010 --log-level info