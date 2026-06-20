# setup.ps1
# Automates the setup of the GPU Orchestrator Worker Agent on Windows

param(
    [switch]$ForceNvidia,
    [string]$OrchestratorUrl = "auto"
)

$ErrorActionPreference = "Stop"
. "$PSScriptRoot\common.ps1"

Write-Host "==================================================" -ForegroundColor Cyan
Write-Host " GPU Orchestrator Worker Agent Setup (Windows)    " -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host ""

# 1. Check for Python 3
try {
    $Python = Find-Python
    $pythonVersion = & $Python --version 2>&1
    Write-Host "[OK] Python found: $pythonVersion (via '$Python')" -ForegroundColor Green
} catch {
    Write-Host "[X] $_" -ForegroundColor Red
    exit 1
}

# 2. Check for GPU hardware to determine dependencies
$hasNvidia = $false
$hasAmd = $false

Write-Host "Detecting GPU hardware..."
$videoControllers = Get-CimInstance -ClassName Win32_VideoController
foreach ($vc in $videoControllers) {
    $name = $vc.Name
    if ($name -match "NVIDIA") {
        $hasNvidia = $true
        Write-Host "[OK] NVIDIA GPU detected: $name" -ForegroundColor Green
    }
    if ($name -match "AMD" -or $name -match "Radeon") {
        $hasAmd = $true
        Write-Host "[OK] AMD GPU detected: $name" -ForegroundColor Green
    }
}

if ($ForceNvidia) {
    $hasNvidia = $true
    Write-Host "[OK] Forcing NVIDIA dependency installation via flag." -ForegroundColor Yellow
} elseif (-not $hasNvidia -and -not $hasAmd) {
    Write-Host "[INFO] No discrete GPU detected. Will install base dependencies." -ForegroundColor Yellow
}

# 3. Create Virtual Environment
if (Test-Path ".venv\Scripts\python.exe") {
    Write-Host "`n[OK] Virtual environment already exists, skipping creation." -ForegroundColor Green
} else {
    Write-Host "`nCreating virtual environment (.venv)..."
    & $Python -m venv .venv
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[X] Failed to create virtual environment." -ForegroundColor Red
        exit 1
    }
}


# 4. Install Dependencies
Write-Host "`nInstalling dependencies..."
$pipPath = ".venv\Scripts\pip.exe"
& $pipPath install --upgrade pip

if ($hasNvidia) {
    Write-Host "Installing base dependencies + NVIDIA support..."
    & $pipPath uninstall -y pynvml
    & $pipPath install -e .[nvidia]
} else {
    Write-Host "Installing base dependencies..."
    & $pipPath install -e .
}

Write-Host "`nCompiling protobufs..."
$pythonPath = ".venv\Scripts\python.exe"
& $pythonPath scripts/compile_protos.py

# 5. Configure Environment Variables
Write-Host "`n==================================================" -ForegroundColor Cyan
Write-Host " Configuration" -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "The worker will use Orchestrator URL: $OrchestratorUrl"

"ORCHESTRATOR_URL=`"$OrchestratorUrl`"" | Out-File -FilePath ".env" -Encoding utf8
Write-Host "[OK] Configuration saved to .env" -ForegroundColor Green

Write-Host "`n==================================================" -ForegroundColor Cyan
Write-Host " Setup Complete! [SUCCESS]" -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "To start the worker agent, run:"
Write-Host "  .\scripts\windows\start_worker.ps1" -ForegroundColor Yellow
Write-Host ""
