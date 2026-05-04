"""
日経クロステック建設・日刊建設工業新聞のRSSから新着記事URLを取得し、
scripts/watchlist.txt にTAB区切りで追記する。

使い方:
    python scripts/fetch_rss.py [--dry-run]

出力フォーマット (watchlist.txt):
    <url>\t<YYYY-MM-DD>\t<title>
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = Path(__file__).resolve().parent

WATCHLIST_DEFAULT = SCRIPTS_DIR / "watchlist.txt"

RSS_SOURCES = [
    {
        "name": "日経クロステック建設",
        "url": "https://xtech.nikkei.com/rss/xtech-con.rdf",
        "fmt": "rdf",
    },
    {
        "name": "日刊建設工業新聞",
        "url": "https://decn.co.jp/?feed=rss2",
        "fmt": "rss2",
    },
]

# AGENTS.md §6-3: robots.txt 準拠。User-Agent に問い合わせ先を明示する。
_UA = "Mozilla/5.0 (compatible; DailyNewsBot/1.0; +mailto:tjykk45@gmail.com)"
_TIMEOUT = 20

_NS_RSS1 = "http://purl.org/rss/1.0/"
_NS_DC = "http://purl.org/dc/elements/1.1/"
_NS_RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"

# タイトルフィルタ: いずれか1つを含む記事だけ watchlist に追加する
_KEYWORDS = [
    "国交省", "土木", "道路", "橋", "河川", "港湾", "下水", "上水",
    "インフラ", "建設", "工事", "積算", "入札", "発注",
    "BIM", "CIM", "i-Con", "DX", "担い手", "働き方", "自動", "AI",
]


def _matches_keyword(title: str) -> bool:
    return any(kw in title for kw in _KEYWORDS)


# ---------------------------------------------------------------------------
# ジョブログ（daily_run.py と同じ形式）
# ---------------------------------------------------------------------------

def _job_log_path(d: date) -> Path:
    return PROJECT_ROOT / "clips" / "log" / f"_job-{d.year:04d}{d.month:02d}.log"


def _append_job_log(d: date, message: str) -> None:
    p = _job_log_path(d)
    p.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with p.open("a", encoding="utf-8") as f:
        f.write(f"- {now} | {message}\n")


# ---------------------------------------------------------------------------
# watchlist 読み書き
# ---------------------------------------------------------------------------

def _load_existing_urls(watchlist: Path) -> set[str]:
    if not watchlist.is_file():
        return set()
    urls: set[str] = set()
    for line in watchlist.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        url = stripped.split("\t")[0].strip()
        if url.startswith("http"):
            urls.add(url)
    return urls


def _append_to_watchlist(
    watchlist: Path, entries: list[tuple[str, str, str]]
) -> None:
    watchlist.parent.mkdir(parents=True, exist_ok=True)
    with watchlist.open("a", encoding="utf-8") as f:
        for url, date_str, title in entries:
            safe_title = title.replace("\t", " ").replace("\n", " ")
            f.write(f"{url}\t{date_str}\t{safe_title}\n")


# ---------------------------------------------------------------------------
# RSS フェッチ・パース
# ---------------------------------------------------------------------------

def _fetch_xml(url: str) -> ET.Element:
    req = Request(url, headers={"User-Agent": _UA})
    with urlopen(req, timeout=_TIMEOUT) as resp:
        content = resp.read()
    return ET.fromstring(content)


def _rdf_date(text: str | None) -> str:
    """dc:date (ISO 8601) → YYYY-MM-DD。失敗時は取得日で代替。"""
    if text:
        try:
            return datetime.fromisoformat(text.strip()).date().isoformat()
        except ValueError:
            pass
    return date.today().isoformat()


def _rss2_date(text: str | None) -> str:
    """pubDate (RFC 2822) → YYYY-MM-DD。失敗時は取得日で代替。"""
    if text:
        try:
            return parsedate_to_datetime(text.strip()).date().isoformat()
        except Exception:
            pass
    return date.today().isoformat()


def _items_from_rdf(root: ET.Element) -> list[tuple[str, str, str]]:
    """RSS 1.0 / RDF から (url, date_str, title) を抽出する。"""
    results: list[tuple[str, str, str]] = []
    for item in root.findall(f"{{{_NS_RSS1}}}item"):
        # URL: rdf:about 属性 → <link> 要素の順に取得
        url = item.get(f"{{{_NS_RDF}}}about") or ""
        if not url:
            url = (item.findtext(f"{{{_NS_RSS1}}}link") or "").strip()
        if not url.startswith("http"):
            continue
        title = (item.findtext(f"{{{_NS_RSS1}}}title") or "").strip()
        date_str = _rdf_date(item.findtext(f"{{{_NS_DC}}}date"))
        results.append((url, date_str, title))
    return results


def _items_from_rss2(root: ET.Element) -> list[tuple[str, str, str]]:
    """RSS 2.0 から (url, date_str, title) を抽出する。"""
    results: list[tuple[str, str, str]] = []
    for item in root.findall(".//item"):
        url = (item.findtext("link") or "").strip()
        if not url.startswith("http"):
            continue
        title = (item.findtext("title") or "").strip()
        date_str = _rss2_date(item.findtext("pubDate"))
        results.append((url, date_str, title))
    return results


def _fetch_source(source: dict) -> list[tuple[str, str, str]]:
    """1ソース分の (url, date_str, title) リストを返す。失敗時は空リスト。"""
    try:
        root = _fetch_xml(source["url"])
    except (URLError, ET.ParseError, Exception) as e:
        print(f"  [ERR] {source['name']}: {e}", file=sys.stderr)
        return []
    if source["fmt"] == "rdf":
        return _items_from_rdf(root)
    return _items_from_rss2(root)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass

    ap = argparse.ArgumentParser(
        description="RSS から watchlist.txt に新着 URL を追記します。"
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="ファイルへの書き込みを行わず結果だけ表示する",
    )
    ap.add_argument(
        "--watchlist",
        type=Path,
        default=WATCHLIST_DEFAULT,
        help=f"出力先 watchlist.txt（既定: {WATCHLIST_DEFAULT}）",
    )
    args = ap.parse_args()

    today = date.today()
    existing_urls = _load_existing_urls(args.watchlist)
    total_added = 0
    log_parts: list[str] = []

    for source in RSS_SOURCES:
        print(f"[fetch] {source['name']} ...", flush=True)
        items = _fetch_source(source)
        filtered = [(u, d, t) for u, d, t in items if _matches_keyword(t)]
        new_items = [(u, d, t) for u, d, t in filtered if u not in existing_urls]
        skipped_dup = len(filtered) - len(new_items)
        skipped_kw = len(items) - len(filtered)
        skipped = skipped_dup + skipped_kw

        if not args.dry_run and new_items:
            _append_to_watchlist(args.watchlist, new_items)
            for url, _, _ in new_items:
                existing_urls.add(url)

        for url, date_str, title in new_items:
            print(f"  + {date_str}  {title[:55]}  {url[:70]}")

        summary = (
            f"{source['name']}: "
            f"取得{len(items)}件 KWフィルタ通過{len(filtered)}件 "
            f"追記{len(new_items)}件 スキップ(重複){skipped_dup}件 スキップ(KW外){skipped_kw}件"
        )
        print(f"  -> {summary}")
        log_parts.append(summary)
        total_added += len(new_items)

    if args.dry_run:
        print("[dry-run] ファイルへの書き込みはしません。")
    else:
        log_msg = (
            "fetch_rss: "
            + " / ".join(log_parts)
            + f" | 合計追記{total_added}件"
        )
        _append_job_log(today, log_msg)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
