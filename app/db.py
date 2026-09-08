"""SQLite schema 与图书数据访问。所有 SQL 集中于此，API 层不写 SQL。"""
import re
import sqlite3
from contextlib import contextmanager

from .paths import normalize_file_path

SCHEMA = """
CREATE TABLE IF NOT EXISTS authors (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, chinese INTEGER, nationality TEXT);
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
  read_at TEXT,                -- 阅读时间：只有读过（打过分）或人显式填过的才有值，其余 NULL
  last_modified TEXT,
  file_path TEXT,             -- "书名.md"（位于 raw/books/）；同名同作者的多个版本/批次共用一个文件
  douban_id TEXT,             -- 豆瓣 subject 号（封面真源，可经 og:image 重推）；前端拼 https://book.douban.com/subject/{id}/
  platform_id INTEGER REFERENCES platforms(id)
  -- category 为多对多（book_categories）：数据中 68 本书有多个分类
  -- 无唯一约束：售出书 created 同为 NULL，同书名多批次只能靠应用层规则去重
);
CREATE TABLE IF NOT EXISTS ai_cache (
  key TEXT PRIMARY KEY,        -- 书名文件路径 或 "yearly:<年>"
  mtime TEXT,                  -- 源文件 mtime（失效判断）；年度画像为 NULL
  model TEXT,
  text TEXT NOT NULL,
  updated TEXT
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
# 登记/阅读/更新时间是 Notion 文本日期串，按文本排序得字母序（April<December…）。
# _SORTABLE 的日期列改用 ts_key() 包一层，转成定宽 ISO「YYYY-MM-DD HH:MM」→ 字典序即时间序。
_MON_RE = re.compile(
    r"([A-Za-z]+)\s+(\d{1,2}),\s*(\d{4})(?:\s+(\d{1,2}):(\d{2}))?\s*([AP])M?", re.I)
_MON3 = {m: i for i, m in enumerate(
    "jan feb mar apr may jun jul aug sep oct nov dec".split(), 1)}
_SELECT_NAMES = """
  SELECT b.*, f.name AS platform
  FROM books b
  LEFT JOIN platforms f ON f.id = b.platform_id
"""
_SORTABLE = {"id": "b.id", "title": "b.title", "price": "b.price", "rating": "b.rating",
             "progress": "b.progress", "importance": "b.importance",
             "created": "ts_key(b.created)", "read_at": "ts_key(b.read_at)",
             "last_modified": "ts_key(b.last_modified)"}


def ts_key(s):
    """'April 27, 2024 11:32 AM' → '2024-04-27 11:32'（定宽，字典序=时间序）。
    None / 解析不出 → None（SQL NULL，SQLite 恒排 ASC 首 / DESC 尾，符合「没日期的沉底」）。"""
    if not s:
        return None
    m = _MON_RE.search(str(s))
    if not m:
        return None
    mon = _MON3.get(m.group(1)[:3].lower())
    if not mon:
        return None
    mo, d, y = mon, int(m.group(2)), int(m.group(3))
    if m.group(4) and m.group(6):     # 带时刻 → 24 小时
        h = int(m.group(4)) % 12 + (12 if m.group(6).upper() == "P" else 0)
        return f"{y:04d}-{mo:02d}-{d:02d} {h:02d}:{int(m.group(5)):02d}"
    return f"{y:04d}-{mo:02d}-{d:02d}"


def read_time(alias: str = "") -> str:
    """「有效阅读时间」的 SQL 表达式：read_at 有值用它，没值回落 created（登记日）。
    只用于聚合查询，绝不写回列——read_at 为 NULL 必须真的是「没记过」，否则曲线又只是
    购书曲线。回落是为了让刚打分的书（还没来得及填阅读日）不至于从年度筛选里消失。"""
    p = f"{alias}." if alias else ""
    return f"COALESCE(NULLIF({p}read_at, ''), {p}created)"


_M2M = (("book_authors", "authors", "authors", "author_id"),
        ("book_publishers", "publishers", "publishers", "publisher_id"),
        ("book_categories", "categories", "categories", "category_id"))


def get_db(path):
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.create_function("year_of", 1, year_of)   # 所有连接共享的 SQL 函数
    conn.create_function("ts_key", 1, ts_key)     # 日期列排序键（见 _SORTABLE）
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
    cols = {r[1] for r in conn.execute("PRAGMA table_info(books)")}
    if "douban_id" not in cols:  # 存量库迁移
        conn.execute("ALTER TABLE books ADD COLUMN douban_id TEXT")
    if "read_at" not in cols:
        conn.execute("ALTER TABLE books ADD COLUMN read_at TEXT")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_book_read_at ON books(read_at)")
    _migrate_read_at(conn)
    if "cover_url" in cols:  # 封面已改为“磁盘文件存在性”，废弃 cover_url 列（douban_id 为真源）
        conn.execute("ALTER TABLE books DROP COLUMN cover_url")
    acols = {r[1] for r in conn.execute("PRAGMA table_info(authors)")}
    if "chinese" not in acols:  # 作者国籍（app.ai.gen.ensure_author_meta 填充）
        conn.execute("ALTER TABLE authors ADD COLUMN chinese INTEGER")
    if "nationality" not in acols:
        conn.execute("ALTER TABLE authors ADD COLUMN nationality TEXT")
    for row in conn.execute("SELECT id, file_path FROM books WHERE file_path LIKE 'raw/books/%'").fetchall():
        conn.execute("UPDATE books SET file_path = ? WHERE id = ?",
                     (normalize_file_path(row["file_path"]), row["id"]))
    conn.commit()


# user_version 迁移位图：v2 = 已收敛 read_at 的 created 回填（只留打过分的书）
_READ_AT_CLEANED = 2


def _migrate_read_at(conn):
    """治理 read_at 污染：当初新增这一列时没数据可用，就把 created 无条件回填了进去，
    于是「读过的书」和「只买没读的书」在库里长得一样（317/317 条 read_at == created），
    曲线只是购书曲线。一次性收敛：打过分（=读过）的书保留 created 当阅读时间，其余清回
    NULL。写入侧从此不再有默认值，read_at 只能是人填的。
    ⚠ 只跑一次（user_version）：跨这个迁移回滚代码不会自动重跑治理——老代码的无条件回填
    会把污染复位，再升回来时版本已是 2、治理跳过；回滚过就要手动 `PRAGMA user_version = 1`
    再启动一次。年度画像的旧文本同时作废：它的取书口径跟着改成「只算读过的书」，可重生成。"""
    if conn.execute("PRAGMA user_version").fetchone()[0] >= _READ_AT_CLEANED:
        return
    conn.execute("UPDATE books SET read_at = NULL "
                 "WHERE rating IS NULL AND created IS NOT NULL AND read_at = created")
    conn.execute("DELETE FROM ai_cache WHERE key LIKE 'yearly:%'")
    conn.execute(f"PRAGMA user_version = {_READ_AT_CLEANED}")


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
               created=?, read_at=?, last_modified=?, file_path=?, douban_id=?, platform_id=?
           WHERE id=?""",
        (b.get("isbn"), b.get("price"), b.get("importance"), b.get("progress"), b.get("rating"),
         b.get("status") or "in_library", b.get("created"), b.get("read_at"), b.get("last_modified"),
         normalize_file_path(b.get("file_path")), b.get("douban_id") or None,
         _dim(conn, "platforms", b.get("platform")), bid))
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
                              created, read_at, last_modified, file_path, douban_id, platform_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (title, b.get("isbn"), b.get("price"), b.get("importance"), b.get("progress"),
         b.get("rating"), b.get("status") or "in_library", created, b.get("read_at"),
         b.get("last_modified"),
         normalize_file_path(b.get("file_path")), b.get("douban_id") or None,
         _dim(conn, "platforms", b.get("platform"))))
    bid = cur.lastrowid
    _replace_m2m(conn, bid, b)
    conn.commit()
    return bid


def _shape(conn, row):
    bid = row["id"]
    return {
        "id": bid, "title": row["title"], "isbn": row["isbn"], "price": row["price"],
        "importance": row["importance"], "progress": row["progress"], "rating": row["rating"],
        "status": row["status"], "created": row["created"], "read_at": row["read_at"],
        "last_modified": row["last_modified"],
        "file_path": row["file_path"], "douban_id": row["douban_id"],
        "platform": row["platform"],
        "authors": _names(conn, "book_authors", "authors", "authors", "author_id", bid),
        "nationalities": [r[0] for r in conn.execute(
            "SELECT DISTINCT a.nationality FROM book_authors ba JOIN authors a ON a.id=ba.author_id "
            "WHERE ba.book_id=? AND a.nationality IS NOT NULL AND a.nationality != '' "
            "ORDER BY a.nationality", (bid,))],
        # 作者 → 国籍 映射：书单页国籍弹层按作者逐个编辑（作者行跨书共享，改动全局生效）
        "author_nationalities": {r[0]: r[1] for r in conn.execute(
            "SELECT a.name, a.nationality FROM book_authors ba "
            "JOIN authors a ON a.id=ba.author_id WHERE ba.book_id=?", (bid,))},
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
               status=None, nationality=None, min_price=None, max_price=None, min_rating=None,
               year=None, sort="id", desc=False, page=1, page_size=50):
    where, args = ["1=1"], []
    if q:
        where.append("(b.title LIKE ? OR b.isbn = ?)")
        args += [f"%{q}%", q]
    if year:
        where.append(f"year_of({read_time('b')}) = ?"); args.append(year)
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
    if nationality:
        where.append("EXISTS (SELECT 1 FROM book_authors ba JOIN authors a ON a.id = ba.author_id "
                     "WHERE ba.book_id = b.id AND a.nationality = ?)")
        args.append(nationality)
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
    # 维度值只取「挂到至少一本书」的——孤立行（如测试/导入残留、作者没配书）不该出现在筛选里
    authors = [r[0] for r in conn.execute(
        "SELECT DISTINCT a.name FROM authors a JOIN book_authors ba ON ba.author_id=a.id "
        "ORDER BY a.name")]
    publishers = [r[0] for r in conn.execute(
        "SELECT DISTINCT p.name FROM publishers p JOIN book_publishers bp ON bp.publisher_id=p.id "
        "ORDER BY p.name")]
    categories = [r[0] for r in conn.execute(
        "SELECT DISTINCT c.name FROM categories c JOIN book_categories bc ON bc.category_id=c.id "
        "ORDER BY c.name")]
    platforms = [r[0] for r in conn.execute(
        "SELECT DISTINCT f.name FROM platforms f JOIN books b ON b.platform_id=f.id "
        "ORDER BY f.name")]
    nats = [r[0] for r in conn.execute(
        "SELECT DISTINCT a.nationality FROM authors a JOIN book_authors ba ON ba.author_id=a.id "
        "WHERE a.nationality IS NOT NULL AND a.nationality != '' AND a.nationality != '未知' "
        "ORDER BY a.nationality")]
    years = [r[0] for r in conn.execute(
        f"SELECT DISTINCT year_of({read_time()}) FROM books "
        f"WHERE year_of({read_time()}) IS NOT NULL ORDER BY 1 DESC")]
    return {"categories": categories, "platforms": platforms,
            "authors": authors, "publishers": publishers,
            "nationalities": nats, "years": years}


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
    """按维度聚合。by: category|platform|author|publisher|year|rating|nationality；
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
        # 国籍：按作者国名（authors.nationality，ensure_author_meta 填充）；
        # 未判定/空的归「未标注」；多国籍书在每个国家各计一次（同 author 维度语义）
        "nationality": "SELECT b.id, b.price, b.rating, "
                       "COALESCE(NULLIF(a.nationality, ''), '未标注') AS key FROM books b "
                       "JOIN book_authors ba ON ba.book_id=b.id JOIN authors a ON a.id=ba.author_id",
        "year": f"SELECT b.id, b.price, b.rating, year_of({read_time('b')}) AS key FROM books b",
        "rating": "SELECT b.id, b.price, b.rating, b.rating AS key FROM books b",
    }[by]
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
