# CoSolve startup script

Write-Host "Activating virtual environment..." -ForegroundColor Cyan
.venv\Scripts\activate

# Kill any existing process on port 8010 before starting
Write-Host "Checking for existing process on port 8010..." -ForegroundColor Cyan
$existing = Get-NetTCPConnection -LocalPort 8010 -ErrorAction SilentlyContinue
if ($existing) {
    $pids = $existing | Select-Object -ExpandProperty OwningProcess -Unique
    foreach ($pid in $pids) {
        Write-Host "Killing stale process PID $pid on port 8010..." -ForegroundColor Yellow
        Stop-Process -Id $pid -Force -ErrorAction SilentlyContinue
    }
    Start-Sleep -Seconds 2
    Write-Host "Port 8010 cleared." -ForegroundColor Green
} else {
    Write-Host "Port 8010 is free." -ForegroundColor Green
}

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
