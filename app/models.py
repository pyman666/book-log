"""API 请求模型。"""
from typing import Dict, List, Optional

from pydantic import BaseModel


class BookIn(BaseModel):
    title: str = ""
    isbn: Optional[str] = None
    price: Optional[float] = None
    importance: Optional[float] = None
    progress: Optional[int] = None
    rating: Optional[int] = None
    status: Optional[str] = "in_library"
    created: Optional[str] = None
    read_at: Optional[str] = None
    last_modified: Optional[str] = None
    douban_id: Optional[str] = None
    authors: Optional[List[str]] = None
    publishers: Optional[List[str]] = None
    categories: Optional[List[str]] = None
    platforms: Optional[List[str]] = None
    tags: Optional[List[str]] = None


class AuthorNatIn(BaseModel):
    """按作者名批量设置国籍：{作者名: [国籍...]}（空列表=清空；一作者可多国籍）。
    作者行跨书共享，改动全局生效。"""
    nationalities: Dict[str, List[str]]


class DimOp(BaseModel):
    """字典维护（改名/合并、删除）。dim 取值见 db._DIMS + "nationality"；
    nationality 没有词表行，改的是挂在作者身上的文本值。"""
    dim: str
    name: str


class DimRename(BaseModel):
    """改名：new 已存在则合并过去（旧值删掉、关联改指新行），否则原地改名。"""
    dim: str
    old: str
    new: str

