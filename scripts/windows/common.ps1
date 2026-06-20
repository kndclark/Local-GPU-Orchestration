# common.ps1
# Shared helpers for GPU Orchestrator Windows scripts. Dot-source this file:
#   . "$PSScriptRoot\common.ps1"

function Find-Python {
    foreach ($cmd in @("py", "python", "python3")) {
        try {
            $ver = & $cmd --version 2>&1
            if ($LASTEXITCODE -eq 0 -and $ver -match "Python 3") {
                return $cmd
            }
        } catch {}
    }
    throw "No Python 3 interpreter found. Install Python from https://python.org and ensure it is on your PATH."
}
