"""
朝の自動ジョブ用エントリ（ローカル PC）。

- 既定: ジョブ用ログ（起動成功の心拍）だけを追記
- --ingest: scripts/watchlist.txt の先頭行（URL \\t 日付 \\t 任意タイトル）を1件処理
  本文取得 -> summarize_one -> clips/log/YYYY-MM.md へ1行追記
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import traceback
from datetime import date, datetime
from pathlib import Path

from project_env import load_project_env

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = Path(__file__).resolve().parent
WATCHLIST_DEFAULT = SCRIPTS_DIR / "watchlist.txt"
CACHE_DIR = PROJECT_ROOT / "clips" / ".cache"
DATA_DIR = PROJECT_ROOT / "clips" / "data"
SUMMARIZE = SCRIPTS_DIR / "summarize_one.py"


def job_log_path(d: date) -> Path:
    return PROJECT_ROOT / "clips" / "log" / f"_job-{d.year:04d}{d.month:02d}.log"


def append_job_log(d: date, message: str) -> None:
    p = job_log_path(d)
    p.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with p.open("a", encoding="utf-8") as f:
        f.write(f"- {now} | {message}\n")


def monthly_article_log_path(d: date) -> Path:
    return PROJECT_ROOT / "clips" / "log" / f"{d.year:04d}-{d.month:02d}.md"


def ensure_monthly_article_log(p: Path, d: date) -> None:
    if p.is_file():
        return
    p.parent.mkdir(parents=True, exist_ok=True)
    header = f"""# {d.year}-{d.month:02d} 取り込みログ

このファイルは自動ジョブが append するタイムラインです。1記事1行が原則。詳細は `projects/` または朝刊HTMLの「深掘り」を参照。

## フォーマット

```
- YYYY-MM-DD HH:MM | <section> | <title> | <url> | <tags>
```

## エントリ

"""
    p.write_text(header, encoding="utf-8")


def format_tags_for_log(tags: list) -> str:
    return " ".join(f"`{t}`" for t in tags if isinstance(t, str))


def append_article_line(p: Path, d: date, section: str, title: str, url: str, tags: list) -> None:
    ensure_monthly_article_log(p, d)
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    tline = f"- {now} | {section} | {title} | {url} | {format_tags_for_log(tags)}\n"
    text = p.read_text(encoding="utf-8")
    if text and not text.endswith("\n"):
        text += "\n"
    p.write_text(text + tline, encoding="utf-8")


def first_watchlist_entry(
    watchlist: Path, skip_urls: set[str] | None = None
) -> tuple[str, str, str | None, list[str] | None]:
    """
    先頭の処理対象行を返す: (url, date_str, title_override, all_lines) 。
    対象行がなければ (None, None, None, None) 。all_lines は書き戻し用の全行（改行付き list）。
    skip_urls に含まれる URL はスキップ（watchlist からは削除しない）。
    """
    if not watchlist.is_file():
        return None, None, None, None
    raw = watchlist.read_text(encoding="utf-8", errors="replace")
    lines = raw.splitlines(keepends=True)
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        try:
            url, dstr, t_override = _parse_watchlist_content(stripped)
        except ValueError:
            continue
        if skip_urls and url in skip_urls:
            continue
        new_lines = lines[:i] + lines[i + 1 :]
        return url, dstr, t_override, new_lines
    return None, None, None, None


def _parse_watchlist_content(stripped: str) -> tuple[str, str, str | None]:
    parts = stripped.split("\t")
    if len(parts) < 2:
        raise ValueError
    url = parts[0].strip()
    dstr = parts[1].strip()[:10]
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", dstr):
        raise ValueError
    t_override = parts[2].strip() if len(parts) > 2 and parts[2].strip() else None
    if not (url.startswith("http://") or url.startswith("https://")):
        raise ValueError
    return url, dstr, t_override


def write_watchlist(watchlist: Path, new_lines: list[str]) -> None:
    watchlist.write_text("".join(new_lines), encoding="utf-8")


def _source_name_for_url(url: str) -> str:
    host = url.split("/")[2] if "://" in url else url
    if "mlit.go.jp" in host:
        return "国交省 報道発表（自動取得）"
    return "自動取得"


def run_summarize(
    body_file: Path, url: str, title: str, dstr: str, source: str
) -> dict:
    cmd = [
        sys.executable,
        str(SUMMARIZE),
        "--url",
        url,
        "--title",
        title,
        "--body-file",
        str(body_file),
        "--date",
        dstr,
        "--source-name",
        source,
    ]
    r = subprocess.run(
        cmd,
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if r.returncode != 0:
        err = (r.stderr or "") + (r.stdout or "")
        raise RuntimeError(f"summarize_one 失敗 (exit {r.returncode}): {err[:2000]}")

    out = (r.stdout or "").strip()
    if not out:
        raise RuntimeError("summarize_one の標準出力が空です")
    return json.loads(out)


def _save_article_json(data: dict, source: str) -> None:
    """要約 JSON を clips/data/ に保存する（render_html.py が読む）。"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    art_date = data.get("date", date.today().isoformat())
    url_hash = abs(hash(data.get("url", ""))) % (10 ** 12)
    out = dict(data)
    out["source_name"] = source
    p = DATA_DIR / f"{art_date}_{url_hash}.json"
    p.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")


def ingest_one(watchlist: Path, skip_urls: set[str] | None = None) -> bool | None:
    """
    watchlist の先頭1件を処理する。
    戻り値: True=成功, False=失敗, None=処理対象なし（watchlist が空または全スキップ）。
    """
    load_project_env(PROJECT_ROOT)
    url, dstr, title_override, new_lines = first_watchlist_entry(watchlist, skip_urls)
    if not url or new_lines is None:
        append_job_log(date.today(), "ingest: watchlist に処理対象行がありません")
        return None

    from mlit_text import fetch_press_page

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        page_title, body, final_url = fetch_press_page(url)
    except Exception as e:
        append_job_log(
            date.today(),
            f"ingest: 取得失敗 {url!r} : {e!s}",
        )
        if skip_urls is not None:
            skip_urls.add(url)
        return False

    if not body or len(body.strip()) < 20:
        append_job_log(date.today(), f"ingest: 本文が短すぎるためスキップ {url!r}")
        if skip_urls is not None:
            skip_urls.add(url)
        return False

    title = title_override or page_title or "（タイトル未取得）"
    body_file = CACHE_DIR / f"body_{abs(hash(final_url)) % (10**12)}.txt"
    body_file.write_text(body, encoding="utf-8")

    source = _source_name_for_url(final_url)
    try:
        data = run_summarize(body_file, final_url, title, dstr, source)
    except Exception as e:
        append_job_log(
            date.today(),
            f"ingest: 要約失敗 {url!r} : {e!s}\n{traceback.format_exc()[:500]}",
        )
        if skip_urls is not None:
            skip_urls.add(url)
        return False
    finally:
        try:
            body_file.unlink(missing_ok=True)
        except OSError:
            pass

    d = date.fromisoformat(dstr) if dstr else date.today()
    p = monthly_article_log_path(d)
    append_article_line(
        p, d, data["section"], data["title"], data["url"], data.get("tags", [])
    )
    _save_article_json(data, source)
    write_watchlist(watchlist, new_lines)
    append_job_log(
        date.today(),
        f"ingest: ok {data.get('title', '')[:40]} | {data.get('url', '')[:60]}",
    )
    return True


def ingest_all(watchlist: Path, max_count: int = 10) -> int:
    """watchlist を全件処理する。失敗した URL はセッション内でスキップして次に進む。
    max_count: 1回の実行で処理する最大件数（デフォルト10件）。戻り値: 成功件数。"""
    skip_urls: set[str] = set()
    success_count = 0
    attempt_count = 0
    while attempt_count < max_count:
        result = ingest_one(watchlist, skip_urls)
        if result is None:
            break
        attempt_count += 1
        if result is True:
            success_count += 1
    if attempt_count >= max_count:
        append_job_log(
            date.today(),
            f"ingest-all: 上限 {max_count} 件に達したため中断（残りは翌日処理）",
        )
    return success_count


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass
    p = argparse.ArgumentParser(description="朝刊ジョブ（心拍ログ / watchlist 取り込み）")
    p.add_argument(
        "--ingest",
        action="store_true",
        help="watchlist から1件取り込む（要 GEMINI_API_KEY）",
    )
    p.add_argument(
        "--ingest-all",
        action="store_true",
        dest="ingest_all",
        help="watchlist を全件取り込む（失敗した URL はスキップして続行）",
    )
    p.add_argument(
        "--watchlist",
        type=Path,
        default=WATCHLIST_DEFAULT,
        help="既定: scripts/watchlist.txt",
    )
    args = p.parse_args()
    today = date.today()

    if args.ingest_all:
        append_job_log(today, "daily_run 起動 --ingest-all")
        n = ingest_all(args.watchlist)
        append_job_log(today, f"ingest-all: 完了 成功{n}件")
    elif args.ingest:
        append_job_log(today, "daily_run 起動 --ingest")
        ok = ingest_one(args.watchlist)
        if ok is False:
            return 1
    else:
        append_job_log(today, "daily_run 起動")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
