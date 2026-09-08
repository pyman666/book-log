from app import db as dbmod
from app.db import (get_db, get_book, init_db, list_books, save_book, stats_group,
                    stats_summary, update_book)


def make(tmp_path):
    conn = get_db(tmp_path / "t.db")
    init_db(conn)
    return conn


def B(title="测试", **kw):
    b = {"title": title, "isbn": None, "price": None, "importance": None, "progress": None,
         "rating": None, "status": "in_library", "created": None, "read_at": None,
         "last_modified": None,
         "file_path": None, "authors": [], "publishers": [], "categories": [], "platform": None}
    b.update(kw)
    return b


def test_file_path_stores_book_filename_only(tmp_path):
    conn = make(tmp_path)
    bid = save_book(conn, B(title="路径书", file_path="raw/books/路径书.md"))
    assert get_book(conn, bid)["file_path"] == "路径书.md"


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
    conn.execute("INSERT INTO ai_cache (key, text) VALUES ('yearly:2024', '旧画像')")
    conn.execute("INSERT INTO ai_cache (key, text) VALUES ('活着.md', '单本摘要')")
    conn.execute("PRAGMA user_version = 1")                     # 回到治理前的库
    conn.commit()
    dbmod.init_db(conn)
    assert dict(conn.execute("SELECT title, read_at FROM books").fetchall()) == {
        "没读": None, "读过": "April 1, 2024 10:00 AM", "售出": None}
    # 年度画像旧文本随口径变更作废，单本摘要不受影响
    assert [r[0] for r in conn.execute(
        "SELECT key FROM ai_cache ORDER BY key")] == ["活着.md"]
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
    assert {row["key"] for row in stats_group(conn, "year")} == {2024, 2023}


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


def test_stub_absorption(tmp_path):
    """sync 建的存根（created 空、有 file_path）在后来的正式记录应被填充而不是新建。"""
    conn = make(tmp_path)
    save_book(conn, B(title="存根书", file_path="raw/存根书.md"))
    bid = save_book(conn, B(title="存根书", file_path="raw/存根书.md",
                            created="May 2, 2024 9:00 AM", price=5.0))
    assert conn.execute("SELECT COUNT(*) FROM books").fetchone()[0] == 1
    assert get_book(conn, bid)["created"] == "May 2, 2024 9:00 AM"


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


def test_summary_nulls(tmp_path):
    """NULL 价格不参与金额；正=亏损 负=净赚。"""
    conn = make(tmp_path)
    save_book(conn, B(title="a", price=5.0, rating=8))
    save_book(conn, B(title="b", price=-2.0))
    save_book(conn, B(title="c", progress=100))
    s = stats_summary(conn)
    assert s["net"] == 3.0
    assert s["loss"] == 5.0
    assert s["gain"] == 2.0
    assert s["priced"] == 2
    assert s["finished"] == 1
    assert s["in_lib"] == 3
    assert s["avg_rating"] == 8.0


def test_group_category_price(tmp_path):
    conn = make(tmp_path)
    save_book(conn, B(title="a", categories=["科幻"], price=10.0))
    save_book(conn, B(title="b", categories=["科幻"], price=-4.0))
    save_book(conn, B(title="c", categories=["传记"], price=1.0))
    d = {x["key"]: x["value"] for x in stats_group(conn, "category", "sum_price")}
    assert d["科幻"] == 6.0
    assert d["传记"] == 1.0


def test_group_multi_category_counts_each(tmp_path):
    """多分类书计入每个分类，但 count 不重复、sum 按分类各计一次。"""
    conn = make(tmp_path)
    save_book(conn, B(title="a", categories=["科幻", "经典"], price=4.0))
    d = {x["key"]: x["value"] for x in stats_group(conn, "category", "sum_price")}
    assert d["科幻"] == 4.0 and d["经典"] == 4.0
    assert stats_group(conn, "category", "count")[0]["value"] == 1


def test_group_year_and_rating(tmp_path):
    conn = make(tmp_path)
    save_book(conn, B(title="a", created="April 27, 2024 11:32 AM", rating=9))
    save_book(conn, B(title="b", created="October 7, 2023 3:29 PM"))
    dy = {str(x["key"]): x["value"] for x in stats_group(conn, "year", "count")}
    assert dy["2024"] == 1 and dy["2023"] == 1
    dr = {str(x["key"]): x["value"] for x in stats_group(conn, "rating", "count")}
    assert dr["9"] == 1 and dr["未评分"] == 1


def test_multi_author_no_double_count(tmp_path):
    """一书两作者：group by author 时 count 不重复，sum_price 不翻倍。"""
    conn = make(tmp_path)
    save_book(conn, B(title="双", authors=["甲", "乙"], price=3.0))
    da = {x["key"]: x for x in stats_group(conn, "author", "sum_price")}
    assert da["甲"]["value"] == 3.0
    assert da["乙"]["value"] == 3.0
    assert stats_group(conn, "author", "count")[0]["value"] == 1
