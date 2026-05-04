# scripts — POC 用

朝刊生成の**ローカル実行スクリプト**を置くフォルダ。

## 依存関係のインストール

プロジェクトルート（`【課題】土木Daily-News/`）で:

```bash
pip install -r requirements.txt
```

（仮想環境を使う場合は、先に `.venv` 等を有効化してから）

## 環境変数・API キーの置き場所

**キーを貼るのは、プロジェクト直下（`index.html` や `requirements.txt` と同じ階層）の次のどちらかだけにしてください。**

| ファイル | 用途 |
|---------|------|
| **`.env`** | 推奨。`GEMINI_API_KEY=...` を1行で記載。 |
| **`Daily-News.env`** | 別名で運用する場合。`.env` と同様。 |

- **読み込み順**: 先に `.env`、次に `Daily-News.env`。同じ変数名は **`.env` が優先**（`Daily-News.env` は上書きしない）。
- **Git**: [`.gitignore`](../.gitignore) で `.env` と `Daily-News.env` はコミット対象外です。
- **貼ってはいけない場所**: [`.env.example`](../.env.example)（テンプレのみ）、各種 `.md`、`index.html`、チャットへのキー貼り付け、公開リポジトリに載るスクリーンショット。

その他:

- **`GEMINI_API_KEY`**（必須）— [Google AI Studio](https://aistudio.google.com/apikey)
- **`GEMINI_MODEL`**（任意）— 未設定時の既定は **`gemini-2.5-flash`**（[Gemini モデル一覧](https://ai.google.dev/gemini-api/docs/models)）。`gemini-1.0-pro` など旧名は API でエラーになることがあるため、`.env` 内の `GEMINI_MODEL` が古ければ削除するか、上記の安定版に更新してください。

## `summarize_one.py`

1記事分の本文（UTF-8 テキストファイル）を渡し、[daily-news-summarize v1.1](../.claude/skills/daily-news-summarize/SKILL.md) 準拠の JSON を **標準出力**に出します。

### 実行例

プロジェクトルートで:

```bash
python scripts/summarize_one.py ^
  --url "https://www.mlit.go.jp/report/press/kanbo08_hh_001304.html" ^
  --title "令和8年度 国交省 土木工事・業務の積算基準等を改定" ^
  --body-file path/to/body.txt ^
  --date "2026-02-27" ^
  --source-name "国交省 報道発表" ^
  --section-hint "国交省・規制・政策"
```

PowerShell では行継続は **バッククォート** `` ` `` です:

```powershell
python scripts/summarize_one.py `
  --url "https://example.com/" `
  --title "見出し" `
  --body-file .\body.txt `
  --date "2026-04-27"
```

### 成功判定

- 終了コード 0
- 標準出力の JSON に `title` / `url` / `section` / `date` / `is_in_scope` / `maturity` / `lead` / `bullets` / `tags` がすべて含まれる
- `section` と `tags` が [AGENTS.md](../AGENTS.md) の許可値に収まる（`tags` はスクリプト側で許可外を除去し、0件ならエラー）

## `daily_run.py`（自動ジョブ）

毎朝のトリガー用エントリ。[design.md](../design.md) の「タスクスケジューラ」想定。

| 動作 | 説明 |
|------|------|
| 既定 | `clips/log/_job-YYYYMM.log` に **心拍ログ** 1行追記（起動できたことの記録） |
| `--ingest` | [`watchlist.txt`](watchlist.example.txt) の**先頭の処理可能行**（TAB 区切り）を1件だけ処理: HTTP で本文取得 → `summarize_one` → [`clips/log/YYYY-MM.md`](../clips/log/) に1行追記。成功した行だけ watchlist から削除（要 `GEMINI_API_KEY`） |

### watchlist の形式

1. [`watchlist.example.txt`](watchlist.example.txt) をコピーして **`scripts/watchlist.txt`** にリネーム（`watchlist.txt` は `.gitignore` 済み）。
2. 非コメント行は **TAB 区切り**: `URL` `\t` `YYYY-MM-DD` `\t` （任意）**代替タイトル**

### ラッパー（タスク登録用のパス例）

- **CMD**: プロジェクトの [`scripts/run-daily.cmd`](run-daily.cmd) を「プログラムの開始」に指定（作業フォルダは未設定でよい。バッチ内でルートに `cd`）。
- **PowerShell**: [`scripts/Run-Daily.ps1`](Run-Daily.ps1) を `powershell.exe -ExecutionPolicy Bypass -File "...\Run-Daily.ps1"` のように指定可能。

引数はそのまま `daily_run.py` に渡せます（例: `run-daily.cmd --ingest`）。

### Windows タスク スケジューラ（自動登録・推奨）

プロジェクトルートで PowerShell を開き、**1回だけ**実行します（管理者権限は不要）。

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\Install-DailyScheduledTask.ps1
```

- **既定**: 毎日 **7:00** に `fetch_rss.py` → `daily_run.py --ingest-all` → `render_html.py` を実行（[`run-daily-scheduled.ps1`](run-daily-scheduled.ps1)）。
- **時刻変更**: `-Time "06:30"` のように指定。
- **削除**: `-Uninstall`
- **Python**: プロジェクト直下に `.venv` があればその `python.exe` を優先（タスク実行時も PATH に依存しにくくするため、`python -m venv .venv` の利用を推奨）。

初回はタスク スケジューラで **「DailyNews-Doboku-Morning」** を検索し、「実行」して動作確認してください。`clips/log/_job-*.log` と `index.html` の更新日が進むことを確認します。

### 手動でタスクを作る場合（参考）

1. 「タスクの作成」→ トリガー「毎日」時刻（例 6:30）。
2. 操作「プログラムの開始」:
   - プログラム: `powershell.exe`
   - 引数: `-NoProfile -ExecutionPolicy Bypass -File "…\scripts\run-daily-scheduled.ps1"`
   - または CMD ラッパー: `C:\Windows\System32\cmd.exe` / `/c "…\scripts\run-daily.cmd"`

本文取得は [design.md](../design.md) の利用条件に従い、主に **静的 HTML が読める一次ソース**（国交省報道発表など）を想定。有料壁・JS 必須ページは失敗しうる。

## 共有モジュール

- [`project_env.py`](project_env.py) — `.env` / `Daily-News.env` の読み込み（`summarize_one.py` と共通）

## その後の POC タスク（メモ）

- 各ソースの RSS / `robots.txt`（[design.md](../design.md) 3-2）
- 差分判定・`index.html` 自動生成・Chrome `file://` のパス確認
