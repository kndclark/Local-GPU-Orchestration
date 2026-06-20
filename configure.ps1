# configure.ps1
# Wrapper script to run the GPU Orchestrator configuration tool (Windows)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location -Path $ScriptDir
. "$ScriptDir\scripts\windows\common.ps1"

if (Test-Path ".venv\Scripts\python.exe") {
    $Python = ".venv\Scripts\python.exe"
} else {
    try { $Python = Find-Python } catch {
        Write-Host "[X] $_" -ForegroundColor Red
        exit 1
    }
}

Write-Host ">> Launching configuration tool..." -ForegroundColor Cyan
& $Python .\scripts\configure.py
