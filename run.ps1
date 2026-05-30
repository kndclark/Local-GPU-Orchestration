# run.ps1
# One-click quick install and run script for the GPU Orchestrator Worker (Windows)

param(
    [switch]$ForceNvidia
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location -Path $ScriptDir

Write-Host "==================================================" -ForegroundColor Cyan
Write-Host " Starting One-Click Install & Run (Windows)" -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor Cyan

# 1. Run Setup
Write-Host "`n>> Running setup..." -ForegroundColor Cyan
try {
    if ($ForceNvidia) {
        .\scripts\windows\setup.ps1 -ForceNvidia
    } else {
        .\scripts\windows\setup.ps1
    }
    if ($LASTEXITCODE -ne 0 -and $LASTEXITCODE -ne $null) {
        throw "Setup script exited with code $LASTEXITCODE"
    }
} catch {
    Write-Host "[X] Setup failed: $($_.Exception.Message). Aborting." -ForegroundColor Red
    exit 1
}

# 2. Run Worker
Write-Host "`n>> Setup successful. Starting worker daemon..." -ForegroundColor Cyan
try {
    .\scripts\windows\start_worker.ps1
    if ($LASTEXITCODE -ne 0 -and $LASTEXITCODE -ne $null) {
        throw "Worker script exited with code $LASTEXITCODE"
    }
} catch {
    Write-Host "[X] Worker daemon crashed or failed to start: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
