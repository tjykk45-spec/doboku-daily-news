"""
当日の clips/data/ 配下の JSON を読み、edge-tts で MP3 を生成する。
生成後、Google Drive にアップロード（オプション）。

使い方:
    python scripts/tts_generate.py
    python scripts/tts_generate.py --date 2026-06-01   # 特定日を対象にする
    python scripts/tts_generate.py --no-drive          # Google Drive アップロードをスキップ

出力: clips/audio/YYYY-MM-DD.mp3
成功時は出力パスを stdout に、状態メッセージは stderr に書く（Run-Daily.ps1 が stdout を読む）。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import date, timedelta
from pathlib import Path

from dotenv import load_dotenv

try:
    import edge_tts
except ImportError:
    print(
        "[tts] edge-tts がインストールされていません。"
        "`pip install edge-tts` を実行してください。",
        file=sys.stderr,
    )
    raise SystemExit(1)

try:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
except ImportError:
    print(
        "[tts] Google Drive API ライブラリがインストールされていません。"
        "`pip install -r requirements.txt` を実行してください。",
        file=sys.stderr,
    )
    raise SystemExit(1)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "clips" / "data"
AUDIO_DIR = PROJECT_ROOT / "clips" / "audio"

# .env ファイルを読み込む
load_dotenv(PROJECT_ROOT / ".env")
load_dotenv(PROJECT_ROOT / "Daily-News.env")

KEEP_DAYS = 7
VOICE = "ja-JP-NanamiNeural"

SECTION_ORDER = ["国交省・規制・政策", "技術・トレンド", "資材価格・コスト"]

# Google Drive OAuth 2.0
SCOPES = ["https://www.googleapis.com/auth/drive.file"]
TOKEN_FILE = PROJECT_ROOT / "clips" / ".gdrive-token.json"
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
DRIVE_FOLDER_ID = os.environ.get("DRIVE_FOLDER_ID", "")


def load_articles(target: date) -> list[dict]:
    prefix = target.isoformat()
    articles = []
    for f in sorted(DATA_DIR.glob(f"{prefix}_*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8-sig"))
            if data.get("is_in_scope", True):
                articles.append(data)
        except (json.JSONDecodeError, OSError):
            pass
    return articles


def build_script(articles: list[dict], target: date) -> str:
    parts: list[str] = []
    parts.append(
        f"本日、{target.year}年{target.month}月{target.day}日の"
        "土木デイリーニュースです。"
    )

    if not articles:
        parts.append("本日は新着ニュースがありません。")
        return "\n".join(parts)

    parts.append(f"{len(articles)}件のニュースをお届けします。")

    by_section: dict[str, list[dict]] = {}
    for a in articles:
        by_section.setdefault(a.get("section", "その他"), []).append(a)

    num = 1
    ordered_sections = [s for s in SECTION_ORDER if s in by_section]
    ordered_sections += [s for s in by_section if s not in SECTION_ORDER]

    for section in ordered_sections:
        parts.append(f"\n【{section}】")
        for a in by_section[section]:
            title = a.get("title", "")
            lead = a.get("lead", "")
            parts.append(f"{num}件目。{title}。{lead}")
            num += 1

    parts.append("\n以上、本日の土木デイリーニュースでした。")
    return "\n".join(parts)


async def _generate(text: str, output_path: Path) -> None:
    communicate = edge_tts.Communicate(text, VOICE)
    await communicate.save(str(output_path))


def purge_old(audio_dir: Path, today: date) -> None:
    cutoff = today - timedelta(days=KEEP_DAYS)
    for f in audio_dir.glob("*.mp3"):
        try:
            if date.fromisoformat(f.stem[:10]) < cutoff:
                f.unlink()
        except (ValueError, OSError):
            pass


def get_drive_credentials() -> Credentials | None:
    """
    OAuth 2.0 トークンを取得。初回は認可フロー、以降はトークンを再利用。
    """
    creds = None

    # 既存トークンがあれば読み込み
    if TOKEN_FILE.is_file():
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, scopes=SCOPES)

    # トークンが無いまたは期限切れなら認可フロー
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            print("[tts] トークンをリフレッシュ中...", file=sys.stderr)
            creds.refresh(Request())
        else:
            if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
                print(
                    "[tts] GOOGLE_CLIENT_ID/SECRET が設定されていません。.env を確認してください。",
                    file=sys.stderr,
                )
                return None

            print("[tts] 初回認可: ブラウザが開きます。Google アカウントで許可してください。", file=sys.stderr)
            flow = InstalledAppFlow.from_client_config(
                {
                    "installed": {
                        "client_id": GOOGLE_CLIENT_ID,
                        "client_secret": GOOGLE_CLIENT_SECRET,
                        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                        "token_uri": "https://oauth2.googleapis.com/token",
                        "redirect_uris": ["http://localhost"],
                    }
                },
                scopes=SCOPES,
            )
            creds = flow.run_local_server(port=0)

        # トークンを保存
        TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
        with TOKEN_FILE.open("w") as f:
            f.write(creds.to_json())
        print(f"[tts] トークンを保存しました: {TOKEN_FILE}", file=sys.stderr)

    return creds


def upload_to_drive(mp3_path: Path) -> bool:
    """
    MP3 を Google Drive のマイドライブにアップロード。
    成功時 True, 失敗時 False を返す。
    """
    try:
        creds = get_drive_credentials()
        if not creds:
            return False

        drive_service = build("drive", "v3", credentials=creds)

        file_metadata = {
            "name": mp3_path.name,
            "mimeType": "audio/mpeg",
        }
        if DRIVE_FOLDER_ID:
            file_metadata["parents"] = [DRIVE_FOLDER_ID]
        media = MediaFileUpload(str(mp3_path), mimetype="audio/mpeg")

        result = drive_service.files().create(
            body=file_metadata,
            media_body=media,
            fields="id, webViewLink",
        ).execute()

        link = result.get("webViewLink", "")
        print(
            f"[tts] Google Drive にアップロード完了: {link}",
            file=sys.stderr,
        )
        return True

    except Exception as e:
        print(f"[tts] Google Drive アップロード失敗: {e}", file=sys.stderr)
        return False


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass

    parser = argparse.ArgumentParser(description="当日ニュースを MP3 に変換する")
    parser.add_argument(
        "--date",
        default=None,
        help="対象日 YYYY-MM-DD（省略時: 今日）",
    )
    parser.add_argument(
        "--no-drive",
        action="store_true",
        help="Google Drive アップロードをスキップ",
    )
    args = parser.parse_args()

    target = date.fromisoformat(args.date) if args.date else date.today()
    articles = load_articles(target)

    if not articles:
        print(
            f"[tts] {target} の記事がありません（is_in_scope=true のものが0件）。スキップします。",
            file=sys.stderr,
        )
        return 0

    script_text = build_script(articles, target)
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    output_path = AUDIO_DIR / f"{target.isoformat()}.mp3"

    print(
        f"[tts] {len(articles)}件 → {output_path.name} を生成中...",
        file=sys.stderr,
    )

    try:
        asyncio.run(_generate(script_text, output_path))
    except Exception as e:
        print(f"[tts] edge-tts エラー: {e}", file=sys.stderr)
        return 1

    size_kb = output_path.stat().st_size // 1024
    print(f"[tts] 完了 ({size_kb} KB): {output_path}", file=sys.stderr)

    purge_old(AUDIO_DIR, target)

    # Google Drive にアップロード（オプション）
    if not args.no_drive:
        upload_to_drive(output_path)

    # 呼び出し元（Run-Daily.ps1）が Start-Process に使うためパスを stdout へ
    print(str(output_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
