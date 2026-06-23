# start_control_plane.ps1
# Starts the GPU Orchestrator Control Plane on Windows (FastAPI on :8080, gRPC on :50051)

. "$PSScriptRoot\common.ps1"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location -Path "$ScriptDir\..\.."

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Host "[X] Virtual environment not found. Run .\scripts\windows\setup.ps1 first." -ForegroundColor Red
    exit 1
}

Write-Host "Starting GPU Orchestrator Control Plane..."
Write-Host "  REST API  -> http://localhost:8080"
Write-Host "  gRPC      -> localhost:50051"
Write-Host "  Metrics   -> http://localhost:8080/metrics"
Write-Host ""

& ".venv\Scripts\python.exe" -m uvicorn control_plane.main:app --host 0.0.0.0 --port 8080
