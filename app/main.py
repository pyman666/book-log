"""FastAPI 入口：图书 CRUD、统计、正文、sync、git。uvicorn app.main:app"""
import os
import re
import sqlite3
import subprocess
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import db as dbmod
from .sync import sync_vault

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "books.db"


def _strip_douban_header(text: str) -> str:
    """剥掉文件开头的豆瓣引用块（首行含 book.douban.com 才剥，连续 blockquote+空行直到正文）。"""
    lines = text.splitlines()
    if not lines or "book.douban.com" not in lines[0]:
        return text
    i = 0
    while i < len(lines) and (lines[i].startswith(">") or not lines[i].strip()):
        i += 1
    return "\n".join(lines[i:]).strip()


class BookIn(BaseModel):
    title: str = ""              # POST 时空值由路由 400 拦截；PUT 部分更新可省略（title 不可改）
    isbn: Optional[str] = None
    price: Optional[float] = None
    importance: Optional[float] = None
    progress: Optional[int] = None
    rating: Optional[int] = None
    status: Optional[str] = "in_library"
    created: Optional[str] = None
    last_modified: Optional[str] = None
    file_path: Optional[str] = None
    douban_id: Optional[str] = None
    authors: Optional[List[str]] = None
    publishers: Optional[List[str]] = None
    categories: Optional[List[str]] = None
    platform: Optional[str] = None


def _app_version(root: Path) -> str:
    """静态资源缓存破坏用；读不到 pyproject 时退回 dev。"""
    try:
        m = re.search(r'version\s*=\s*"([^"]+)"', (root / "pyproject.toml").read_text(encoding="utf-8"))
        if m:
            return m.group(1)
    except OSError:
        pass
    return "dev"


def create_app(db_path: Path, root: Path) -> FastAPI:
    app = FastAPI(title="book-log")
    app.state.db_path = Path(db_path)
    app.state.root = Path(root)
    with dbmod.db_conn(app.state.db_path) as conn:
        dbmod.init_db(conn)

    def conn_of(request):
        return dbmod.db_conn(request.app.state.db_path)

    # ---------- 图书 CRUD ----------
    @app.get("/api/books")
    def list_books(request: Request, q: Optional[str] = None, category: Optional[str] = None,
                   author: Optional[str] = None, publisher: Optional[str] = None,
                   platform: Optional[str] = None, status: Optional[str] = None,
                   min_price: Optional[float] = None, max_price: Optional[float] = None,
                   min_rating: Optional[int] = None, sort: str = "id", desc: bool = False,
                   page: int = 1, page_size: int = Query(50, le=200)):
        with conn_of(request) as conn:
            return dbmod.list_books(conn, q=q, category=category, author=author,
                                    publisher=publisher, platform=platform, status=status,
                                    min_price=min_price, max_price=max_price,
                                    min_rating=min_rating, sort=sort, desc=desc,
                                    page=page, page_size=page_size)

    @app.post("/api/books")
    def create_book(payload: BookIn, request: Request):
        if not payload.title.strip():
            raise HTTPException(400, "书名必填")
        with conn_of(request) as conn:
            return dbmod.save_book(conn, payload.model_dump())

    @app.get("/api/books/{bid}")
    def get_book(request: Request, bid: int):
        with conn_of(request) as conn:
            b = dbmod.get_book(conn, bid)
        if not b:
            raise HTTPException(404, "不存在")
        return b

    @app.put("/api/books/{bid}")
    def update_book(payload: BookIn, request: Request, bid: int):
        data = payload.model_dump(exclude_unset=True)
        with conn_of(request) as conn:
            try:
                b = dbmod.update_book(conn, bid, data)
            except sqlite3.IntegrityError:
                raise HTTPException(400, "与已有记录冲突")
        if not b:
            raise HTTPException(404, "不存在")
        return b

    @app.delete("/api/books/{bid}")
    def delete_book(request: Request, bid: int):
        with conn_of(request) as conn:
            n = conn.execute("DELETE FROM books WHERE id = ?", (bid,)).rowcount
            conn.commit()
        if not n:
            raise HTTPException(404, "不存在")
        return {"deleted": bid}

    @app.get("/api/books/{bid}/content", response_class=PlainTextResponse)
    def get_content(request: Request, bid: int):
        with conn_of(request) as conn:
            row = conn.execute("SELECT file_path FROM books WHERE id = ?", (bid,)).fetchone()
        if not row or not row["file_path"]:
            raise HTTPException(404, "无正文")
        root = request.app.state.root.resolve()
        p = (root / row["file_path"]).resolve()
        if not p.is_relative_to(root) or not p.is_file():
            raise HTTPException(404, "无正文")
        body = _strip_douban_header(p.read_text(encoding="utf-8"))
        if not body:
            raise HTTPException(404, "无正文")   # 只有豆瓣头/空文件，视为无自己的笔记
        return body

    # ---------- 筛选维度 ----------
    @app.get("/api/facets")
    def facets(request: Request):
        with conn_of(request) as conn:
            return dbmod.facets(conn)

    # ---------- 统计 ----------
    @app.get("/api/stats/summary")
    def stats_summary(request: Request):
        with conn_of(request) as conn:
            return dbmod.stats_summary(conn)

    @app.get("/api/stats/group")
    def stats_group(request: Request, by: str, agg: str = "count"):
        with conn_of(request) as conn:
            try:
                return dbmod.stats_group(conn, by, agg)
            except (KeyError, ValueError):
                raise HTTPException(400, "by/agg 参数无效")

    # ---------- sync & git ----------
    @app.post("/api/sync")
    def sync(request: Request):
        with conn_of(request) as conn:
            return sync_vault(conn, request.app.state.root)

    @app.post("/api/git/push")
    def git_push(request: Request):
        out, ok = [], True
        env = {**os.environ, "LC_ALL": "C"}   # 固定英文输出，跨设备一致
        for cmd in (["git", "add", "-A"],
                    ["git", "commit", "-m", "book-log: 网页更新"],
                    ["git", "push"]):
            r = subprocess.run(cmd, cwd=request.app.state.root, capture_output=True,
                               text=True, timeout=120, env=env)
            out.append("$ " + " ".join(cmd) + "\n" + (r.stdout or "") + (r.stderr or ""))
            ok = ok and r.returncode == 0
        return {"ok": ok, "output": "\n".join(out)}

    # ---------- 页面 ----------
    ver = _app_version(root)
    static_dir = Path(__file__).parent / "static"
    if static_dir.is_dir():
        app.mount("/static", StaticFiles(directory=static_dir), name="static")

    @app.get("/", include_in_schema=False)
    def index():
        html = (static_dir / "index.html").read_text(encoding="utf-8")
        # 静态资源加 ?v= 版本号：浏览器按 URL 缓存，版本一变必重新拉取
        html = re.sub(r'(/static/[^"\']+)(")', rf'\1?v={ver}\2', html)
        return HTMLResponse(html, headers={"Cache-Control": "no-cache"})

    return app


app = create_app(DB_PATH, ROOT)
