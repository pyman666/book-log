"""回收站：删除 = 摘进 books_trash；恢复按快照重建；正文 md 从头到尾不动。"""
from fastapi.testclient import TestClient

from app.main import create_app


def client(tmp_path):
    (tmp_path / "raw").mkdir()
    return TestClient(create_app(tmp_path / "t.db", tmp_path))


def _book(c, **extra):
    payload = {"title": "回收书", "price": 12.5, "authors": ["作者甲"],
               "categories": ["科幻"], "tags": ["年度最佳"], "isbn": "9787000000001",
               "read_at": "2024-03-05", "rating": 9}
    payload.update(extra)
    return c.post("/api/books", json=payload).json()


def test_delete_hides_book_but_keeps_snapshot(tmp_path):
    c = client(tmp_path)
    bid = _book(c)
    created = c.get(f"/api/books/{bid}").json()["created"]

    assert c.delete(f"/api/books/{bid}").status_code == 200
    assert c.get(f"/api/books/{bid}").status_code == 404
    assert c.get("/api/books").json()["total"] == 0
    # 统计也立刻干净：回收站里的书不算花费（空库 SUM 返回 NULL）
    assert c.get("/api/stats/summary").json()["net"] is None

    items = c.get("/api/trash").json()["items"]
    assert len(items) == 1
    assert items[0]["title"] == "回收书" and items[0]["authors"] == ["作者甲"]

    new_id = c.post(f"/api/trash/{items[0]['id']}/restore").json()["id"]
    b = c.get(f"/api/books/{new_id}").json()
    assert b["title"] == "回收书" and b["price"] == 12.5
    assert b["authors"] == ["作者甲"] and b["categories"] == ["科幻"] and b["tags"] == ["年度最佳"]
    assert b["isbn"] == "9787000000001" and b["rating"] == 9 and b["read_at"] == "2024-03-05"
    assert b["created"] == created                    # 买书时间不因删了又恢复而变
    assert c.get("/api/trash").json()["items"] == []
    assert c.delete(f"/api/books/{new_id}").status_code == 200


def test_restored_book_gets_new_id_and_notes_still_resolve(tmp_path):
    c = client(tmp_path)
    (tmp_path / "raw" / "books").mkdir(parents=True)
    (tmp_path / "raw" / "books" / "有笔记.md").write_text("# 笔记\n很好看", encoding="utf-8")
    bid = _book(c, title="有笔记")

    assert c.get(f"/api/books/{bid}/content").status_code == 200
    c.delete(f"/api/books/{bid}")
    assert c.get(f"/api/books/{bid}/content").status_code == 404      # 书不在账上，正文也不归属
    assert (tmp_path / "raw" / "books" / "有笔记.md").is_file()       # 文件没动

    tid = c.get("/api/trash").json()["items"][0]["id"]
    new_id = c.post(f"/api/trash/{tid}/restore").json()["id"]
    # 恢复是重新插入：id 可能相同（空库时 max+1 又回到 1），也可能不同——都按新记录看
    assert c.get(f"/api/books/{new_id}/content").text == "# 笔记\n很好看"


def test_purge_is_permanent(tmp_path):
    c = client(tmp_path)
    bid = _book(c)
    c.delete(f"/api/books/{bid}")
    tid = c.get("/api/trash").json()["items"][0]["id"]
    assert c.delete(f"/api/trash/{tid}").status_code == 200
    assert c.get("/api/trash").json()["items"] == []
    assert c.delete(f"/api/trash/{tid}").status_code == 404
    assert c.post(f"/api/trash/{tid}/restore").status_code == 404


def test_missing_book_delete_and_restore_are_404(tmp_path):
    c = client(tmp_path)
    assert c.delete("/api/books/999").status_code == 404
    assert c.post("/api/trash/999/restore").status_code == 404
