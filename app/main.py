"""FastAPI 应用组装入口。"""
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from . import db as dbmod
from .dependencies import local_cover_stems
from .routes import ai, books, covers, git, pages, stats, sync

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "books.db"
STATIC_DIR = Path(__file__).parent / "static"


def app_version(root: Path) -> str:
    """读取 pyproject.toml 版本号；读不到时返回 dev。"""
    import re

    try:
        match = re.search(r'version\s*=\s*"([^"]+)"',
                          (root / "pyproject.toml").read_text(encoding="utf-8"))
        return match.group(1) if match else "dev"
    except OSError:
        return "dev"


def create_app(db_path: Path, root: Path) -> FastAPI:
    app = FastAPI(title="book-log")
    app.state.db_path = Path(db_path)
    app.state.root = Path(root)
    app.state.covers_dir = app.state.root / "raw" / "covers"
    app.state.covers_dir.mkdir(parents=True, exist_ok=True)
    app.state.static_dir = STATIC_DIR
    app.state.version = app_version(app.state.root)

    with dbmod.db_conn(app.state.db_path) as conn:
        dbmod.init_db(conn)

    for route_module in (books, ai, stats, covers, sync, git, pages):
        app.include_router(route_module.router)
    if STATIC_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app


def build_app() -> FastAPI:
    """uvicorn 入口：`uv run uvicorn app.main:build_app --factory --host 127.0.0.1 --port 8000`。
    故意不在模块级 create_app——那样 import app.main 就会对生产 books.db 跑 init_db，
    跑一次 pytest 顺手改掉真库（测试全部用 tmp_path 显式建应用）。"""
    return create_app(DB_PATH, ROOT)
