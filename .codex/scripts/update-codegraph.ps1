param(
    [switch] $ExcludeTests
)

# Equivalent command:
# python docs\codegraph\generate_codegraph.py . --output-dir docs/codegraph/generated

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repoRoot = (& git rev-parse --show-toplevel).Trim()
if (-not $repoRoot) {
    throw "This script must run inside a git checkout."
}
Set-Location -LiteralPath $repoRoot

$generator = Join-Path $repoRoot "docs\codegraph\generate_codegraph.py"
if (-not (Test-Path -LiteralPath $generator)) {
    throw "Missing codegraph generator: $generator"
}

$pythonExe = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $pythonExe)) {
    $pythonExe = "py"
    $pythonArgs = @("-3.12")
}
else {
    $pythonArgs = @()
}

$generatorArgs = @(
    "docs\codegraph\generate_codegraph.py",
    ".",
    "--output-dir",
    "docs/codegraph/generated"
)

if ($ExcludeTests) {
    $generatorArgs += "--exclude-tests"
}

& $pythonExe @pythonArgs @generatorArgs
