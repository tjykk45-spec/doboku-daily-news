"""
1記事分の本文から Gemini で daily-news-summarize v1.1 準拠の JSON を生成する POC スクリプト。

環境変数: GEMINI_API_KEY（必須）, GEMINI_MODEL（任意、既定 gemini-2.5-flash）
読み込み順: プロジェクト直下の `.env` のあと `Daily-News.env`（同一キーは先に読んだ方が優先）
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from google import genai
from google.genai import types

from project_env import load_project_env

PROJECT_ROOT = Path(__file__).resolve().parent.parent

ALLOWED_SECTIONS = frozenset(
    {
        "国交省・規制・政策",
        "技術・トレンド",
        "資材価格・コスト",
    }
)

ALLOWED_TAGS = frozenset(
    {
        "#国交省",
        "#内閣府",
        "#地方整備局",
        "#規制",
        "#政策",
        "#i-Construction",
        "#BIM-CIM",
        "#自動運転",
        "#ドローン",
        "#DX",
        "#資材価格",
        "#鋼材",
        "#セメント",
        "#人件費",
        "#災害",
        "#発注",
        "#入札",
        "#週次深掘り",
        "#継続ウォッチ",
    }
)

MATURITY_VALUES = ("確定", "提言", "観測")

REQUIRED_KEYS = (
    "title",
    "url",
    "section",
    "date",
    "is_in_scope",
    "maturity",
    "lead",
    "bullets",
    "tags",
)


def response_json_schema() -> dict:
    tag_enum = sorted(ALLOWED_TAGS)
    return {
        "type": "object",
        "properties": {
            "title": {"type": "string", "maxLength": 90},
            "url": {"type": "string"},
            "section": {
                "type": "string",
                "enum": sorted(ALLOWED_SECTIONS),
            },
            "date": {"type": "string", "description": "YYYY-MM-DD"},
            "is_in_scope": {"type": "boolean"},
            "maturity": {"type": "string", "enum": list(MATURITY_VALUES)},
            "lead": {"type": "string"},
            "bullets": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 1,
                "maxItems": 3,
            },
            "tags": {
                "type": "array",
                "items": {"type": "string", "enum": tag_enum},
            },
        },
        "required": list(REQUIRED_KEYS),
        "additionalProperties": False,
    }


def system_instruction() -> str:
    return """あなたは土木業界ニュースを、朝刊ダッシュボード用の厳密な JSON に要約するアシスタントです。
ルール:
- 出力は JSON のみ。前後に説明やマークダウンを付けない。
- 固有名詞・数値は原文に忠実。言い換え・勝手な統一・丸めをしない。
- 原文にない断定・推測を書かない。本文が乏しいときは lead に (本文未取得のため見出しとリードのみ) を明記し、bullets は事実範囲に留める。
- lead は1段落・敬体（です・ます）。100文字前後（±20まで）。
- bullets は管理職の意思決定に効く観点で最大3件。maturity が 提言 のときは施策化の見込みまたは次に追う会議体を1つ含める。
- tags はスキーマの enum のみ使用（それ以外は出さない）。
- section は enum の3値のいずれか。迷う場合は最も近いものを選び、bullets の1つにセクション判定に自信なしと明記。
- title は90文字以内。HTML や Markdown 記号を含めない。
禁則: 装飾、感想、許可外タグ、同一内容の重複 bullet。"""


def user_prompt(
    *,
    title_raw: str,
    url: str,
    body: str,
    published_at: str,
    source_name: str,
    section_hint: str | None,
) -> str:
    hint = section_hint or "（なし）"
    return f"""以下の入力から、指定スキーマの JSON を生成してください。

title_raw: {title_raw}
url: {url}
published_at: {published_at}
source_name: {source_name}
section_hint: {hint}

body:
---
{body}
---
"""


def validate_and_normalize(
    data: object,
    *,
    canonical_url: str,
    canonical_date: str,
) -> dict:
    if not isinstance(data, dict):
        raise ValueError("ルートがオブジェクトではありません")

    missing = [k for k in REQUIRED_KEYS if k not in data]
    if missing:
        raise ValueError(f"必須キーがありません: {missing}")

    section = data["section"]
    if section not in ALLOWED_SECTIONS:
        raise ValueError(f"section が許可値外です: {section!r}")

    maturity = data["maturity"]
    if maturity not in MATURITY_VALUES:
        raise ValueError(f"maturity が許可値外です: {maturity!r}")

    bullets = data["bullets"]
    if not isinstance(bullets, list):
        raise ValueError("bullets が配列ではありません")
    cleaned_bullets: list[str] = []
    for i, b in enumerate(bullets):
        if not isinstance(b, str):
            raise ValueError(f"bullets[{i}] が文字列ではありません")
        s = b.strip()
        if s:
            cleaned_bullets.append(s)
    if not cleaned_bullets:
        raise ValueError("bullets が空です")
    if len(cleaned_bullets) > 3:
        cleaned_bullets = cleaned_bullets[:3]

    tags_raw = data["tags"]
    if not isinstance(tags_raw, list):
        raise ValueError("tags が配列ではありません")
    filtered = [t for t in tags_raw if isinstance(t, str) and t in ALLOWED_TAGS]
    if not filtered:
        raise ValueError(
            "許可タグが1件も残りませんでした（モデル出力を確認するか、AGENTS の許可リストを見直してください）"
        )

    title = data["title"]
    if not isinstance(title, str) or not title.strip():
        raise ValueError("title が空です")
    if len(title) > 90:
        raise ValueError(f"title が90文字を超えています（{len(title)} 文字）")

    lead = data["lead"]
    if not isinstance(lead, str) or not lead.strip():
        raise ValueError("lead が空です")

    is_in_scope = data["is_in_scope"]
    if not isinstance(is_in_scope, bool):
        raise ValueError("is_in_scope が真偽値ではありません")

    out = {
        "title": title.strip(),
        "url": canonical_url,
        "section": section,
        "date": canonical_date,
        "is_in_scope": is_in_scope,
        "maturity": maturity,
        "lead": lead.strip(),
        "bullets": cleaned_bullets,
        "tags": filtered,
    }
    return out


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Gemini で1記事分を daily-news-summarize v1.1 JSON に要約します。"
    )
    p.add_argument("--url", required=True, help="記事 URL（出力の url にそのまま反映）")
    p.add_argument("--title", required=True, help="記事タイトル（原文に近い形）")
    p.add_argument(
        "--body-file",
        required=True,
        type=Path,
        help="本文テキスト（UTF-8）のファイルパス",
    )
    p.add_argument(
        "--date",
        required=True,
        help="公開日 YYYY-MM-DD（published_at として渡し、出力 date にも反映）",
    )
    p.add_argument(
        "--source-name",
        default="手入力",
        help="取得元ラベル（例: 国交省 報道発表）",
    )
    p.add_argument(
        "--section-hint",
        default=None,
        help="セクション仮判定（任意）",
    )
    return p.parse_args()


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass

    args = parse_args()
    load_project_env(PROJECT_ROOT)

    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        print(
            "GEMINI_API_KEY が設定されていません。"
            "プロジェクト直下の `.env` または `Daily-News.env` に設定してください。",
            file=sys.stderr,
        )
        return 1

    model = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash").strip()

    body_path = args.body_file
    if not body_path.is_file():
        print(f"本文ファイルがありません: {body_path}", file=sys.stderr)
        return 1

    body = body_path.read_text(encoding="utf-8")

    config = types.GenerateContentConfig(
        system_instruction=system_instruction(),
        response_mime_type="application/json",
        response_json_schema=response_json_schema(),
    )

    contents = user_prompt(
        title_raw=args.title,
        url=args.url,
        body=body,
        published_at=args.date,
        source_name=args.source_name,
        section_hint=args.section_hint,
    )

    client = genai.Client(api_key=api_key)
    try:
        response = client.models.generate_content(
            model=model,
            contents=contents,
            config=config,
        )
    except Exception as e:
        print(f"Gemini API エラー: {e}", file=sys.stderr)
        return 1

    raw_text = (response.text or "").strip()
    if not raw_text:
        print("モデルから空の応答が返りました。", file=sys.stderr)
        return 1

    try:
        parsed = json.loads(raw_text)
    except json.JSONDecodeError as e:
        print(f"JSON パース失敗: {e}\n---\n{raw_text[:2000]}", file=sys.stderr)
        return 1

    try:
        normalized = validate_and_normalize(
            parsed,
            canonical_url=args.url.strip(),
            canonical_date=args.date.strip(),
        )
    except ValueError as e:
        print(f"検証エラー: {e}", file=sys.stderr)
        return 1

    print(json.dumps(normalized, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
