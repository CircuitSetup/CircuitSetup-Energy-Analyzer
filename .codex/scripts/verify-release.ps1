param(
    [string] $Tag
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repoRoot = (& git rev-parse --show-toplevel).Trim()
if (-not $repoRoot) {
    throw "This script must run inside a git checkout."
}
Set-Location -LiteralPath $repoRoot

rtk pytest tests/test_release_version.py tests/test_release_workflow.py -q
rtk ruff check .

gh auth status

if ($Tag) {
    git fetch --tags origin
    $pythonExe = Join-Path $repoRoot ".venv\Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $pythonExe)) {
        $pythonExe = "python"
    }
    & $pythonExe scripts\verify_release_batch.py `
        --tag $Tag `
        --minimum-prs 2 `
        --repository CircuitSetup/CircuitSetup-Energy-Analyzer
}
else {
    Write-Host "Pass -Tag vX.Y.Z to verify the release PR batch for a local tag."
}
