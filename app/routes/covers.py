"""本地封面相关路由。"""
import re

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

from .. import db as dbmod, douban
from ..dependencies import conn_of, covers_dir, local_cover_stems

router = APIRouter()


@router.post("/api/books/{bid}/cover")
def book_cover_fill(request: Request, bid: int):
    directory = covers_dir(request)
    with conn_of(request) as conn:
        row = conn.execute("SELECT douban_id, isbn FROM books WHERE id = ?", (bid,)).fetchone()
        if not row:
            raise HTTPException(404, "不存在")
        douban_id = row["douban_id"]
        if not douban_id:
            raise HTTPException(400, "请先填写或通过 ISBN 查找豆瓣编号")
        if not re.fullmatch(r"\d+", douban_id):
            raise HTTPException(400, "豆瓣编号须为数字")
        try:
            path = douban.fetch_cover_local(douban_id, directory)
        except RuntimeError as e:
            raise HTTPException(502, str(e)) from e
    return {"has_cover": path is not None, "douban_id": douban_id}


@router.post("/api/books/{bid}/douban-id")
def book_douban_id_lookup(request: Request, bid: int):
    with conn_of(request) as conn:
        row = conn.execute("SELECT isbn, douban_id FROM books WHERE id = ?", (bid,)).fetchone()
        if not row:
            raise HTTPException(404, "不存在")
        if not row["isbn"]:
            raise HTTPException(400, "请先填写 ISBN")
        if row["douban_id"]:
            raise HTTPException(409, "已有豆瓣编号，请先清空后再查找")
        try:
            douban_id = douban.lookup_subject_by_isbn(row["isbn"])
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
        except RuntimeError as e:
            raise HTTPException(502, str(e)) from e
        if not dbmod.save_douban_id_if_missing(conn, bid, row["isbn"], douban_id):
            raise HTTPException(409, "书目的 ISBN 或豆瓣编号已变化，请刷新后重试")
        return {"douban_id": douban_id}


@router.get("/api/covers")
def covers_list(request: Request):
    return sorted(local_cover_stems(covers_dir(request)))


@router.get("/cover/{stem}")
def cover_file(request: Request, stem: str):
    directory = covers_dir(request)
    for ext in douban.EXTS:
        path = directory / f"{stem}.{ext}"
        if path.exists():
            return FileResponse(path)
    raise HTTPException(404, "no cover")
