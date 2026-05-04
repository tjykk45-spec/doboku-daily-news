"""プロジェクト直下の `.env` / `Daily-News.env` を読み込む（先に読んだ方が優先）。"""

from pathlib import Path

from dotenv import load_dotenv


def load_project_env(root: Path) -> None:
    load_dotenv(root / ".env")
    load_dotenv(root / "Daily-News.env")
