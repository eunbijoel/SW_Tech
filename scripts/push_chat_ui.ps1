# Commit and push chat history + ChatGPT-style UI changes.
# Run from repo root:
#   cd C:\Users\keti\eunbi\ai-prompt-platform
#   powershell -ExecutionPolicy Bypass -File .\scripts\push_chat_ui.ps1

$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

Write-Host "Repository:" (Get-Location)

git status -sb

$files = @(
    "backend/services/chat_history_service.py",
    "backend/api/routes/history.py",
    "backend/main.py",
    "frontend/utils/api_client.py",
    "frontend/app.py",
    "frontend/pages"
)

foreach ($f in $files) {
    if (Test-Path $f) {
        git add $f
    } else {
        Write-Warning "Missing: $f"
    }
}

# Optional: other touched files in same feature (README, scripts)
if (Test-Path "README.md") { git add README.md }
if (Test-Path "scripts/git_commit_and_push.ps1") { git add scripts/*.ps1 }

git status

git diff --cached --quiet
if ($LASTEXITCODE -eq 0) {
    Write-Host "Nothing staged to commit. Check git status above."
    exit 0
}

git commit -m @"
feat: chat history API and ChatGPT-style Streamlit UI

- Add chat_history_service and /api/v1/history routes
- Register history router in backend main
- Extend api_client with save/list/load/delete chat helpers
- Rewrite frontend app.py as single-page chat UI
- Redirect legacy Chat page to main app
"@

# Remote may have README edits from GitHub — merge before push
Write-Host "Pulling origin/main (merge)..."
git pull origin main --no-rebase
if ($LASTEXITCODE -ne 0) {
    Write-Host "Pull failed. If you see merge conflicts, fix files then: git add . ; git commit"
    exit $LASTEXITCODE
}

git push -u origin main

Write-Host "Done. See https://github.com/eunbijoel/SW_Tech"
