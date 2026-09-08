"""路由共享依赖与小型请求辅助函数。"""
from pathlib import Path

from fastapi import Request

from . import db as dbmod
from . import douban


def conn_of(request: Request):
    return dbmod.db_conn(request.app.state.db_path)


def covers_dir(request: Request) -> Path:
    return request.app.state.covers_dir


def local_cover_stems(directory: Path) -> set:
    """返回已有本地封面的 ISBN 主干集合。"""
    if not directory.exists():
        return set()
    return {p.stem for p in directory.iterdir()
            if p.suffix.lower().lstrip(".") in douban.EXTS}


def strip_douban_header(text: str) -> str:
    """剥掉文件开头的豆瓣引用块。"""
    lines = text.splitlines()
    if not lines or "book.douban.com" not in lines[0]:
        return text
    i = 0
    while i < len(lines) and (lines[i].startswith(">") or not lines[i].strip()):
        i += 1
    return "\n".join(lines[i:]).strip()

