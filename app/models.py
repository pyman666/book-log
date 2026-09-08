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
    platform: Optional[str] = None


class AuthorNatIn(BaseModel):
    """按作者名批量设置国籍：{作者名: 国籍}（空串=清空）。作者行跨书共享，改动全局生效。"""
    nationalities: Dict[str, str]

