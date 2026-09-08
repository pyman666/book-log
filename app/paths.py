"""书库文件路径的存储格式与磁盘解析。"""
from pathlib import Path

BOOKS_REL = Path("raw") / "books"
_LEGACY_PREFIX = "raw/books/"


def normalize_file_path(file_path):
    """数据库只存 raw/books 下的文件名；兼容旧的仓库相对路径。"""
    if not file_path:
        return file_path
    value = str(file_path).replace("\\", "/")
    if value.startswith(_LEGACY_PREFIX):
        value = value[len(_LEGACY_PREFIX):]
    return value


def resolve_book_path(root, file_path):
    """把数据库中的文件名解析到 raw/books，并阻止路径逃逸。"""
    if not file_path:
        return None
    root = Path(root).resolve()
    books = (root / BOOKS_REL).resolve()
    value = str(file_path).replace("\\", "/")
    if value.startswith(_LEGACY_PREFIX):
        base, relative = books, value[len(_LEGACY_PREFIX):]
    elif value.startswith("raw/"):
        base, relative = root, value
    else:
        base, relative = books, value
    path = (base / relative).resolve()
    allowed = root if base == root else books
    if not path.is_relative_to(allowed):
        raise ValueError("非法书籍文件路径")
    return path



