# ===========================================================================
#  push_all.ps1  -  commit the latest code and push dev -> main -> prod
#
#  Use INSTEAD of the manual routine. From the repo folder:
#      powershell -ExecutionPolicy Bypass -File .\push_all.ps1 -Message "Sales: what changed"
#  (no -Message = "Sales: update")
#
#  What it does, in order:
#    1. makes sure service-account keys and _to_delete backup folders are ignored,
#    2. commits everything else on dev (skips the commit if nothing changed),
#    3. FIRST RUN ONLY: strips the accidentally-committed service_account.json out
#       of every past commit on every branch (GitHub blocks pushes that contain
#       it). The file stays on disk. On later runs this step does nothing.
#    4. pushes dev, merges into main and pushes, merges into prod and pushes,
#    5. returns you to dev.
#  It STOPS at the first problem and tells you what it was - it never force-pushes.
# ===========================================================================
param([string]$Message = "Sales: update")

$ErrorActionPreference = 'Stop'
$Repo   = "C:\Users\vaibh\Documents\IntelliBI Automation\IntelliBI_Sales_Automation"
$Secret = "counsellor_app/packaging/dist/Server/credentials/service_account.json"

function Step([string]$text) { Write-Host ""; Write-Host "==> $text" -ForegroundColor Cyan }
function Must([string]$what) {
    if ($LASTEXITCODE -ne 0) { throw "FAILED: $what  (see the git output above). Nothing further was done." }
}

Set-Location $Repo
Remove-Item .git\index.lock -Force -ErrorAction SilentlyContinue

Step "Switching to dev"
git checkout dev | Out-Null; Must "git checkout dev"

# --- 1) ignore rules (idempotent) -------------------------------------------
Step "Making sure keys and backup folders are ignored"
$gi = ""
if (Test-Path .gitignore) { $gi = Get-Content .gitignore -Raw }
if ($gi -notmatch '(?m)^\*\*/service_account\.json\s*$') {
    Add-Content .gitignore "`n# Never commit service-account keys anywhere`n**/service_account.json"
    Write-Host "    added **/service_account.json"
}
if ($gi -notmatch '(?m)^\*\*/_to_delete/\s*$') {
    Add-Content .gitignore "`n# local backup folders`n**/_to_delete/"
    Write-Host "    added **/_to_delete/"
}
# if the key is still tracked in the current commit, untrack it (file stays on disk)
git rm --cached --ignore-unmatch -q -- $Secret | Out-Null

# --- 2) commit the latest work on dev -----------------------------------------
Step "Committing your latest changes on dev"
git add -A; Must "git add -A"
git diff --cached --quiet
if ($LASTEXITCODE -ne 0) {
    git commit -q -m $Message; Must "git commit"
    Write-Host "    committed: $Message"
} else {
    Write-Host "    nothing new to commit"
}

# --- 3) one-time: purge the key from ALL history ------------------------------
Step "Checking history for the service-account key"
$hits = @(git log --all --format=%H -- $Secret)
if ($hits.Count -gt 0) {
    Write-Host "    found in $($hits.Count) past commit(s) - removing it from history (file stays on disk)."
    Write-Host "    git shows a long warning and pauses ~5 s - that is normal."
    git filter-branch -f --index-filter "git rm --cached --ignore-unmatch $Secret" --prune-empty -- --all
    Must "git filter-branch"
    git for-each-ref --format="%(refname)" refs/original/ | ForEach-Object { git update-ref -d $_ }
    git reflog expire --expire=now --all
    git gc --prune=now --quiet
    $hits = @(git log --all --format=%H -- $Secret)
    if ($hits.Count -gt 0) { throw "The key is STILL in history after the rewrite. Stop here and ask for help." }
    Write-Host "    history is clean." -ForegroundColor Green
} else {
    Write-Host "    clean - no key anywhere in history."
}
if (-not (Test-Path $Secret)) {
    Write-Warning "$Secret is not on disk (it is only needed on the office PC, so this is fine)."
}

# --- 4) push dev -> main -> prod ----------------------------------------------
Step "Pushing dev"
git push origin dev; Must "git push origin dev"

Step "Merging dev into main and pushing"
git checkout main | Out-Null; Must "git checkout main"
git merge dev --no-edit; Must "git merge dev (resolve the conflict, then run this script again)"
git push origin main; Must "git push origin main"

Step "Merging main into prod and pushing"
git checkout prod | Out-Null; Must "git checkout prod"
git merge main --no-edit; Must "git merge main (resolve the conflict, then run this script again)"
git push origin prod; Must "git push origin prod"

git checkout dev | Out-Null
Write-Host ""
Write-Host "ALL PUSHED OK  (dev, main, prod are up to date on GitHub). You are back on dev." -ForegroundColor Green
