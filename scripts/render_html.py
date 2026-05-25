"""
clips/data/YYYY-MM-DD_*.json から直近 WINDOW_DAYS 日分の記事を読み込み、
index.html の DAILY-NEWS マーカー間を自動更新する。

マーカー:
  <!-- DAILY-NEWS:MASTHEAD:START --> ... <!-- DAILY-NEWS:MASTHEAD:END -->
  <!-- DAILY-NEWS:SECTIONS:START --> ... <!-- DAILY-NEWS:SECTIONS:END -->
"""

from __future__ import annotations

import json
import re
import sys
from datetime import date, datetime, timedelta
from html import escape
from pathlib import Path
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "clips" / "data"
LEAD_STORY_FILE = DATA_DIR / "_lead_story.json"
INDEX_HTML = PROJECT_ROOT / "index.html"

WINDOW_DAYS = 5
NEW_DAYS = 1  # 直近 1 日以内の記事に NEW バッジを表示

SECTION_ORDER = ["国交省・規制・政策", "技術・トレンド", "資材価格・コスト"]

_SECTION_ID = {
    "国交省・規制・政策": "sec-policy",
    "技術・トレンド": "sec-tech",
    "資材価格・コスト": "sec-cost",
}

_SECTION_THEME = {
    "国交省・規制・政策": "green",
    "技術・トレンド": "main",
    "資材価格・コスト": "pink",
}

_SECTION_CFG = {
    "国交省・規制・政策": {
        "num": "SEC.02",
        "h2": "国交省・規制・政策動向",
        "meta": "Policy",
        "cat": "Policy",
        "sub": None,
    },
    "技術・トレンド": {
        "num": "SEC.03",
        "h2": "技術・トレンド",
        "meta": "Tech",
        "cat": "Tech",
        "sub": (
            "<strong>建築・土木共通</strong>で追うトピック"
            "（i-Construction、現場の自動運転・自律機械、BIM/CIM など）をここにまとめます。"
        ),
    },
    "資材価格・コスト": {
        "num": "SEC.04",
        "h2": "資材価格・コスト動向",
        "meta": "Cost",
        "cat": "Cost",
        "sub": None,
    },
}

_JA_WEEKDAYS = ["月", "火", "水", "木", "金", "土", "日"]

_SVG_EXTERNAL = (
    '<svg width="13" height="13" viewBox="0 0 24 24" fill="none"'
    ' stroke="currentColor" stroke-width="2.4" stroke-linecap="round"'
    ' stroke-linejoin="round"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0'
    ' 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/>'
    '<line x1="10" y1="14" x2="21" y2="3"/></svg>'
)
_SVG_COPY = (
    '<svg width="13" height="13" viewBox="0 0 24 24" fill="none"'
    ' stroke="currentColor" stroke-width="2.4" stroke-linecap="round"'
    ' stroke-linejoin="round"><rect x="9" y="9" width="13" height="13"'
    ' rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9'
    'a2 2 0 0 1 2 2v1"/></svg>'
)
_SVG_MAIL = (
    '<svg width="13" height="13" viewBox="0 0 24 24" fill="none"'
    ' stroke="currentColor" stroke-width="2.4" stroke-linecap="round"'
    ' stroke-linejoin="round"><rect x="2" y="4" width="20" height="16"'
    ' rx="2"/><polyline points="2,4 12,13 22,4"/></svg>'
)


# ---------------------------------------------------------------------------
# データ読み込み
# ---------------------------------------------------------------------------

def load_recent_articles() -> list[dict]:
    """clips/data/*.json から直近 WINDOW_DAYS 日分を読み込む（URL重複排除・日付降順）。"""
    if not DATA_DIR.is_dir():
        return []
    cutoff = date.today() - timedelta(days=WINDOW_DAYS)
    seen_urls: set[str] = set()
    articles: list[dict] = []
    for p in sorted(DATA_DIR.glob("*.json"), reverse=True):
        if p.name.startswith("_"):
            continue  # _lead_story.json などの管理ファイルを除外
        try:
            art = json.loads(p.read_text(encoding="utf-8"))
            art_date = date.fromisoformat(art.get("date", "1900-01-01"))
            if art_date < cutoff:
                continue
            url = art.get("url", "")
            if url in seen_urls:
                continue
            seen_urls.add(url)
            articles.append(art)
        except Exception:
            continue
    articles.sort(key=lambda a: a.get("date", ""), reverse=True)
    return articles


# ---------------------------------------------------------------------------
# HTML 生成
# ---------------------------------------------------------------------------

def _e(s: str) -> str:
    return escape(str(s), quote=True)


def _t(s: str) -> str:
    return escape(str(s))


def _bullets_attr(bullets: list) -> str:
    return "|".join(b.replace("|", "｜") for b in bullets if b)


def _render_card(art: dict, cat: str) -> str:
    title = art.get("title", "")
    url = art.get("url", "#")
    section = art.get("section", "")
    art_date = art.get("date", "")
    lead = art.get("lead", "")
    bullets: list[str] = art.get("bullets", [])
    tags: list[str] = art.get("tags", [])
    maturity = art.get("maturity", "")
    is_in_scope = art.get("is_in_scope", True)
    source_name = art.get("source_name", "自動取得")

    date_display = art_date.replace("-", ".") if art_date else ""

    # NEW バッジ（直近 NEW_DAYS 日以内）
    try:
        art_date_obj = date.fromisoformat(art_date) if art_date else None
    except ValueError:
        art_date_obj = None
    is_new = bool(art_date_obj and (date.today() - art_date_obj).days <= NEW_DAYS)
    new_html = ' <span class="badge-new">NEW</span>' if is_new else ""

    # maturity バッジ
    maturity_html = (
        f' <span class="badge-maturity" data-maturity="{_e(maturity)}">{_t(maturity)}</span>'
        if maturity else ""
    )
    # スコープ外バッジ
    scope_html = (
        ' <span class="badge-scope-out">スコープ外参考</span>'
        if not is_in_scope else ""
    )

    # bullets → details
    bullets_html = ""
    if bullets:
        items_html = "".join(f"<li>{_t(b)}</li>" for b in bullets)
        bullets_html = (
            f'\n        <details class="dive">\n'
            f'          <summary>深掘り</summary>\n'
            f'          <div class="body"><ul>{items_html}</ul></div>\n'
            f'        </details>'
        )

    # タグ
    tags_html = "".join(f'<span class="tag">{_t(tg)}</span>' for tg in tags)
    tags_line = f'\n        <div class="tags">{tags_html}</div>' if tags_html else ""

    return (
        f'\n      <article\n'
        f'        class="card news-clip"\n'
        f'        data-clip-title="{_e(title)}"\n'
        f'        data-clip-url="{_e(url)}"\n'
        f'        data-clip-section="{_e(section)}"\n'
        f'        data-clip-date="{_e(art_date)}"\n'
        f'        data-clip-lead="{_e(lead)}"\n'
        f'        data-clip-bullets="{_e(_bullets_attr(bullets))}"\n'
        f'      >\n'
        f'        <div class="kicker">\n'
        f'          <span class="cat">{_t(cat)}</span>\n'
        f'          <span>·</span>\n'
        f'          <span class="date">{_t(date_display)}</span>'
        f'{new_html}{maturity_html}{scope_html}\n'
        f'        </div>\n'
        f'        <h3>{_t(title)}</h3>\n'
        f'        <p class="lead">{_t(lead)}</p>'
        f'{bullets_html}'
        f'{tags_line}\n'
        f'        <div class="source-line">{_t(source_name)} ／ {_t(art_date)}</div>\n'
        f'        <div class="actions">\n'
        f'          <a href="{_e(url)}" target="_blank" rel="noopener noreferrer"'
        f' class="btn btn-primary">\n'
        f'            {_SVG_EXTERNAL}\n'
        f'            ソースを開く\n'
        f'          </a>\n'
        f'          <button type="button" class="btn btn-ghost js-copy-clip">\n'
        f'            {_SVG_COPY}\n'
        f'            後追い用にコピー\n'
        f'          </button>\n'
        f'          <button type="button" class="btn btn-mail js-mail-clip">\n'
        f'            {_SVG_MAIL}\n'
        f'            深掘り予約\n'
        f'          </button>\n'
        f'        </div>\n'
        f'      </article>'
    )


def _render_section(section_key: str, articles: list[dict]) -> str:
    cfg = _SECTION_CFG[section_key]
    count = len(articles)
    sub_html = (
        f'\n      <p class="sec-sub">{cfg["sub"]}</p>'
        if cfg["sub"] else ""
    )
    if articles:
        cards_html = "".join(_render_card(a, cfg["cat"]) for a in articles)
    else:
        cards_html = '\n      <p class="sec-empty">本日は該当記事がありません。</p>'

    sec_id = _SECTION_ID.get(section_key, "")
    id_attr = f' id="{sec_id}"' if sec_id else ""
    theme = _SECTION_THEME.get(section_key, "")
    theme_attr = f' data-theme="{theme}"' if theme else ""
    return (
        f'\n    <section class="sec"{id_attr}{theme_attr}>\n'
        f'      <div class="sec-head">\n'
        f'        <div class="label">\n'
        f'          <span class="num">{cfg["num"]}</span>\n'
        f'          <h2>{cfg["h2"]}</h2>\n'
        f'        </div>\n'
        f'        <span class="meta">{cfg["meta"]} ／ {count} 件</span>\n'
        f'      </div>{sub_html}\n'
        f'{cards_html}\n'
        f'    </section>'
    )


def generate_sections_html(articles: list[dict]) -> str:
    grouped: dict[str, list[dict]] = {k: [] for k in SECTION_ORDER}
    for art in articles:
        sec = art.get("section", "")
        if sec in grouped:
            grouped[sec].append(art)
    return "\n".join(_render_section(k, grouped[k]) for k in SECTION_ORDER)


# ---------------------------------------------------------------------------
# 今日の一言（KOTOBA）関連
# ---------------------------------------------------------------------------

def load_lead_story_article(all_articles: list[dict]) -> dict | None:
    """
    _lead_story.json の URL に一致する記事を all_articles から探して返す。
    ファイルがない・URLが見つからない場合は None。
    """
    if not LEAD_STORY_FILE.is_file():
        return None
    try:
        lead = json.loads(LEAD_STORY_FILE.read_text(encoding="utf-8"))
        target_url = lead.get("url", "")
    except Exception:
        return None
    if not target_url:
        return None
    for art in all_articles:
        if art.get("url", "") == target_url:
            return art
    return None


def _render_lead_story(art: dict) -> str:
    """lead-story div の HTML を生成する。"""
    title = art.get("title", "")
    url = art.get("url", "#")
    art_date = art.get("date", "")
    lead = art.get("lead", "")
    bullets: list[str] = art.get("bullets", [])
    tags: list[str] = art.get("tags", [])
    source_name = art.get("source_name", "自動取得")

    bullets_attr = "|".join(b.replace("|", "｜") for b in bullets if b)
    tags_html = "".join(
        f'      <span class="tag">{_t(tg)}</span>\n' for tg in tags
    )
    bullets_li = "".join(f"<li>{_t(b)}</li>" for b in bullets if b)
    bullets_html = (
        f'    <details class="dive">\n'
        f'      <summary>深掘り・論点</summary>\n'
        f'      <div class="body"><ul>{bullets_li}</ul></div>\n'
        f'    </details>\n'
    ) if bullets_li else ""

    return (
        f'    <!-- DAILY-NEWS:KOTOBA:START -->\n'
        f'    <div\n'
        f'      class="lead-story news-clip"\n'
        f'      data-clip-title="{_e(title)}"\n'
        f'      data-clip-url="{_e(url)}"\n'
        f'      data-clip-section="今日の一言"\n'
        f'      data-clip-date="{_e(art_date)}"\n'
        f'      data-clip-lead="{_e(lead)}"\n'
        f'      data-clip-bullets="{_e(bullets_attr)}"\n'
        f'    >\n'
        f'      <div class="lead-story-kicker">Lead Story ／ 今日の一言</div>\n'
        f'      <h2>{_t(title)}</h2>\n'
        f'      <p class="lead">{_t(lead)}</p>\n'
        f'      <div class="lead-story-tags">\n'
        f'{tags_html}'
        f'      </div>\n'
        f'{bullets_html}'
        f'      <div class="source-line">{_t(source_name)} ／ {_t(art_date)}</div>\n'
        f'      <div class="actions">\n'
        f'        <a href="{_e(url)}" target="_blank" rel="noopener noreferrer"'
        f' class="btn btn-primary">\n'
        f'          {_SVG_EXTERNAL}\n'
        f'          ソースを開く\n'
        f'        </a>\n'
        f'        <button type="button" class="btn btn-ghost js-copy-clip">\n'
        f'          {_SVG_COPY}\n'
        f'          後追い用にコピー\n'
        f'        </button>\n'
        f'        <button type="button" class="btn btn-mail js-mail-clip">\n'
        f'          {_SVG_MAIL}\n'
        f'          深掘り予約\n'
        f'        </button>\n'
        f'      </div>\n'
        f'    </div>\n'
        f'    <!-- DAILY-NEWS:KOTOBA:END -->'
    )


# ---------------------------------------------------------------------------
# index.html 更新
# ---------------------------------------------------------------------------

def _masthead_html(today: date, total: int, now_jst: str) -> str:
    weekday = _JA_WEEKDAYS[today.weekday()]
    date_str = f"{today.year}年{today.month}月{today.day}日（{weekday}）"
    return (
        f'<!-- DAILY-NEWS:MASTHEAD:START -->\n'
        f'        <time datetime="{today.isoformat()}">{date_str}</time>\n'
        f'        <span class="sep">·</span>\n'
        f'        <span class="pill">本日のピックアップ <strong>{total}</strong> 件</span>\n'
        f'        <span class="sep">·</span>\n'
        f'        <span class="last-updated">最終更新: {now_jst}</span>\n'
        f'        <!-- DAILY-NEWS:MASTHEAD:END -->'
    )


def update_index_html(articles: list[dict], now_jst: str) -> None:
    today = date.today()
    html = INDEX_HTML.read_text(encoding="utf-8")

    # title タグ更新（ブラウザタブに今日の日付を表示）
    weekday = _JA_WEEKDAYS[today.weekday()]
    title_str = f"土木 Daily News｜{today.month}月{today.day}日（{weekday}）"
    html = re.sub(r"<title>.*?</title>", f"<title>{title_str}</title>", html)

    # masthead 更新
    html = re.sub(
        r"<!-- DAILY-NEWS:MASTHEAD:START -->.*?<!-- DAILY-NEWS:MASTHEAD:END -->",
        _masthead_html(today, len(articles), now_jst),
        html,
        flags=re.DOTALL,
    )

    # 今日の一言（KOTOBA）更新
    lead_art = load_lead_story_article(articles)
    if lead_art:
        html = re.sub(
            r"<!-- DAILY-NEWS:KOTOBA:START -->.*?<!-- DAILY-NEWS:KOTOBA:END -->",
            _render_lead_story(lead_art),
            html,
            flags=re.DOTALL,
        )

    # セクション更新
    sections_html = generate_sections_html(articles)
    html = re.sub(
        r"<!-- DAILY-NEWS:SECTIONS:START -->.*?<!-- DAILY-NEWS:SECTIONS:END -->",
        f"<!-- DAILY-NEWS:SECTIONS:START -->\n{sections_html}\n    <!-- DAILY-NEWS:SECTIONS:END -->",
        html,
        flags=re.DOTALL,
    )

    INDEX_HTML.write_text(html, encoding="utf-8")


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
# main
# ---------------------------------------------------------------------------

def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass

    JST = ZoneInfo("Asia/Tokyo")
    now_jst = datetime.now(JST).strftime("%Y-%m-%d %H:%M JST")

    articles = load_recent_articles()
    update_index_html(articles, now_jst)
    msg = f"render_html: index.html 更新 {len(articles)}件"
    _append_job_log(msg)
    print(msg)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
