# start_worker.ps1
# Starts the GPU orchestrator worker agent on Windows (Desktop)

Write-Host "Starting GPU Orchestrator Worker Agent..."

# Ensure we're in the right directory
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location -Path "$ScriptDir\..\.."

# Set the Orchestrator Control Plane URL here
# Example: $env:ORCHESTRATOR_URL="192.168.1.100:50051"
if (-not $env:ORCHESTRATOR_URL) {
    Write-Host "Warning: ORCHESTRATOR_URL not set, defaulting to localhost:50051" -ForegroundColor Yellow
}

# Run the agent module using the venv if it exists
if (Test-Path ".venv\Scripts\python.exe") {
    & ".venv\Scripts\python.exe" -m worker_agent.main
} else {
    python -m worker_agent.main
}
