# reference/ — デザインプレビュー

## ファイル

| ファイル | 用途 |
|---|---|
| `design-preview.html` | **Claude Design で編集するメインファイル。** 全CSS + サンプル記事カード入り。 |

## デザイン変更の手順

1. `reference/design-preview.html` を Claude Design で開く
2. 色・フォント・余白などを視覚的に編集する
3. 保存後、このリポジトリのルートで以下を実行:
   ```
   python scripts/apply_design.py
   ```
4. `index.html` の `<style>` ブロックが自動更新される
5. commit & push → GitHub Pages に反映

## 注意

- `design-preview.html` 内の `<style>...</style>` ブロック全体が `index.html` に上書きコピーされます
- CSS を追加・削除した場合も正しく反映されます
- サンプルカードの HTML 部分（`<body>` 内）は `index.html` には反映されません。CSS のみが対象です
- GitHub Actions は毎朝 7:00 JST に `apply_design.py` を自動実行します（`design-preview.html` を編集して push するだけで翌朝反映）
