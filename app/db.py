"""SQLite schema 与图书数据访问。所有 SQL 集中于此，API 层不写 SQL。"""
import re
import sqlite3
from contextlib import contextmanager

SCHEMA = """
CREATE TABLE IF NOT EXISTS authors (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE);
CREATE TABLE IF NOT EXISTS publishers (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE);
CREATE TABLE IF NOT EXISTS categories (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE);
CREATE TABLE IF NOT EXISTS platforms (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE);
CREATE TABLE IF NOT EXISTS books (
  id INTEGER PRIMARY KEY,
  title TEXT NOT NULL,
  isbn TEXT,
  price REAL,                 -- 花费-收入：正=净亏 负=净赚；NULL=无价格（不参与统计）
  importance REAL,
  progress INTEGER,           -- 100读完 / 0未读 / -1售出
  rating INTEGER,             -- 1~10
  status TEXT NOT NULL DEFAULT 'in_library',
  created TEXT,
  last_modified TEXT,
  file_path TEXT,             -- "raw/书名.md"，售出书为 NULL
  platform_id INTEGER REFERENCES platforms(id)
  -- category 为多对多（book_categories）：数据中 68 本书有多个分类
  -- 无唯一约束：售出书 created 同为 NULL，同书名多批次只能靠应用层规则去重
);
CREATE TABLE IF NOT EXISTS book_authors (
  book_id INTEGER REFERENCES books(id) ON DELETE CASCADE,
  author_id INTEGER REFERENCES authors(id),
  PRIMARY KEY (book_id, author_id));
CREATE TABLE IF NOT EXISTS book_publishers (
  book_id INTEGER REFERENCES books(id) ON DELETE CASCADE,
  publisher_id INTEGER REFERENCES publishers(id),
  PRIMARY KEY (book_id, publisher_id));
CREATE TABLE IF NOT EXISTS book_categories (
  book_id INTEGER REFERENCES books(id) ON DELETE CASCADE,
  category_id INTEGER REFERENCES categories(id),
  PRIMARY KEY (book_id, category_id));
CREATE INDEX IF NOT EXISTS ix_book_title ON books(title);
CREATE INDEX IF NOT EXISTS ix_book_status ON books(status);
CREATE INDEX IF NOT EXISTS ix_book_created ON books(created);
CREATE INDEX IF NOT EXISTS ix_bookcat_category ON book_categories(category_id);
"""

_YEAR_RE = re.compile(r"\b(19\d{2}|20\d{2})\b")
_SELECT_NAMES = """
  SELECT b.*, f.name AS platform
  FROM books b
  LEFT JOIN platforms f ON f.id = b.platform_id
"""
_SORTABLE = {"id": "b.id", "title": "b.title", "price": "b.price", "rating": "b.rating",
             "progress": "b.progress", "importance": "b.importance",
             "created": "b.created", "last_modified": "b.last_modified"}
_M2M = (("book_authors", "authors", "authors", "author_id"),
        ("book_publishers", "publishers", "publishers", "publisher_id"),
        ("book_categories", "categories", "categories", "category_id"))


def get_db(path):
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def db_conn(path):
    conn = get_db(path)
    try:
        yield conn
    finally:
        conn.close()


def init_db(conn):
    conn.executescript(SCHEMA)
    conn.commit()


def year_of(s):
    """'April 27, 2024 11:32 AM' → 2024；None/无年份 → None。"""
    if not s:
        return None
    m = _YEAR_RE.search(str(s))
    return int(m.group(1)) if m else None


def _dim(conn, table, name):
    if not name:
        return None
    row = conn.execute(f"SELECT id FROM {table} WHERE name = ?", (name,)).fetchone()
    if row:
        return row["id"]
    return conn.execute(f"INSERT INTO {table} (name) VALUES (?)", (name,)).lastrowid


def _names(conn, table, key, dim_table, fk, bid):
    return [r["name"] for r in conn.execute(
        f"SELECT d.name FROM {dim_table} d JOIN {table} j ON j.{fk} = d.id "
        f"WHERE j.book_id = ? ORDER BY d.name", (bid,))]


def _replace_m2m(conn, bid, b):
    for table, key, dim_table, fk in _M2M:
        conn.execute(f"DELETE FROM {table} WHERE book_id = ?", (bid,))
        for name in b.get(key) or []:
            conn.execute(f"INSERT OR IGNORE INTO {table} (book_id, {fk}) VALUES (?, ?)",
                         (bid, _dim(conn, dim_table, name)))


def _apply(conn, bid, b):
    conn.execute(
        """UPDATE books SET isbn=?, price=?, importance=?, progress=?, rating=?, status=?,
               created=?, last_modified=?, file_path=?, platform_id=?
           WHERE id=?""",
        (b.get("isbn"), b.get("price"), b.get("importance"), b.get("progress"), b.get("rating"),
         b.get("status") or "in_library", b.get("created"), b.get("last_modified"),
         b.get("file_path"), _dim(conn, "platforms", b.get("platform")), bid))
    _replace_m2m(conn, bid, b)
    conn.commit()


def save_book(conn, b):
    """写一条书，返回 id。去重规则（无唯一约束，纯应用层）：
    - created 非空：title+created+last_modified 相同 = 同一记录（沿用旧去重标准）；
      若存在同名"同步存根"（created 空、有 file_path）则填充它；
    - created 空（售出书等）：一律新增——同书名可能有多批次。"""
    title, created = b["title"], b.get("created")
    if created:
        stub = conn.execute(
            "SELECT id FROM books WHERE title = ? AND created IS NULL AND file_path IS NOT NULL",
            (title,)).fetchone()
        if stub:
            _apply(conn, stub["id"], b)
            return stub["id"]
        row = conn.execute(
            "SELECT id FROM books WHERE title = ? AND created = ? AND last_modified IS ?",
            (title, created, b.get("last_modified"))).fetchone()
        if row:
            _apply(conn, row["id"], b)
            return row["id"]
    cur = conn.execute(
        """INSERT INTO books (title, isbn, price, importance, progress, rating, status,
                              created, last_modified, file_path, platform_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (title, b.get("isbn"), b.get("price"), b.get("importance"), b.get("progress"),
         b.get("rating"), b.get("status") or "in_library", created, b.get("last_modified"),
         b.get("file_path"), _dim(conn, "platforms", b.get("platform"))))
    bid = cur.lastrowid
    _replace_m2m(conn, bid, b)
    conn.commit()
    return bid


def _shape(conn, row):
    bid = row["id"]
    return {
        "id": bid, "title": row["title"], "isbn": row["isbn"], "price": row["price"],
        "importance": row["importance"], "progress": row["progress"], "rating": row["rating"],
        "status": row["status"], "created": row["created"], "last_modified": row["last_modified"],
        "file_path": row["file_path"], "platform": row["platform"],
        "authors": _names(conn, "book_authors", "authors", "authors", "author_id", bid),
        "publishers": _names(conn, "book_publishers", "publishers", "publishers", "publisher_id", bid),
        "categories": _names(conn, "book_categories", "categories", "categories", "category_id", bid),
    }


def get_book(conn, bid):
    row = conn.execute(_SELECT_NAMES + " WHERE b.id = ?", (bid,)).fetchone()
    return _shape(conn, row) if row else None


def update_book(conn, bid, fields):
    """按 id 部分更新：只更新 fields 里的键（含 None = 显式清空）。title 不可改。"""
    fields = {k: v for k, v in fields.items() if k != "title"}
    row = conn.execute(_SELECT_NAMES + " WHERE b.id = ?", (bid,)).fetchone()
    if not row:
        return None
    b = _shape(conn, row)
    b.update(fields)
    _apply(conn, bid, b)
    return get_book(conn, bid)


def list_books(conn, q=None, category=None, author=None, publisher=None, platform=None,
               status=None, min_price=None, max_price=None, min_rating=None,
               sort="id", desc=False, page=1, page_size=50):
    where, args = ["1=1"], []
    if q:
        where.append("(b.title LIKE ? OR b.isbn = ?)")
        args += [f"%{q}%", q]
    if platform:
        where.append("f.name = ?"); args.append(platform)
    if status:
        where.append("b.status = ?"); args.append(status)
    if min_price is not None:
        where.append("b.price >= ?"); args.append(min_price)
    if max_price is not None:
        where.append("b.price <= ?"); args.append(max_price)
    if min_rating is not None:
        where.append("b.rating >= ?"); args.append(min_rating)
    if author:
        where.append("EXISTS (SELECT 1 FROM book_authors ba JOIN authors a ON a.id = ba.author_id "
                     "WHERE ba.book_id = b.id AND a.name = ?)")
        args.append(author)
    if publisher:
        where.append("EXISTS (SELECT 1 FROM book_publishers bp JOIN publishers p ON p.id = bp.publisher_id "
                     "WHERE bp.book_id = b.id AND p.name = ?)")
        args.append(publisher)
    if category:
        where.append("EXISTS (SELECT 1 FROM book_categories bc JOIN categories c ON c.id = bc.category_id "
                     "WHERE bc.book_id = b.id AND c.name = ?)")
        args.append(category)
    base = f" FROM books b LEFT JOIN platforms f ON f.id = b.platform_id WHERE {' AND '.join(where)}"
    total = conn.execute(f"SELECT COUNT(*){base}", args).fetchone()[0]
    order = f"{_SORTABLE.get(sort, 'b.id')} {'DESC' if desc else 'ASC'}, b.id"
    rows = conn.execute(
        f"SELECT b.*, f.name AS platform{base} "
        f"ORDER BY {order} LIMIT ? OFFSET ?", args + [page_size, (page - 1) * page_size]).fetchall()
    return {"total": total, "page": page, "page_size": page_size,
            "items": [_shape(conn, r) for r in rows]}


def facets(conn):
    col = lambda t: [r[0] for r in conn.execute(f"SELECT name FROM {t} ORDER BY name")]
    return {"categories": col("categories"), "platforms": col("platforms"),
            "authors": col("authors"), "publishers": col("publishers")}


def stats_summary(conn):
    r = conn.execute(
        """SELECT SUM(status = 'in_library') AS in_lib,
                  SUM(status = 'sold') AS sold,
                  SUM(progress = 100) AS finished,
                  AVG(rating) AS avg_rating,
                  SUM(price) AS net,
                  SUM(CASE WHEN price > 0 THEN price END) AS loss,
                  SUM(CASE WHEN price < 0 THEN -price END) AS gain,
                  SUM(price IS NOT NULL) AS priced
           FROM books""").fetchone()
    return {k: (round(v, 2) if isinstance(v, float) else v) for k, v in dict(r).items()}


def stats_group(conn, by, agg="count"):
    """按维度聚合。by: category|platform|author|publisher|year|rating；
    agg: count|sum_price|avg_rating。NULL 价格不参与金额；多值维度不重复计数同一本书。"""
    if agg not in ("count", "sum_price", "avg_rating"):
        raise ValueError(f"bad agg: {agg}")
    src = {
        "category": "SELECT b.id, b.price, b.rating, c.name AS key FROM books b "
                    "JOIN book_categories bc ON bc.book_id = b.id "
                    "JOIN categories c ON c.id = bc.category_id",
        "platform": "SELECT b.id, b.price, b.rating, f.name AS key FROM books b "
                    "LEFT JOIN platforms f ON f.id = b.platform_id",
        "author": "SELECT b.id, b.price, b.rating, a.name AS key FROM books b "
                  "JOIN book_authors ba ON ba.book_id = b.id JOIN authors a ON a.id = ba.author_id",
        "publisher": "SELECT b.id, b.price, b.rating, p.name AS key FROM books b "
                     "JOIN book_publishers bp ON bp.book_id = b.id JOIN publishers p ON p.id = bp.publisher_id",
        "year": "SELECT b.id, b.price, b.rating, year_of(b.created) AS key FROM books b",
        "rating": "SELECT b.id, b.price, b.rating, b.rating AS key FROM books b",
    }[by]
    if by == "year":
        conn.create_function("year_of", 1, year_of)
    default_label = {"rating": "未评分", "year": "未知"}.get(by, "未分类")
    groups = {}
    for r in conn.execute(src):
        key = r["key"] if r["key"] is not None else default_label
        g = groups.setdefault(key, {"ids": set(), "price": 0.0, "has_price": False, "ratings": []})
        if r["id"] not in g["ids"]:
            g["ids"].add(r["id"])
            if r["price"] is not None:
                g["price"] += r["price"]
                g["has_price"] = True
            if r["rating"] is not None:
                g["ratings"].append(r["rating"])
    out = []
    for key, g in groups.items():
        item = {"key": key, "count": len(g["ids"])}
        if agg == "sum_price":
            item["value"] = round(g["price"], 2) if g["has_price"] else None
        elif agg == "avg_rating":
            item["value"] = round(sum(g["ratings"]) / len(g["ratings"]), 2) if g["ratings"] else None
        else:
            item["value"] = len(g["ids"])
        out.append(item)
    out.sort(key=lambda x: (x["value"] is None, -(x["value"] or 0)))
    return out
