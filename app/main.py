"""FastAPI 入口：图书 CRUD、统计、正文、sync、git。uvicorn app.main:app"""
import os
import re
import sqlite3
import subprocess
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import db as dbmod
from . import analytics, douban
from .ai import gen
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


def local_cover_stems(covers_dir: Path) -> set:
    """扫描 raw/covers/，返回拥有本地封面文件的 isbn 主干集合（去扩展名）。
    前端“是否有封面”与书架过滤的唯一依据——封面的真值在磁盘文件，不在 DB。"""
    if not covers_dir.exists():
        return set()
    return {p.stem for p in covers_dir.iterdir()
            if p.suffix.lower().lstrip(".") in douban.EXTS}


def create_app(db_path: Path, root: Path) -> FastAPI:
    app = FastAPI(title="book-log")
    app.state.db_path = Path(db_path)
    app.state.root = Path(root)
    covers_dir = Path(root) / "raw" / "covers"   # 本地封面库（app.douban --localize 填充）
    covers_dir.mkdir(parents=True, exist_ok=True)
    with dbmod.db_conn(app.state.db_path) as conn:
        dbmod.init_db(conn)

    def conn_of(request):
        return dbmod.db_conn(request.app.state.db_path)

    # ---------- 图书 CRUD ----------
    @app.get("/api/books")
    def list_books(request: Request, q: Optional[str] = None, category: Optional[str] = None,
                   author: Optional[str] = None, publisher: Optional[str] = None,
                   platform: Optional[str] = None, status: Optional[str] = None,
                   nationality: Optional[str] = None,
                   min_price: Optional[float] = None, max_price: Optional[float] = None,
                   min_rating: Optional[int] = None, year: Optional[int] = None,
                   sort: str = "id", desc: bool = False,
                   page: int = 1, page_size: int = Query(50, le=500)):
        with conn_of(request) as conn:
            return dbmod.list_books(conn, q=q, category=category, author=author,
                                    publisher=publisher, platform=platform, status=status,
                                    nationality=nationality,
                                    min_price=min_price, max_price=max_price,
                                    min_rating=min_rating, year=year, sort=sort, desc=desc,
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

    # ---------- AI ----------
    @app.get("/api/books/{bid}/summary")
    def get_summary(request: Request, bid: int, fresh: int = 0):
        with conn_of(request) as conn:
            b = dbmod.get_book(conn, bid)
            if not b:
                raise HTTPException(404, "不存在")
            if fresh:
                conn.execute("DELETE FROM ai_cache WHERE key = ?", (b["file_path"],))
                conn.commit()
            try:
                return gen.summarize_book(conn, request.app.state.root, b)
            except ValueError as e:
                raise HTTPException(404, str(e))
            except Exception as e:
                raise HTTPException(502, f"模型调用失败: {type(e).__name__}: {e}")

    @app.get("/api/ai/yearly")
    def get_yearly(request: Request, year: int = 0, fresh: int = 0, pending: int = 0):
        with conn_of(request) as conn:
            years = [r[0] for r in conn.execute(
                "SELECT DISTINCT year_of(created) y FROM books WHERE created IS NOT NULL "
                "ORDER BY y DESC") if r[0]]
            if not year:
                return {"years": years}
            if pending:  # 只查缓存，不触发生成（前端初始化用）
                text = gen.cache_get(conn, f"yearly:{year}")
                return {"text": text, "cached": text is not None}
            if fresh:
                conn.execute("DELETE FROM ai_cache WHERE key = ?", (f"yearly:{year}",))
                conn.commit()
            try:
                return gen.yearly_portrait(conn, request.app.state.root, year)
            except ValueError as e:
                raise HTTPException(404, str(e))
            except Exception as e:
                raise HTTPException(502, f"模型调用失败: {type(e).__name__}: {e}")

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

    # ---------- 仪表盘分析（analytics.py 纯聚合） ----------
    @app.get("/api/stats/daily")
    def stats_daily(request: Request):
        with conn_of(request) as conn:
            return analytics.daily_counts(conn)

    @app.get("/api/stats/spectrum")
    def stats_spectrum(request: Request):
        with conn_of(request) as conn:
            return analytics.taste_spectrum(conn)   # 纯读；国籍判定显式触发，见 /api/ai/author-meta

    @app.get("/api/ai/author-meta")
    def author_meta_status(request: Request):
        with conn_of(request) as conn:
            return gen.flag_status(conn)

    @app.post("/api/ai/author-meta")
    def author_meta_run(request: Request):
        with conn_of(request) as conn:
            try:
                judged = gen.ensure_author_meta(conn)
            except Exception as e:
                raise HTTPException(502, f"模型调用失败: {type(e).__name__}: {e}")
            return {**gen.flag_status(conn), "judged": judged}

    @app.get("/api/stats/quadrant")
    def stats_quadrant(request: Request):
        with conn_of(request) as conn:
            return analytics.quadrant(conn)

    @app.get("/api/stats/wall")
    def stats_wall(request: Request):
        """封面墙：只出有本地封面文件（raw/covers/<isbn>.*）的书，前端直接渲染不需兼容旧热链。"""
        stems = local_cover_stems(covers_dir)
        with conn_of(request) as conn:
            data = analytics.cover_wall(conn)
        data["items"] = [it for it in data["items"] if it["isbn"] in stems]
        return data

    @app.post("/api/books/{bid}/cover")
    def book_cover_fill(request: Request, bid: int):
        """新书单本补封面：以 douban_id 拓 og:image → 落盘 raw/covers/<isbn>（批量走 python -m app.douban）。"""
        with conn_of(request) as conn:
            row = conn.execute("SELECT douban_id, isbn FROM books WHERE id = ?", (bid,)).fetchone()
            if not row:
                raise HTTPException(404, "不存在")
            if not row["douban_id"]:
                raise HTTPException(400, "无豆瓣号，无法抓封面")
            try:
                path = douban.fetch_cover_local(row["douban_id"], row["isbn"], covers_dir)
            except RuntimeError as e:
                raise HTTPException(502, str(e))
        # path=None 代表豆瓣只有占位图/无 isbn（不落盘），has_cover 驱动前端按钮/刷新
        return {"has_cover": path is not None, "isbn": row["isbn"]}

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

    @app.get("/api/covers")
    def covers_list():
        """已落盘的本地封面 isbn 清单（前端据此判断“有没有封面”/是否显“抓封面”按钮）。"""
        return sorted(local_cover_stems(covers_dir))

    @app.get("/cover/{isbn}")
    def cover_file(isbn: str):
        """按 isbn 伺服本地封面（忽略扩展名）；无文件 404，前端退书名卡。"""
        for ext in douban.EXTS:
            p = covers_dir / f"{isbn}.{ext}"
            if p.exists():
                return FileResponse(p)
        raise HTTPException(404, "no cover")

    @app.get("/", include_in_schema=False)
    def index():
        html = (static_dir / "index.html").read_text(encoding="utf-8")
        # 静态资源加 ?v= 版本号：浏览器按 URL 缓存，版本一变必重新拉取
        html = re.sub(r'(/static/[^"\']+)(")', rf'\1?v={ver}\2', html)
        return HTMLResponse(html, headers={"Cache-Control": "no-cache"})

    return app


app = create_app(DB_PATH, ROOT)
