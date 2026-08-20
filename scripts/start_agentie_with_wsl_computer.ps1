param(
    [string]$Distro = "Ubuntu",
    [int]$Port = 8000
)

$ErrorActionPreference = "Stop"

Write-Host "Starting Agentie WSL Computer..." -ForegroundColor Cyan

function Invoke-Wsl($Command) {
    wsl.exe -d $Distro -- bash -lc $Command
    if ($LASTEXITCODE -ne 0) {
        throw "WSL command failed: $Command"
    }
}

# This starts WSL if it is not already running, then starts the persistent XFCE/noVNC computer.
Invoke-Wsl "test -x ~/.agentie-computer/start.sh || (echo 'Agentie WSL computer is not set up. Run: bash /mnt/c/Users/user/agentie-v2/scripts/setup_wsl_computer.sh' >&2; exit 2)"
Invoke-Wsl "~/.agentie-computer/start.sh"

Write-Host "Starting Agentie API on port $Port..." -ForegroundColor Cyan
$env:AGENTIE_COMPUTER_MODE = "wsl-novnc"
$env:AGENTIE_COMPUTER_URL = "http://127.0.0.1:6080/vnc.html?host=127.0.0.1&port=6080&autoconnect=1&resize=remote&reconnect=1"
$env:PORT = "$Port"

python main.py
