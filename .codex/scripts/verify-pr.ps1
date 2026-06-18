param(
    [switch] $HomeAssistant
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repoRoot = (& git rev-parse --show-toplevel).Trim()
if (-not $repoRoot) {
    throw "This script must run inside a git checkout."
}
Set-Location -LiteralPath $repoRoot

rtk git diff --check
rtk ruff check .
rtk pytest -q

if ($HomeAssistant) {
    $pythonExe = Join-Path $repoRoot ".venv\Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $pythonExe)) {
        throw "Missing .venv Python. Run .codex/scripts/setup-windows.ps1 first."
    }
    & $pythonExe -m pytest tests\test_control_entities.py tests\test_config_flow.py tests_homeassistant -q
}
