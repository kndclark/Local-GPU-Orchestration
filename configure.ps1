# configure.ps1
# Wrapper script to run the GPU Orchestrator configuration tool (Windows)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location -Path $ScriptDir

# Check if python is available
try {
    $pythonVersion = python --version 2>&1
} catch {
    Write-Host "[X] Python is not installed or not in PATH." -ForegroundColor Red
    exit 1
}

Write-Host ">> Launching configuration tool..." -ForegroundColor Cyan
python .\scripts\configure.py
