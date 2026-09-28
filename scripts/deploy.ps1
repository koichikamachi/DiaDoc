# DiaDoc を Cloud Run に公開する（手動公開を1本にまとめたもの）
#
# 使い方（プロジェクトのフォルダで）：
#   powershell -ExecutionPolicy Bypass -File scripts\deploy.ps1
#
# 流れ：
#   1. 変更し忘れがないか（コミットしていないコードの変更があれば止まる）
#   2. GitHub に送っていないコミットがあれば、送るかを聞く
#   3. 同梱データのファイル名が英数字だけか（日本語名は Cloud Run が読み込めない）
#   4. コミット済みの内容だけを別フォルダに取り出す（手元の .env や試した跡は入らない）
#   5. 取り出した内容でテスト（-SkipTests で省略できる）。公開するものそのものを試験する
#   6. gcloud run deploy
#   7. 取り出したフォルダを片付け、公開 URL と公開したコミットを表示する
#
# どこかで問題が見つかれば、その場で止まって理由を表示する。公開中の版はそのまま残る。

param(
    [switch]$SkipTests,
    [switch]$Yes,                                   # 確認の問いに、すべて「はい」で答える
    [string]$Service = "diadoc",
    [string]$Region = "asia-northeast1",
    [string]$Model = "gemini-3.8-flash"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$WorkTree = Join-Path (Split-Path -Parent $Root) "diadoc-deploy"

function Step($n, $text) { Write-Host ""; Write-Host "[$n/7] $text" -ForegroundColor Cyan }
$script:Extracted = $false
function Fail($text) {
    Write-Host ""; Write-Host "中止：$text" -ForegroundColor Red
    if ($script:Extracted) { Set-Location $Root; QuietGit worktree remove --force $WorkTree; QuietGit worktree prune }
    Write-Host "公開中の版は変わっていません。"; exit 1
}
function Ok($text) { Write-Host "  OK  $text" -ForegroundColor Green }
function Ask($text) {
    if ($Yes) { return $true }
    $a = Read-Host "$text (y/N)"
    return ($a -eq "y" -or $a -eq "Y")
}
$GitExe = (Get-Command git -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1).Source
function QuietGit {
    # 失敗してもよい git（片付けなど）。Windows PowerShell 5.1 で 2>$null が中止扱いにならないよう、止めずに流す
    $old = $ErrorActionPreference; $ErrorActionPreference = "Continue"
    try { & $GitExe -C $Root @args 2>&1 | Out-Null } finally { $ErrorActionPreference = $old }
}
function RunGit { & $GitExe -C $Root @args; if ($LASTEXITCODE -ne 0) { Fail "git $($args -join ' ') が失敗しました" } }

Set-Location $Root
if (-not $GitExe) { Fail "git が見つかりません" }
if (-not (Get-Command gcloud -ErrorAction SilentlyContinue)) { Fail "gcloud が見つかりません（Google Cloud SDK を入れてください）" }

# --- 1. コミットしていない変更 ---------------------------------------------------
Step 1 "コミットしていない変更がないか"
# data/ の中の変更は、画面で試したときの跡なので公開には関係しない（取り出すのはコミット済みの内容だけ）
$dirty = @(RunGit -c core.quotepath=false status --porcelain --untracked-files=no | Where-Object { $_ -notmatch '^.. data/' })
if ($dirty.Count -gt 0) {
    Write-Host "  コミットしていない変更があります（このままでは公開されません）："
    $dirty | ForEach-Object { Write-Host "    $_" }
    Fail "先にコミットしてください（公開したくない変更なら、元に戻してください）"
}
$Commit = (RunGit log -1 --format="%h %s")
Ok "公開するコミット：$Commit"

# --- 2. GitHub に送っていないコミット ---------------------------------------------
Step 2 "GitHub に送っていないコミットがないか"
RunGit fetch --quiet origin
$ahead = [int](RunGit rev-list --count "origin/main..HEAD")
if ($ahead -gt 0) {
    Write-Host "  GitHub に送っていないコミットが $ahead 件あります。"
    if (Ask "  いま git push しますか？") {
        RunGit push origin HEAD:main
        Ok "送りました"
    } else {
        Write-Host "  送らずに進みます（公開はできますが、GitHub の内容と公開版がずれます）" -ForegroundColor Yellow
    }
} else {
    Ok "GitHub と同じです"
}

# --- 3. ファイル名 --------------------------------------------------------------
Step 3 "同梱するファイルの名前が英数字だけか"
$bad = @(RunGit -c core.quotepath=false ls-files data src .streamlit | Where-Object { $_ -match '[^\x20-\x7e]' })
if ($bad.Count -gt 0) {
    Write-Host "  英数字以外の名前のファイル："
    $bad | ForEach-Object { Write-Host "    $_" }
    Fail "Cloud Run は日本語などのファイル名を含むイメージを読み込めません。ファイル名を英数字にし、表示名は同じフォルダの titles.json に書いてください"
}
Ok "問題なし"

# --- 4. コミット済みの内容を取り出す ------------------------------------------------
Step 4 "コミット済みの内容を取り出す（$WorkTree）"
if (Test-Path $WorkTree) {
    QuietGit worktree remove --force $WorkTree
    if (Test-Path $WorkTree) { Fail "前回の取り出し先 $WorkTree を片付けられません。手で消してから、やり直してください" }
}
RunGit worktree prune
RunGit worktree add --detach $WorkTree HEAD
$script:Extracted = $true
Ok "取り出しました"

# --- 5. テスト（取り出した内容で。手元の data/ に残った試した跡に左右されない） ------------------------------------------------------------------
Step 5 "テスト（取り出した内容で）"
if ($SkipTests) {
    Write-Host "  -SkipTests が指定されたので省略します" -ForegroundColor Yellow
} else {
    $py = $null
    foreach ($c in @("python", "py")) { if (Get-Command $c -ErrorAction SilentlyContinue) { $py = $c; break } }
    if (-not $py) { Fail "python が見つかりません（テストを省くなら -SkipTests を付けてください）" }
    Push-Location $WorkTree
    try { & $py -m pytest -q -p no:cacheprovider; $passed = ($LASTEXITCODE -eq 0) } finally { Pop-Location }
    if (-not $passed) { Fail "テストが通りませんでした" }
    Ok "テストが通りました"
}

# --- 6. デプロイ ----------------------------------------------------------------
Step 6 "Cloud Run に公開する（ビルドに数分かかります）"
$deployArgs = @(
    "run", "deploy", $Service,
    "--source", ".",
    "--region", $Region,
    "--execution-environment", "gen2",
    "--allow-unauthenticated",
    "--set-secrets", "GEMINI_API_KEY=gemini-api-key:latest",
    "--set-env-vars", "GEMINI_MODEL=$Model",
    "--max-instances", "1",
    "--concurrency", "20",
    "--session-affinity",
    "--memory", "2Gi",
    "--timeout", "3600",
    "--quiet"
)
Push-Location $WorkTree
try {
    & gcloud @deployArgs
    $deployed = ($LASTEXITCODE -eq 0)
} finally {
    Pop-Location
}

# --- 7. 片付けと結果 --------------------------------------------------------------
Step 7 "片付け"
QuietGit worktree remove --force $WorkTree
QuietGit worktree prune
if (-not $deployed) { Fail "gcloud run deploy が失敗しました（上の表示を確かめてください）" }
$url = (& gcloud run services describe $Service --region $Region --format "value(status.url)")
Write-Host ""
Write-Host "公開しました" -ForegroundColor Green
Write-Host "  URL      ：$url"
Write-Host "  コミット ：$Commit"
Write-Host "  確かめる ：URL を開き、サイドバーに「公開デモ」の表示が出ていること、C002 で「1手進める」が動くこと"
