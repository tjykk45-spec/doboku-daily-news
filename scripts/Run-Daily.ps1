# プロジェクトルートをカレントにして daily_run.py を起動
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot
$scriptPath = Join-Path $PSScriptRoot "daily_run.py"
& python $scriptPath @args
exit $LASTEXITCODE
