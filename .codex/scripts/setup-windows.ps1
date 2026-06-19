$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Invoke-Optional {
    param(
        [Parameter(Mandatory = $true)]
        [scriptblock] $Command,
        [Parameter(Mandatory = $true)]
        [string] $Warning
    )

    try {
        & $Command
    }
    catch {
        Write-Warning "$Warning $($_.Exception.Message)"
    }
}

function Add-PathIfExists {
    param(
        [Parameter(Mandatory = $true)]
        [string] $Path
    )

    if ((Test-Path -LiteralPath $Path) -and (($env:Path -split ";") -notcontains $Path)) {
        $env:Path = "$Path;$env:Path"
    }
}

$repoRoot = (& git rev-parse --show-toplevel).Trim()
if (-not $repoRoot) {
    throw "This script must run inside a git checkout."
}
Set-Location -LiteralPath $repoRoot

if (-not (Test-Path -LiteralPath "pyproject.toml")) {
    throw "pyproject.toml was not found at repo root: $repoRoot"
}

Write-Host "Setting up CircuitSetup Energy Analyzer at $repoRoot"

rtk --version
rg --version | Select-Object -First 1
Add-PathIfExists -Path (Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Packages\ast-grep.ast-grep_Microsoft.Winget.Source_8wekyb3d8bbwe")
sg --version
Add-PathIfExists -Path (Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Packages\jqlang.jq_Microsoft.Winget.Source_8wekyb3d8bbwe")
jq --version
Add-PathIfExists -Path (Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Packages\MikeFarah.yq_Microsoft.Winget.Source_8wekyb3d8bbwe")
yq --version

$pythonExe = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $pythonExe)) {
    if (Get-Command uv -ErrorAction SilentlyContinue) {
        uv venv .venv --python 3.12
    }
    else {
        py -3.12 -m venv .venv
    }
}

& $pythonExe -m pip install --upgrade pip
& $pythonExe -m pip install -e ".[test]"
& $pythonExe -m pip install ruff jinja2 PyYAML voluptuous-serialize

gh --version
Invoke-Optional -Command { gh auth status } -Warning "GitHub CLI is not authenticated:"
Invoke-Optional `
    -Command { gh repo view CircuitSetup/CircuitSetup-Energy-Analyzer --json nameWithOwner,defaultBranchRef } `
    -Warning "Could not verify GitHub repository access:"

Write-Host "Setup complete."
