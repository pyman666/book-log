from app import db as dbmod
from app.db import get_db, get_book, init_db, list_books, save_book, update_book


def make(tmp_path):
    conn = get_db(tmp_path / "t.db")
    init_db(conn)
    return conn


def B(title="测试", **kw):
    b = {"title": title, "isbn": None, "price": None, "importance": None, "progress": None,
         "rating": None, "status": "in_library", "created": None, "read_at": None,
         "last_modified": None, "authors": [], "publishers": [], "categories": [], "platform": None}
    b.update(kw)
    return b


def test_legacy_file_path_column_is_dropped(tmp_path):
    """旧库残留的 file_path 列在启动时被丢掉：路径只从命名法推导，不再入库。"""
    conn = make(tmp_path)
    conn.execute("ALTER TABLE books ADD COLUMN file_path TEXT")
    conn.execute("UPDATE books SET file_path = '测试书.md'")
    conn.commit()
    init_db(conn)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(books)")}
    assert "file_path" not in cols


def test_read_at_has_no_default(tmp_path):
    """写入侧不设默认：回填 created 会把「只买没读」伪造成读过。"""
    conn = make(tmp_path)
    bid = save_book(conn, B(created="April 1, 2024 10:00 AM", rating=8))
    assert get_book(conn, bid)["read_at"] is None


def test_polluted_read_at_keeps_only_rated(tmp_path):
    """存量库治理：早期回填的 read_at 里，只有打过分的书保留 created，其余清回 NULL；
    user_version 保证只跑一次，事后显式填一个和 created 相同的值不会被抹掉。"""
    conn = make(tmp_path)
    save_book(conn, B(title="没读", created="April 1, 2024 10:00 AM"))
    save_book(conn, B(title="读过", created="April 1, 2024 10:00 AM", rating=8))
    save_book(conn, B(title="售出", rating=None))
    conn.execute("UPDATE books SET read_at = created WHERE created IS NOT NULL")  # 复现老迁移
    conn.execute("CREATE TABLE ai_cache (key TEXT PRIMARY KEY, text TEXT NOT NULL)")
    conn.execute("INSERT INTO ai_cache (key, text) VALUES ('yearly:2024', '旧画像')")
    conn.execute("PRAGMA user_version = 1")                     # 回到治理前的库
    conn.commit()
    dbmod.init_db(conn)
    assert dict(conn.execute("SELECT title, read_at FROM books").fetchall()) == {
        "没读": None, "读过": "April 1, 2024 10:00 AM", "售出": None}
    # AI 缓存表已下线：init_db 顺手把它从存量库 DROP 掉
    assert conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE name='ai_cache'").fetchone()[0] == 0
    conn.execute("UPDATE books SET read_at = created WHERE title = '没读'")
    conn.commit()
    dbmod.init_db(conn)                                         # 再启动一次，不二次抹值
    assert conn.execute("SELECT read_at FROM books WHERE title='没读'").fetchone()[0] \
        == "April 1, 2024 10:00 AM"


def test_read_at_can_differ_from_created(tmp_path):
    conn = make(tmp_path)
    bid = save_book(conn, B(created="April 1, 2023 10:00 AM", read_at="May 2, 2024"))
    book = get_book(conn, bid)
    assert book["created"] == "April 1, 2023 10:00 AM"
    assert book["read_at"] == "May 2, 2024"


def test_year_filters_use_read_time_with_created_fallback(tmp_path):
    """年度维度看「有效阅读时间」：read_at 有值算它，没值回落 created。"""
    conn = make(tmp_path)
    save_book(conn, B(title="按阅读年", created="April 1, 2023", read_at="May 2, 2024"))
    save_book(conn, B(title="只有登记日", created="April 1, 2024"))
    save_book(conn, B(title="另一年", created="April 1, 2022", read_at="May 2, 2023"))
    assert [i["title"] for i in list_books(conn, year=2024)["items"]] == ["按阅读年", "只有登记日"]
    assert dbmod.facets(conn)["years"] == [2024, 2023]


def test_save_and_get(tmp_path):
    conn = make(tmp_path)
    bid = save_book(conn, B(price=1.5, created="April 1, 2024 10:00 AM",
                            authors=["甲"], categories=["长篇"]))
    b = get_book(conn, bid)
    assert b["title"] == "测试"
    assert b["price"] == 1.5
    assert b["authors"] == ["甲"]
    assert b["categories"] == ["长篇"]


def test_upsert_same_key(tmp_path):
    conn = make(tmp_path)
    save_book(conn, B(created="April 1, 2024 10:00 AM", last_modified="May 2, 2024 9:00 AM", price=1.5))
    bid = save_book(conn, B(created="April 1, 2024 10:00 AM", last_modified="May 2, 2024 9:00 AM",
                            price=2.0, rating=9))
    assert conn.execute("SELECT COUNT(*) FROM books").fetchone()[0] == 1
    assert get_book(conn, bid)["price"] == 2.0
    assert get_book(conn, bid)["rating"] == 9


def test_different_last_modified_is_new_row(tmp_path):
    conn = make(tmp_path)
    save_book(conn, B(created="April 1, 2024 10:00 AM", last_modified="May 2, 2024 9:00 AM"))
    save_book(conn, B(created="April 1, 2024 10:00 AM", last_modified="June 3, 2024 9:00 AM"))
    assert conn.execute("SELECT COUNT(*) FROM books").fetchone()[0] == 2


def test_null_created_always_insert(tmp_path):
    """售出书多批次：同书名 + created 全 NULL 也要各占一行（边城卖过两次）。"""
    conn = make(tmp_path)
    save_book(conn, B(title="边城", status="sold", price=1.0))
    save_book(conn, B(title="边城", status="sold", price=3.0))
    assert conn.execute("SELECT COUNT(*) FROM books").fetchone()[0] == 2


def test_created_key_dedupe_survives_without_stubs(tmp_path):
    """没有存根归并规则之后，title+created+last_modified 仍是唯一的去重键。"""
    conn = make(tmp_path)
    b1 = save_book(conn, B(title="去重书", created="May 2, 2024 9:00 AM", price=5.0))
    b2 = save_book(conn, B(title="去重书", created="May 2, 2024 9:00 AM", price=6.0))
    assert b1 == b2 and conn.execute("SELECT COUNT(*) FROM books").fetchone()[0] == 1
    assert get_book(conn, b1)["price"] == 6.0


def test_list_filters(tmp_path):
    conn = make(tmp_path)
    save_book(conn, B(title="多作者", authors=["甲", "乙"], price=3.0, categories=["科幻"]))
    save_book(conn, B(title="单作者", authors=["甲"], price=1.0, categories=["传记"]))
    save_book(conn, B(title="无价书"))
    assert list_books(conn, author="甲")["total"] == 2
    assert list_books(conn, author="乙")["total"] == 1
    assert list_books(conn, category="科幻")["total"] == 1
    assert list_books(conn, q="多")["total"] == 1
    assert list_books(conn, min_price=0)["total"] == 2      # NULL 价格不参与
    assert list_books(conn, min_rating=9)["total"] == 0
    assert list_books(conn, status="in_library")["total"] == 3


def test_update_partial(tmp_path):
    conn = make(tmp_path)
    bid = save_book(conn, B(price=1.5, authors=["甲"]))
    update_book(conn, bid, {"rating": 9})
    b = get_book(conn, bid)
    assert b["rating"] == 9 and b["price"] == 1.5 and b["authors"] == ["甲"]
    update_book(conn, bid, {"price": None})                 # 显式清空
    assert get_book(conn, bid)["price"] is None
