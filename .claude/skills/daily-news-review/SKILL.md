---
name: daily-news-review
description: daily-news-summarize が出力したJSONを再度Geminiに投げてレビューするサブエージェント用スキル。事実ねじれ・情報不足・紙面密度の観点でチェックし、修正提案JSONを返す。
---

# 目的

[daily-news-summarize](../daily-news-summarize/SKILL.md) が出したJSONを**第2のGeminiプロンプト**で再レビューする。講義2の「サブエージェントに磨かせる」を具現化する役割。

---

## 入力

- `summary_json`: `daily-news-summarize` が返したJSON
- `body` または `lead_raw`: 元の本文またはリード
- `source_name`: 取得元
- `url`: 記事URL

## 出力（厳守）

```json
{
  "verdict": "ok | revise | reject",
  "issues": [
    {
      "field": "title | lead | bullets | tags | section",
      "severity": "high | medium | low",
      "reason": "string (具体的に何が問題か)"
    }
  ],
  "suggested_patch": {
    "title": "string or null",
    "lead": "string or null",
    "bullets": ["string", ...] ,
    "tags": ["string", ...],
    "section": "string or null",
    "is_in_scope": "boolean or null",
    "maturity": "string or null"
  }
}
```

- **ok**: そのまま通してよい。
- **revise**: 修正すれば通せる。`suggested_patch` に**変更するフィールドだけ**値を入れる（変えない箇所は `null` または空配列）。
- **reject**: 朝刊に載せるべきでない（本文欠落がひどい／規約違反の疑い／重要度が低すぎるなど）。

---

## レビュー観点（チェックリスト）

### 1. 事実ねじれ
- `title` / `lead` が原文の事実関係を変えていないか
- 数字が原文と一致しているか（丸め・誇張なし）
- 固有名詞が改変されていないか
- **原文にない情報**を補足で入れていないか

### 2. 情報源の明示
- `url` が入力と一致しているか
- 本文が取れていない場合、`lead` に明示（「本文未取得のため…」）があるか

### 3. 紙面密度
- `lead` が100文字前後に収まっているか（極端に短くない／長くない）
- `bullets` が **1〜3件** の範囲か
- `bullets` の内容が重複していないか
- `bullets` が読者（土木業界の管理職）にとって**意思決定に使える観点**になっているか

### 4. スキーマ準拠
- `section` が定義値（`国交省・規制・政策` / `技術・トレンド` / `資材価格・コスト`）内か
- `tags` が [AGENTS.md の許可タグリスト](../../../AGENTS.md#5-許可タグリスト) 内か
- `date` が `YYYY-MM-DD` 形式か
- `is_in_scope` が `true`/`false` で入っており、判定理由が lead か bullets から読み取れるか
- `maturity` が `確定` / `提言` / `観測` のいずれかか
- `maturity: 提言` の場合、bullets に「施策化の見込み」または「次に追うべき会議体」のヒントが入っているか
### 6. 発表日・本文薄い記事の処理確認
- `published_at` が取得日代替の場合、`lead` に
  `（発表日不明のため取得日で代替）` の明記があるか
- `body_length` が300文字未満の場合：
  - `bullets` が1件以内に絞られているか
  - bullets に `（詳細は別添PDF参照）` の明記があるか
  - `lead` に推測・補足が混入していないか


### 5. 朝刊適性
- 同じ話題を過去N日に何度も見た印象があるか（※ただし重複判定そのものはコード側。ここは「文面上の新鮮味」だけを見る）
- 管理職が朝3分で読む紙面として、**情報密度と読みやすさ**のバランスが取れているか

---

## 判定の目安

- 事実ねじれ or スキーマ違反が1つでもあれば少なくとも `revise`
- 本文未取得なのに断定的な要約 → `revise` または `reject`
- 規約違反の疑い（有料本文の転記など）→ `reject`
- それ以外で軽微なら `ok`

---

## 禁則

- `suggested_patch` で**原文にない情報を捏造しない**。
- `verdict: reject` を多用しない（朝刊が空になる）。迷ったら `revise`。
- 自分で修正するのではなく、コード側が適用できるように**差分だけ**を返す。
- JSON以外の説明文を付けない。

---

## フロー上の位置

```
daily-news-summarize → (このスキル) → [コード] verdict で分岐
                                          ok     → そのまま採用
                                          revise → patch を適用して再バリデーション
                                          reject → 今日の紙面から外し log にだけ残す
```
