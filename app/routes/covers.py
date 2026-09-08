"""本地封面相关路由。"""
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

from .. import douban
from ..dependencies import conn_of, covers_dir, local_cover_stems

router = APIRouter()


@router.post("/api/books/{bid}/cover")
def book_cover_fill(request: Request, bid: int):
    directory = covers_dir(request)
    with conn_of(request) as conn:
        row = conn.execute("SELECT douban_id, isbn FROM books WHERE id = ?", (bid,)).fetchone()
        if not row:
            raise HTTPException(404, "不存在")
        if not row["douban_id"]:
            raise HTTPException(400, "无豆瓣号，无法抓封面")
        try:
            path = douban.fetch_cover_local(row["douban_id"], row["isbn"], directory)
        except RuntimeError as e:
            raise HTTPException(502, str(e))
    return {"has_cover": path is not None, "isbn": row["isbn"]}


@router.get("/api/covers")
def covers_list(request: Request):
    return sorted(local_cover_stems(covers_dir(request)))


@router.get("/cover/{isbn}")
def cover_file(request: Request, isbn: str):
    directory = covers_dir(request)
    for ext in douban.EXTS:
        path = directory / f"{isbn}.{ext}"
        if path.exists():
            return FileResponse(path)
    raise HTTPException(404, "no cover")


