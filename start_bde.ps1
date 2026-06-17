# start_bde.ps1 — Start all BDE background services
# Run this once after booting. Neo4j Desktop must already be started manually.
#
# Services started:
#   1. Celery worker  (processes all tasks — pool=solo for Windows compatibility)
#   2. Celery beat    (fires scheduled tasks on the crontab schedule)
#   3. Streamlit      (dashboard at http://localhost:8501)
#
# Logs go to: BDE\logs\worker.log, beat.log, streamlit.log

$BDE = $PSScriptRoot
$VENV = "$BDE\.venv\Scripts"
$LOGS = "$BDE\logs"

# Create logs dir if missing
if (-not (Test-Path $LOGS)) { New-Item -ItemType Directory -Path $LOGS | Out-Null }

Write-Host "Starting BDE services..." -ForegroundColor Cyan

# Kill any existing instances quietly
Get-Process -Name "celery" -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Get-Process -Name "streamlit" -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 1

# 1. Celery worker — pool=solo required on Windows (no fork support)
Write-Host "  Starting Celery worker..." -ForegroundColor Yellow
Start-Process -FilePath "$VENV\python.exe" `
    -ArgumentList "-m", "celery", "-A", "celery_app", "worker",
                  "--pool=solo", "--loglevel=info",
                  "--logfile=$LOGS\worker.log" `
    -WorkingDirectory $BDE `
    -WindowStyle Hidden

# 2. Celery beat — fires scheduled tasks
Write-Host "  Starting Celery beat..." -ForegroundColor Yellow
Start-Process -FilePath "$VENV\python.exe" `
    -ArgumentList "-m", "celery", "-A", "celery_app", "beat",
                  "--loglevel=info",
                  "--logfile=$LOGS\beat.log" `
    -WorkingDirectory $BDE `
    -WindowStyle Hidden

# 3. Streamlit dashboard
Write-Host "  Starting Streamlit dashboard..." -ForegroundColor Yellow
Start-Process -FilePath "$VENV\streamlit.exe" `
    -ArgumentList "run", "dashboard\app.py",
                  "--server.port=8501", "--server.headless=true" `
    -WorkingDirectory $BDE `
    -WindowStyle Hidden

Start-Sleep -Seconds 4

# Verify
$worker_ok  = Get-Process -Name "python" -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowTitle -eq "" }
$stream_ok  = Get-Process -Name "streamlit" -ErrorAction SilentlyContinue

Write-Host ""
if ($stream_ok) {
    Write-Host "BDE is running." -ForegroundColor Green
    Write-Host "  Dashboard : http://localhost:8501" -ForegroundColor Green
    Write-Host "  Worker log: $LOGS\worker.log" -ForegroundColor Gray
    Write-Host "  Beat log  : $LOGS\beat.log" -ForegroundColor Gray
} else {
    Write-Host "Warning: Streamlit did not start. Check logs." -ForegroundColor Red
}
