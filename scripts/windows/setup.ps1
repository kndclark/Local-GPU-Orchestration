# setup.ps1
# Automates the setup of the GPU Orchestrator Worker Agent on Windows

$ErrorActionPreference = "Stop"

Write-Host "==================================================" -ForegroundColor Cyan
Write-Host " GPU Orchestrator Worker Agent Setup (Windows)    " -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host ""

# 1. Check for Python 3
try {
    $pythonVersion = & python --version 2>&1
    Write-Host "[OK] Python found: $pythonVersion" -ForegroundColor Green
} catch {
    Write-Host "[X] Python is not installed or not in your PATH. Please install Python 3 and try again." -ForegroundColor Red
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

if (-not $hasNvidia -and -not $hasAmd) {
    Write-Host "[INFO] No discrete GPU detected. Will install base dependencies." -ForegroundColor Yellow
}

# 3. Create Virtual Environment
Write-Host "`nCreating virtual environment (.venv)..."
& python -m venv .venv
if ($LASTEXITCODE -ne 0) {
    Write-Host "[X] Failed to create virtual environment." -ForegroundColor Red
    exit 1
}


# 4. Install Dependencies
Write-Host "`nInstalling dependencies..."
$pipPath = ".venv\Scripts\pip.exe"
& $pipPath install --upgrade pip

if ($hasNvidia) {
    Write-Host "Installing base dependencies + NVIDIA (pynvml) support..."
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
Write-Host "The worker needs the address of the Control Plane (e.g., 192.168.1.100:50051)."
$orchUrl = Read-Host "Orchestrator URL [Press Enter to accept default: localhost:50051]"

if ([string]::IsNullOrWhiteSpace($orchUrl)) {
    $orchUrl = "localhost:50051"
}

"ORCHESTRATOR_URL=`"$orchUrl`"" | Out-File -FilePath ".env" -Encoding utf8
Write-Host "[OK] Configuration saved to .env" -ForegroundColor Green

Write-Host "`n==================================================" -ForegroundColor Cyan
Write-Host " Setup Complete! [SUCCESS]" -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "To start the worker agent, run:"
Write-Host "  .\scripts\windows\start_worker.ps1" -ForegroundColor Yellow
Write-Host ""
