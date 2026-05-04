# 土木 Daily News

毎朝 7:00 に土木・建設業界のニュースを自動収集・AI 要約して Web ページに配信する個人用ダッシュボード。

**閲覧 URL（スマホ・PC 共通）**
👉 https://tjykk45-spec.github.io/doboku-daily-news/

---

## 仕組みの概要

```
GitHub Actions（毎朝 7:00 自動起動）
  ↓
① fetch_rss.py      日経クロステック建設・日刊建設工業新聞の RSS を取得
  ↓
② daily_run.py      各記事の本文を取得 → Gemini API で JSON 要約
  ↓
③ render_html.py    clips/data/*.json → index.html を再生成
  ↓
④ git push          main ブランチに自動コミット
  ↓
GitHub Pages        index.html を公開（URL は固定）
```

---

## フォルダ構成

```
.github/workflows/
  daily.yml         # 自動実行のスケジュール設定（ここを変えると時間・頻度を変更できる）
scripts/
  fetch_rss.py      # RSS フェッチ → watchlist.txt 生成
  daily_run.py      # watchlist 全件を Gemini で要約 → clips/data/ に保存
  render_html.py    # clips/data/*.json → index.html 生成
  summarize_one.py  # 記事 1 本の要約ロジック（daily_run から呼ばれる）
  mlit_text.py      # 国交省ページの HTML 取得・本文抽出
clips/
  data/             # 記事ごとの要約 JSON（自動生成・Git 管理）
  log/              # 月次取り込みログ（自動生成・Git 管理）
  projects/         # 手動メモ（Git 管理外）
index.html          # 公開ページ本体（自動更新）
requirements.txt    # Python ライブラリ一覧
.env.example        # 環境変数のテンプレート
```

---

## 自動実行のスケジュール

| 設定 | 内容 |
|------|------|
| 頻度 | 毎日（土日含む） |
| 時刻 | 7:00 JST |
| 定義ファイル | [.github/workflows/daily.yml](.github/workflows/daily.yml) |

時間を変えたい場合は `daily.yml` の `cron:` 行を編集します。  
JST は UTC+9 なので、`7:00 JST = 22:00 UTC（前日）`= `cron: '0 22 * * *'`

手動で今すぐ実行したい場合：  
→ [Actions タブ](https://github.com/tjykk45-spec/doboku-daily-news/actions) → Daily News → **Run workflow**

---

## 初期セットアップ（参考）

### 1. API キーの登録（GitHub Secrets）

GitHub の `Settings → Secrets and variables → Actions` に以下を登録：

| Secret 名 | 内容 |
|-----------|------|
| `GEMINI_API_KEY` | Google AI Studio で取得したキー |

コードに直接書かない。`.env` ファイルはローカル専用で `.gitignore` に除外済み。

### 2. GitHub Pages の有効化

`Settings → Pages → Source: Deploy from a branch → Branch: main / (root)` で有効化。

---

## ローカルでの手動実行

```bash
# 依存ライブラリのインストール
pip install -r requirements.txt

# .env ファイルに GEMINI_API_KEY を設定
cp .env.example .env
# .env を編集して GEMINI_API_KEY=... を入力

# 実行
python scripts/fetch_rss.py
python scripts/daily_run.py --ingest-all
python scripts/render_html.py
# → index.html が更新される
```

---

## .gitignore で除外しているもの

| 除外対象 | 理由 |
|----------|------|
| `.env` | API キーが含まれるため絶対に push しない |
| `scripts/watchlist.txt` | 実行のたびに再生成される一時ファイル |
| `clips/.cache/` | 本文取得の一時キャッシュ |
| `clips/projects/` | 個人メモ（公開しない） |
| `clips/log/_job-*.log` | 実行ログ（ローカル専用） |
