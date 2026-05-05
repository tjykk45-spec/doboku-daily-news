"""
reference/design-preview.html の <style>...</style> ブロックを
index.html の <style>...</style> に上書きコピーする。

使い方:
    python scripts/apply_design.py

ワークフロー:
    1. reference/design-preview.html を Claude Design で編集
    2. このスクリプトを実行 → index.html の CSS が更新される
    3. commit & push（または GitHub Actions が翌朝自動実行）
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PREVIEW_FILE = PROJECT_ROOT / "reference" / "design-preview-v3.html"
INDEX_HTML   = PROJECT_ROOT / "index.html"

_STYLE_RE = re.compile(r"<style>(.*?)</style>", re.DOTALL)


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass

    if not PREVIEW_FILE.is_file():
        print(f"apply_design: {PREVIEW_FILE} が見つかりません", flush=True)
        return 1

    preview = PREVIEW_FILE.read_text(encoding="utf-8")
    m = _STYLE_RE.search(preview)
    if not m:
        print("apply_design: design-preview.html に <style> ブロックが見つかりません", flush=True)
        return 1

    new_style_block = m.group(0)  # <style>...</style> ごと置換

    html = INDEX_HTML.read_text(encoding="utf-8")
    html, n = _STYLE_RE.subn(new_style_block, html, count=1)
    if n == 0:
        print("apply_design: index.html に <style> ブロックが見つかりません", flush=True)
        return 1

    INDEX_HTML.write_text(html, encoding="utf-8")
    print("apply_design: index.html の <style> を design-preview.html から更新しました")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
