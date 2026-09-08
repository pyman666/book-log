"""解析 Notion 导出的图书 md：YAML frontmatter 与 ~售出.md 静态表格。纯函数，无 IO。"""
import re

import yaml

WIKILINK_RE = re.compile(r"\[\[([^\]|]+)(?:\|[^\]]*)?\]\]")
_SEP_CELL_RE = re.compile(r":?-{2,}:?")


def split_frontmatter(text):
    """返回 (meta dict 或 None, 正文)。无 frontmatter 时 meta 为 None。"""
    if not text.startswith("---"):
        return None, text
    lines = text.split("\n")
    for i, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            meta = yaml.safe_load("\n".join(lines[1:i])) or {}
            return meta, "\n".join(lines[i + 1:]).lstrip("\n")
    return None, text


def strip_wiki(v):
    """'[[托尔斯泰]]'→'托尔斯泰'；'[[长篇|📙长篇]]'→'长篇'；'—'/空→None；列表递归。"""
    if v is None:
        return None
    if isinstance(v, list):
        return [x for x in (strip_wiki(i) for i in v) if x]
    s = str(v).strip()
    if not s or s == "—":
        return None
    m = WIKILINK_RE.search(s)
    return m.group(1).strip() if m else s


def parse_price(v):
    """'1.83'→1.83；'-0.00'→0.0（显式持平）；None/''/'—'→None（无价格，不是 0）。"""
    if v is None:
        return None
    s = str(v).strip()
    if not s or s == "—":
        return None
    return round(float(s), 2)


def _num(v, cast):
    if v is None:
        return None
    s = str(v).strip()
    return cast(s) if s else None


def _as_list(v):
    if v is None:
        return []
    return v if isinstance(v, list) else [v]


def _clean_str(v):
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def parse_book(text, default_status="in_library"):
    """frontmatter → 书 dict（字段与 db.save_book 的入参一致）。"""
    meta, _body = split_frontmatter(text)
    meta = meta or {}
    return {
        "title": str(meta.get("title") or "").strip(),
        "isbn": _clean_str(meta.get("isbn")),
        "price": parse_price(meta.get("price")),
        "importance": _num(meta.get("importance"), float),
        "progress": _num(meta.get("progress"), int),
        "rating": _num(meta.get("rating"), int),
        "status": default_status,
        "created": _clean_str(meta.get("created")),
        "last_modified": _clean_str(meta.get("last_modified")),
        "authors": strip_wiki(_as_list(meta.get("author"))) or [],
        "publishers": strip_wiki(_as_list(meta.get("publisher"))) or [],
        "categories": strip_wiki(_as_list(meta.get("category"))) or [],
        "platform": strip_wiki(meta.get("platform")),
    }


def parse_sold_table(text):
    """~售出.md 的 markdown 表格 → 书 dict 列表（status='sold', progress=-1, created=None）。"""
    books = []
    for line in text.split("\n"):
        line = line.strip()
        if not (line.startswith("|") and line.endswith("|")):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if not cells or not cells[0] or cells[0] == "书名":
            continue
        if all(_SEP_CELL_RE.fullmatch(c) for c in cells if c):
            continue
        if cells[0].replace("*", "").strip() == "合计":
            continue
        get = lambda i: cells[i] if len(cells) > i else ""
        books.append({
            "title": cells[0],
            "isbn": get(2) or None,
            "price": parse_price(get(1)),
            "importance": None,
            "progress": -1,
            "rating": None,
            "status": "sold",
            "created": None,
            "last_modified": None,
            "authors": strip_wiki(_as_list(get(4))) or [],
            "publishers": WIKILINK_RE.findall(get(5)) or [],
            "category": None,
            "platform": strip_wiki(get(3)),
        })
    return books
