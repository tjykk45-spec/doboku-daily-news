@echo off
REM 朝刊フルパイプライン: RSS取得 → 全件要約 → index.html 生成
REM タスクスケジューラの「プログラムの開始」にこのバッチのフルパスを指定する。
cd /d "%~dp0.."
python "scripts\fetch_rss.py"
python "scripts\daily_run.py" --ingest-all
python "scripts\render_html.py"
exit /b %ERRORLEVEL%
