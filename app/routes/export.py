"""导出路由：GET /api/export?format=csv|json —— 浏览器下载一整份活库。"""
from datetime import datetime

from fastapi import APIRouter, HTTPException, Request, Response

from .. import db as dbmod, export, notes
from ..dependencies import conn_of

router = APIRouter()

_FORMATS = {"csv": ("text/csv", "csv"), "json": ("application/json", "json")}


@router.get("/api/export")
def export_books(request: Request, format: str = "csv"):
    fmt = (format or "").lower()
    if fmt not in _FORMATS:
        raise HTTPException(400, "format 须为 csv 或 json")
    with conn_of(request) as conn:
        books = dbmod.all_books(conn)
        notes.annotate(conn, request.app.state.root, books)   # 笔记文件名靠推导，一并带走
    mime, ext = _FORMATS[fmt]
    body = export.to_csv(books) if fmt == "csv" else export.to_json(books)
    name = f"book-log-{datetime.now():%Y-%m-%d}.{ext}"
    return Response(body, media_type=f"{mime}; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})
