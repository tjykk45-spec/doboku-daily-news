<#
.SYNOPSIS
  土木 Daily News の朝刊パイプラインを「毎日」実行する Windows タスクを登録／削除します。

.DESCRIPTION
  初回のみ管理者権限は不要（ログオン中の自分ユーザー向けタスク）。
  依存: pip install -r requirements.txt、プロジェクト直下に .env（GEMINI_API_KEY）

.PARAMETER Time
  毎日の開始時刻（24時間表記 HH:mm）。既定は 07:00。

.PARAMETER TaskName
  タスク スケジューラに表示される名前。既定は DailyNews-Doboku-Morning。

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\scripts\Install-DailyScheduledTask.ps1

.EXAMPLE
  .\scripts\Install-DailyScheduledTask.ps1 -Time "06:30" -Uninstall
#>

[CmdletBinding()]
param(
    [string]$Time = '07:00',
    [string]$TaskName = 'DailyNews-Doboku-Morning',
    [switch]$Uninstall,
    [switch]$WhatIf
)

$runnerPath = Join-Path $PSScriptRoot 'run-daily-scheduled.ps1'
if (-not (Test-Path -LiteralPath $runnerPath)) {
    throw "見つかりません: $runnerPath"
}

$psExe = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
if (-not (Test-Path -LiteralPath $psExe)) {
    throw "powershell.exe が見つかりません: $psExe"
}

$argLine = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$runnerPath`""

if ($Uninstall) {
    $existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if (-not $existing) {
        Write-Host "タスクは未登録です: $TaskName"
        exit 0
    }
    if ($WhatIf) {
        Write-Host "[WhatIf] 削除: $TaskName"
        exit 0
    }
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "削除しました: $TaskName"
    exit 0
}

# 時刻パース（ローカル）
try {
    $today = Get-Date
    $parts = $Time -split ':'
    $hour = [int]$parts[0]
    $minute = [int]$parts[1]
    $startAt = Get-Date -Hour $hour -Minute $minute -Second 0
}
catch {
    throw "時刻の形式が不正です。例: -Time `"07:00`" ($_)"
}

if ($WhatIf) {
    Write-Host "[WhatIf] 登録: $TaskName 毎日 $Time"
    Write-Host "[WhatIf] 実行: $psExe $argLine"
    exit 0
}

$action = New-ScheduledTaskAction -Execute $psExe -Argument $argLine
$trigger = New-ScheduledTaskTrigger -Daily -At $startAt

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2)

$principal = New-ScheduledTaskPrincipal `
    -UserId "$env:USERDOMAIN\$env:USERNAME" `
    -LogonType Interactive `
    -RunLevel Limited

$desc = 'Doboku Daily News: fetch_rss, daily_run --ingest-all, render_html (run-daily-scheduled.ps1)'

$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "既存タスクを置き換えます: $TaskName"
}

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Description $desc | Out-Null

Write-Host "登録しました: タスク名=$TaskName / 毎日 $Time / 実行ファイル=$runnerPath"
Write-Host "確認: タスク スケジューラで「$TaskName」を検索し、必要なら「右クリック → 実行」でテストしてください。"
exit 0
