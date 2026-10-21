"""回收站：书目的软删除、恢复、彻底删除。

删除进 books_trash 之后，活着的 books 表里没有它，列表/统计/仪表盘/笔记归属
全都不用改查询；恢复按快照重建（新 id）。正文 md 始终留在 raw/books/，
这两个接口都不碰文件。
"""
from fastapi import APIRouter, HTTPException, Request

from .. import db as dbmod
from ..dependencies import conn_of

router = APIRouter()


@router.get("/api/trash")
def list_trash(request: Request):
    with conn_of(request) as conn:
        return {"items": dbmod.list_trash(conn)}


@router.post("/api/trash/{tid}/restore")
def restore_book(request: Request, tid: int):
    with conn_of(request) as conn:
        try:
            new_id = dbmod.restore_book(conn, tid)
        except ValueError as e:
            raise HTTPException(400, str(e))
    if not new_id:
        raise HTTPException(404, "回收站里没有这条记录")
    return {"id": new_id}


@router.delete("/api/trash/{tid}")
def purge_book(request: Request, tid: int):
    with conn_of(request) as conn:
        if not dbmod.purge_book(conn, tid):
            raise HTTPException(404, "回收站里没有这条记录")
    return {"purged": tid}
