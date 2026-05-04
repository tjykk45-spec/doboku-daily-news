"""
報道系ページ向けの軽量 HTML 取得と本文抜粋（主に国交省 mlit.go.jp の報道発表用 POC）。
有料媒体や JS 必須ページでは破綻しうる。AGENTS: 有料壁は本文推測しない方針に従う。
"""

from __future__ import annotations

import re
import urllib.error
import urllib.request
from urllib.parse import urlparse

from bs4 import BeautifulSoup

USER_AGENT = "Mozilla/5.0 (compatible; DailyNewsLocal/1.0; +local) AppleWebKit/537.36"


def _fetch_html_and_url(url: str) -> tuple[bytes, str]:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept-Language": "ja,en-US;q=0.7,en;q=0.3"},
    )
    with urllib.request.urlopen(req, timeout=90) as resp:
        return resp.read(), (resp.geturl() or url)


def _squeeze_title(soup: BeautifulSoup) -> str:
    t = soup.find("title")
    if not t or not t.get_text():
        return ""
    s = t.get_text().strip()
    s = re.sub(r"\s*[\|｜]\s*.*$", "", s)
    return s[:300]


def extract_press_text_and_title(html: str) -> tuple[str, str]:
    """
    戻り値: (page_title, body_plain) 。body はプレーンテキストの塊（長すぎる場合は切り詰め）。
    """
    soup = BeautifulSoup(html, "html.parser")
    title = _squeeze_title(soup)
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    root = (
        soup.find("div", class_="main")
        or soup.find("div", class_="mainArea")
        or soup.find("div", id="contents")
        or soup.find("div", class_="contents")
        or soup.find("main")
    )
    if not root and soup.find("body"):
        root = soup.find("body")
    if not root:
        return title, ""
    for tag in root.find_all(["nav", "header", "footer"]):
        tag.decompose()
    text = root.get_text("\n", strip=True)
    lines = [ln for ln in (x.strip() for x in text.splitlines()) if ln]
    body = "\n\n".join(lines)
    if len(body) > 200_000:
        body = body[:200_000] + "\n\n(以降省略)"
    return title, body


def fetch_press_page(url: str) -> tuple[str, str, str]:
    """
    戻り値: (page_title, body_plain, final_url) 。リダイレクト後の URL を final_url に返す。
    """
    if urlparse(url).scheme not in ("http", "https"):
        raise ValueError("http(s) URL のみ対応しています")
    data, final_url = _fetch_html_and_url(url)
    # charset は簡易: UTF-8 優先。失敗時は replace
    try:
        html = data.decode("utf-8")
    except UnicodeDecodeError:
        html = data.decode("utf-8", errors="replace")
    title, body = extract_press_text_and_title(html)
    return title, body, final_url
