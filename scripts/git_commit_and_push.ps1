# Run from repository root (recommended):
#   cd C:\Users\keti\eunbi\ai-prompt-platform
#   .\scripts\git_commit_and_push.ps1
#
# Excludes (via .gitignore): excel/, .venv/, .env, storage/uploads/, storage/results/, etc.

$ErrorActionPreference = "Stop"
$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $repoRoot

if (-not (Test-Path .git)) {
    git init
    git branch -M main
}

# Stop tracking paths that should stay local-only (safe if not tracked)
$toUntrack = @("excel", "storage/uploads", "storage/results", ".venv")
foreach ($p in $toUntrack) {
    if (Test-Path $p) {
        git rm -r --cached $p 2>$null
    }
}

git add -A
git diff --cached --quiet
if ($LASTEXITCODE -eq 0) {
    Write-Host "Nothing to commit (working tree clean or only ignored changes)."
    exit 0
}

git status
$msg = "chore: sync project state (exclude excel and runtime storage)"
git commit -m $msg

$hasOrigin = git remote get-url origin 2>$null
if (-not $hasOrigin) {
    git remote add origin "https://github.com/eunbijoel/SW_Tech.git"
}

git push -u origin main
Write-Host "Done: pushed to origin/main."
