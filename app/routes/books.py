"""图书 CRUD 与正文路由。"""
import sqlite3
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse

from .. import db as dbmod, notes
from ..dependencies import conn_of, strip_douban_header
from ..models import AuthorNatIn, BookIn

router = APIRouter()


@router.get("/api/books")
def list_books(request: Request, q: Optional[str] = None, category: Optional[str] = None,
               author: Optional[str] = None, publisher: Optional[str] = None,
               platform: Optional[str] = None, status: Optional[str] = None,
               nationality: Optional[str] = None, min_price: Optional[float] = None,
               max_price: Optional[float] = None, min_rating: Optional[int] = None,
               year: Optional[int] = None, sort: str = "id", desc: bool = False,
               page: int = 1, page_size: int = Query(50, le=500)):
    with conn_of(request) as conn:
        data = dbmod.list_books(conn, q=q, category=category, author=author,
                                publisher=publisher, platform=platform, status=status,
                                nationality=nationality, min_price=min_price,
                                max_price=max_price, min_rating=min_rating, year=year,
                                sort=sort, desc=desc, page=page, page_size=page_size)
        notes.annotate(conn, request.app.state.root, data["items"])   # 正文文件名靠推导，不查库
        return data


@router.post("/api/books")
def create_book(payload: BookIn, request: Request):
    if not payload.title.strip():
        raise HTTPException(400, "书名必填")
    with conn_of(request) as conn:
        return dbmod.save_book(conn, payload.model_dump())


@router.get("/api/books/{bid}")
def get_book(request: Request, bid: int):
    with conn_of(request) as conn:
        book = dbmod.get_book(conn, bid)
        if book:
            notes.annotate(conn, request.app.state.root, [book])
    if not book:
        raise HTTPException(404, "不存在")
    return book


@router.put("/api/books/{bid}")
def update_book(payload: BookIn, request: Request, bid: int):
    data = payload.model_dump(exclude_unset=True)
    with conn_of(request) as conn:
        try:
            book = dbmod.update_book(conn, bid, data)
        except sqlite3.IntegrityError:
            raise HTTPException(400, "与已有记录冲突")
    if not book:
        raise HTTPException(404, "不存在")
    return book


@router.put("/api/books/{bid}/author-nationalities")
def update_author_nationalities(payload: AuthorNatIn, request: Request, bid: int):
    """书单页国籍弹层：按作者名设置国籍。作者行跨书共享——改一位作者，他所有书跟着变，
    前端已在 tooltip 里声明这一副作用。只认该书自己的作者（防止越权改无关作者行）。"""
    with conn_of(request) as conn:
        if not conn.execute("SELECT id FROM books WHERE id = ?", (bid,)).fetchone():
            raise HTTPException(404, "不存在")
        book_authors = {r[0] for r in conn.execute(
            "SELECT a.name FROM book_authors ba JOIN authors a ON a.id=ba.author_id "
            "WHERE ba.book_id = ?", (bid,))}
        for name, nat in payload.nationalities.items():
            name = (name or "").strip()
            if name not in book_authors:
                continue
            conn.execute("UPDATE authors SET nationality = ? WHERE name = ?",
                         (nat.strip() or None, name))
        conn.commit()
        return dbmod.get_book(conn, bid)


@router.delete("/api/books/{bid}")
def delete_book(request: Request, bid: int):
    with conn_of(request) as conn:
        deleted = conn.execute("DELETE FROM books WHERE id = ?", (bid,)).rowcount
        conn.commit()
    if not deleted:
        raise HTTPException(404, "不存在")
    return {"deleted": bid}


@router.get("/api/books/{bid}/content", response_class=PlainTextResponse)
def get_content(request: Request, bid: int):
    """笔记正文：文件名按命名法从 (书名, 作者) 推导，库里不存路径。"""
    root = request.app.state.root
    with conn_of(request) as conn:
        exists = conn.execute("SELECT 1 FROM books WHERE id = ?", (bid,)).fetchone()
        note = notes.resolve(conn, root).get(bid)
    if not exists:
        raise HTTPException(404, "不存在")
    path = notes.note_path(root, note)
    if not path or not path.is_file():
        raise HTTPException(404, "无正文")
    body = strip_douban_header(path.read_text(encoding="utf-8"))
    if not body:
        raise HTTPException(404, "无正文")
    return body

