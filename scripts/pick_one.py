"""
直近 WINDOW_DAYS 日分の記事から Gemini で「今日の一言」を1本選定し、
clips/data/_lead_story.json に保存する。

render_html.py がこのファイルを読んで DAILY-NEWS:KOTOBA マーカー間を更新する。

使い方:
    python scripts/pick_one.py [--window-days N] [--dry-run]

環境変数: GEMINI_API_KEY（必須）, GEMINI_MODEL（任意、既定 gemini-2.5-flash）
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

from google import genai
from google.genai import types

from project_env import load_project_env

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "clips" / "data"
LEAD_STORY_FILE = DATA_DIR / "_lead_story.json"

_DEFAULT_WINDOW = 7   # 直近何日分の記事を候補にするか


# ---------------------------------------------------------------------------
# ジョブログ
# ---------------------------------------------------------------------------

def _append_job_log(message: str) -> None:
    today = date.today()
    p = PROJECT_ROOT / "clips" / "log" / f"_job-{today.year:04d}{today.month:02d}.log"
    p.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with p.open("a", encoding="utf-8") as f:
        f.write(f"- {now} | {message}\n")


# ---------------------------------------------------------------------------
# 記事の読み込み
# ---------------------------------------------------------------------------

def load_candidate_articles(window_days: int) -> list[dict]:
    """
    clips/data/*.json から直近 window_days 日分を読み込む。
    _lead_story.json 自体は除外する。URL 重複排除・日付降順。
    """
    if not DATA_DIR.is_dir():
        return []
    cutoff = date.today() - timedelta(days=window_days)
    seen_urls: set[str] = set()
    articles: list[dict] = []
    for p in sorted(DATA_DIR.glob("*.json"), reverse=True):
        if p.name.startswith("_"):
            continue  # _lead_story.json など管理ファイルを除外
        try:
            art = json.loads(p.read_text(encoding="utf-8"))
            art_date = date.fromisoformat(art.get("date", "1900-01-01"))
            if art_date < cutoff:
                continue
            url = art.get("url", "")
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            articles.append(art)
        except Exception:
            continue
    articles.sort(key=lambda a: a.get("date", ""), reverse=True)
    return articles


# ---------------------------------------------------------------------------
# Gemini 呼び出し
# ---------------------------------------------------------------------------

def _response_json_schema() -> dict:
    return {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "選んだ記事の URL（候補リストから必ず1つ選ぶ）",
            },
            "reason": {
                "type": "string",
                "description": "選定理由（50文字以内・日本語）",
            },
        },
        "required": ["url", "reason"],
        "additionalProperties": False,
    }


def _system_instruction() -> str:
    return """あなたは土木建設業の専門紙エディターです。
提示された記事リストの中から、土木建設業の管理職が
明日の意思決定・行動に最も直結する1本を選んでください。

選定基準（優先順位）:
1. maturity=確定 の記事（施行・適用が決まっているもの）を最優先
2. is_in_scope=true の記事（土木中心スコープ）を優先
3. 国交省・規制・政策 セクションの記事を優先
4. 影響範囲が全国・業界横断の記事を優先

出力は JSON のみ。説明や前置きは不要です。
候補リストにない URL は選ばないでください。"""


def _build_user_prompt(articles: list[dict]) -> str:
    lines = ["以下の記事リストから1本選んでください。\n"]
    for i, art in enumerate(articles, 1):
        lines.append(
            f"[{i}] url: {art.get('url', '')}\n"
            f"    title: {art.get('title', '')}\n"
            f"    section: {art.get('section', '')} / "
            f"maturity: {art.get('maturity', '')} / "
            f"is_in_scope: {art.get('is_in_scope', True)}\n"
            f"    lead: {art.get('lead', '')[:80]}\n"
        )
    return "\n".join(lines)


def pick_with_gemini(
    articles: list[dict], *, api_key: str, model: str
) -> dict | None:
    """
    Gemini で最重要記事を1本選ぶ。
    成功: {"url": "...", "reason": "..."} を返す。
    失敗: None を返す（呼び出し元でフォールバック）。
    """
    config = types.GenerateContentConfig(
        system_instruction=_system_instruction(),
        response_mime_type="application/json",
        response_json_schema=_response_json_schema(),
    )
    contents = _build_user_prompt(articles)
    client = genai.Client(api_key=api_key)
    try:
        response = client.models.generate_content(
            model=model,
            contents=contents,
            config=config,
        )
    except Exception as e:
        print(f"  [ERR] Gemini API エラー: {e}", file=sys.stderr)
        return None

    raw = (response.text or "").strip()
    if not raw:
        print("  [ERR] Gemini から空の応答", file=sys.stderr)
        return None

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"  [ERR] JSON パース失敗: {e}", file=sys.stderr)
        return None

    url = parsed.get("url", "")
    reason = parsed.get("reason", "")
    if not url:
        print("  [ERR] url フィールドが空", file=sys.stderr)
        return None

    # 候補リストにある URL かチェック
    candidate_urls = {art.get("url", "") for art in articles}
    if url not in candidate_urls:
        print(f"  [WARN] Gemini が候補外の URL を返しました: {url}", file=sys.stderr)
        return None

    return {"url": url, "reason": reason}


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass

    ap = argparse.ArgumentParser(description="今日の一言を Gemini で選定します。")
    ap.add_argument(
        "--window-days",
        type=int,
        default=_DEFAULT_WINDOW,
        dest="window_days",
        help=f"候補にする日数（既定: {_DEFAULT_WINDOW}）",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="ファイルへの書き込みを行わず結果だけ表示する",
    )
    args = ap.parse_args()

    load_project_env(PROJECT_ROOT)

    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        print(
            "GEMINI_API_KEY が設定されていません。"
            "プロジェクト直下の `.env` または `Daily-News.env` に設定してください。",
            file=sys.stderr,
        )
        _append_job_log("pick_one: GEMINI_API_KEY 未設定 → スキップ")
        return 0  # pipeline を止めない

    model = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash").strip()

    print(f"[pick_one] 候補記事を読み込み中（直近{args.window_days}日）...", flush=True)
    articles = load_candidate_articles(args.window_days)

    if not articles:
        msg = "pick_one: 候補記事が0件 → スキップ"
        print(f"  -> {msg}")
        _append_job_log(msg)
        return 0

    print(f"  -> 候補: {len(articles)}件")

    print(f"[pick_one] Gemini ({model}) に選定を依頼中...", flush=True)
    result = pick_with_gemini(articles, api_key=api_key, model=model)

    if result is None:
        msg = "pick_one: Gemini 選定失敗 → スキップ（前日の一言を維持）"
        print(f"  -> {msg}")
        _append_job_log(msg)
        return 0

    output = {
        "url": result["url"],
        "reason": result["reason"],
        "picked_at": date.today().isoformat(),
    }

    if args.dry_run:
        print(f"[dry-run] 選定結果: {json.dumps(output, ensure_ascii=False, indent=2)}")
        return 0

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    LEAD_STORY_FILE.write_text(
        json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    msg = (
        f"pick_one: 選定完了 → {result['url'][:60]} "
        f"| 理由: {result['reason'][:30]}"
    )
    print(f"  -> {msg}")
    _append_job_log(msg)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
