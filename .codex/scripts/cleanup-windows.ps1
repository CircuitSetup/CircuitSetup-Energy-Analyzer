$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Assert-PathInsideRepo {
    param(
        [Parameter(Mandatory = $true)]
        [string] $Path,
        [Parameter(Mandatory = $true)]
        [string] $RepoRoot
    )

    $resolvedPath = (Resolve-Path -LiteralPath $Path).Path
    $resolvedRoot = (Resolve-Path -LiteralPath $RepoRoot).Path
    $prefix = $resolvedRoot.TrimEnd('\') + '\'

    if ($resolvedPath -eq $resolvedRoot -or -not $resolvedPath.StartsWith($prefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to remove path outside repo scope: $resolvedPath"
    }

    return $resolvedPath
}

$repoRoot = (& git rev-parse --show-toplevel).Trim()
if (-not $repoRoot) {
    throw "This script must run inside a git checkout."
}
Set-Location -LiteralPath $repoRoot

Write-Host "Cleaning generated caches under $repoRoot"
rtk git status --short --branch

$skipPrefixes = @(
    (Join-Path $repoRoot ".git"),
    (Join-Path $repoRoot ".venv")
)

$cacheDirs = Get-ChildItem -LiteralPath $repoRoot -Force -Recurse -Directory -ErrorAction SilentlyContinue |
    Where-Object {
        $fullName = $_.FullName
        $insideSkippedTree = $false
        foreach ($prefix in $skipPrefixes) {
            if ($fullName.StartsWith($prefix, [System.StringComparison]::OrdinalIgnoreCase)) {
                $insideSkippedTree = $true
                break
            }
        }
        -not $insideSkippedTree -and $_.Name -in @("__pycache__", ".pytest_cache", ".ruff_cache")
    }

foreach ($dir in $cacheDirs) {
    $safePath = Assert-PathInsideRepo -Path $dir.FullName -RepoRoot $repoRoot
    Remove-Item -LiteralPath $safePath -Recurse -Force
}

$pycFiles = Get-ChildItem -LiteralPath $repoRoot -Force -Recurse -File -Filter "*.pyc" -ErrorAction SilentlyContinue |
    Where-Object {
        $fullName = $_.FullName
        -not $fullName.StartsWith((Join-Path $repoRoot ".git"), [System.StringComparison]::OrdinalIgnoreCase) -and
        -not $fullName.StartsWith((Join-Path $repoRoot ".venv"), [System.StringComparison]::OrdinalIgnoreCase)
    }

foreach ($file in $pycFiles) {
    $safePath = Assert-PathInsideRepo -Path $file.FullName -RepoRoot $repoRoot
    Remove-Item -LiteralPath $safePath -Force
}

if (Test-Path -LiteralPath ".coverage") {
    $coveragePath = Assert-PathInsideRepo -Path ".coverage" -RepoRoot $repoRoot
    Remove-Item -LiteralPath $coveragePath -Force
}

rtk git worktree prune --dry-run
Write-Host "Cleanup complete. Worktree prune was dry-run only."
