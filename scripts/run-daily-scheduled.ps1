# タスクスケジューラから呼ぶ朝刊フルパイプライン。
# RSS → watchlist 追記 → 全件取り込み → index.html 再生成
# 優先: プロジェクト直下 .venv\Scripts\python.exe → PATH の python

$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $ProjectRoot

function Get-PythonExe {
    $venvPy = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
    if (Test-Path -LiteralPath $venvPy) {
        return (Resolve-Path -LiteralPath $venvPy).Path
    }
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($cmd) {
        return $cmd.Source
    }
    throw 'python が見つかりません。.venv を作成するか PATH に python を通してください。'
}

$py = Get-PythonExe
$env:PYTHONUTF8 = '1'

function Invoke-DailyStep {
    param(
        [Parameter(Mandatory)][string]$RelativeScript,
        [string[]]$Arguments = @()
    )
    $scriptPath = Join-Path $ProjectRoot $RelativeScript
    # $null に代入して stdout をパイプラインに流さない。
    # 流すと $r3 が配列になり「-ne 0」が常に truthy になってしまう。
    $null = & $py $scriptPath @Arguments
    return $LASTEXITCODE
}

$r1 = Invoke-DailyStep 'scripts\fetch_rss.py'
if ($r1 -ne 0) {
    Write-Warning "fetch_rss.py が終了コード $r1 で終了しました（処理は続行します）。詳細は clips/log/_job-*.log を参照。"
}

$r2 = Invoke-DailyStep 'scripts\daily_run.py' @('--ingest-all')
if ($r2 -ne 0) {
    Write-Warning "daily_run.py が終了コード $r2 で終了しました（render は試行します）。GEMINI_API_KEY と watchlist を確認。"
}

$r3 = Invoke-DailyStep 'scripts\render_html.py'
if ($r3 -ne 0) {
    Write-Error "render_html.py が失敗しました (終了コード $r3)。"
    exit $r3
}

# index.html が更新できればジョブ成功（RSS/ingest の警告はログで確認）
exit 0
