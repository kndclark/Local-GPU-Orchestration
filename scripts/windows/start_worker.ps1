# start_worker.ps1
# Starts the GPU orchestrator worker agent on Windows (Desktop)

Write-Host "Starting GPU Orchestrator Worker Agent..."

# Ensure we're in the right directory
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location -Path "$ScriptDir\..\.."



# Run the agent module using the venv if it exists
if (Test-Path ".venv\Scripts\python.exe") {
    & ".venv\Scripts\python.exe" -m worker_agent.main
} else {
    python -m worker_agent.main
}
