"""字典：维护作者 / 标签 / 分类 / 出版社 / 平台 / 国籍这些词表值。

书单页只能往书上「加值」，写错就得动库：这里补齐改名（含合并重复值）和删除，
让字典也能像书目一样在页面上维护。删除不碰书目本身，也不碰 raw/books/ 正文，
回收站快照里存的是名字，不受影响。
"""
from fastapi import APIRouter, HTTPException, Request

from .. import db as dbmod
from ..dependencies import conn_of
from ..models import DimOp, DimRename

router = APIRouter()


@router.get("/api/dims")
def dims_inventory(request: Request):
    """所有维度的取值清单，含 count=0 的孤立行——facets 只回挂到书上的值，
    拼错值没人引用时正好是这里要清理的对象。"""
    with conn_of(request) as conn:
        return dbmod.dim_inventory(conn)


@router.post("/api/dims/rename")
def rename_dim(payload: DimRename, request: Request):
    with conn_of(request) as conn:
        try:
            return dbmod.rename_dim(conn, payload.dim, payload.old, payload.new)
        except ValueError as e:
            raise HTTPException(400, str(e)) from e


@router.post("/api/dims/delete")
def delete_dim(payload: DimOp, request: Request):
    """用 POST 而不是 DELETE：DELETE 不带请求体，传不了 {dim, name}。"""
    with conn_of(request) as conn:
        try:
            return dbmod.delete_dim(conn, payload.dim, payload.name)
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
