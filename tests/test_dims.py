"""字典维护：作者/标签/分类等词表的改名（含合并）与删除，不用改库。"""
import sqlite3

import pytest
from fastapi.testclient import TestClient

from app.db import _DIMS
from app.main import create_app


def client(tmp_path):
    (tmp_path / "raw").mkdir()
    return TestClient(create_app(tmp_path / "t.db", tmp_path))


def test_inventory_lists_orphans_but_facets_hide_them(tmp_path):
    c = client(tmp_path)
    bid = c.post("/api/books", json={"title": "甲", "authors": ["作者甲"], "tags": ["重读"]}).json()
    c.put(f"/api/books/{bid}", json={"tags": []})          # 摘掉 → 变成孤立行

    inv = c.get("/api/dims").json()
    assert {"name": "重读", "count": 0} in inv["tags"]      # 孤立行要看得见
    assert {"name": "作者甲", "count": 1} in inv["authors"]
    assert "重读" not in c.get("/api/facets").json()["tags"]  # facets 照旧只给挂到书上的


def test_rename_plain_and_merge(tmp_path):
    c = client(tmp_path)
    c.post("/api/books", json={"title": "甲", "authors": ["宫本一树"]})
    c.post("/api/books", json={"title": "乙", "authors": ["宫本一树"]})
    c.post("/api/books", json={"title": "丙", "authors": ["宫本一", "另一人"]})

    # 新值不存在 = 原地改名
    assert c.post("/api/dims/rename", json={"dim": "tags", "old": "重读", "new": "再读"}).status_code == 400
    c.post("/api/books", json={"title": "丁", "tags": ["重读"]})
    r = c.post("/api/dims/rename", json={"dim": "tags", "old": "重读", "new": "再读"}).json()
    assert r == {"name": "再读", "books": 1, "merged": False}

    # 新值已存在 = 合并：书目改指现有行，旧行删掉
    r = c.post("/api/dims/rename", json={"dim": "authors", "old": "宫本一树", "new": "宫本一"}).json()
    assert r == {"name": "宫本一", "books": 2, "merged": True}

    inv = c.get("/api/dims").json()
    assert [(x["name"], x["count"]) for x in inv["authors"]] == [("宫本一", 3), ("另一人", 1)]
    facets = c.get("/api/facets").json()
    assert "宫本一树" not in facets["authors"] and "宫本一" in facets["authors"]
    assert {r["key"] for r in c.get("/api/stats/group", params={"by": "author"}).json()} == {"宫本一", "另一人"}


def test_rename_validates(tmp_path):
    c = client(tmp_path)
    c.post("/api/books", json={"title": "甲", "authors": ["作者甲"]})
    bad = [("authors", "", "x"), ("authors", "作者甲", ""), ("authors", "作者甲", " 作者甲  "),
           ("authors", "不存在", "x"), ("bogus", "作者甲", "x")]
    for dim, old, new in bad:
        r = c.post("/api/dims/rename", json={"dim": dim, "old": old, "new": new})
        assert r.status_code == 400, (dim, old, new, r.text)


def test_delete_unbinds_but_keeps_the_book(tmp_path):
    c = client(tmp_path)
    c.post("/api/books", json={"title": "甲", "authors": ["作者甲"], "tags": ["重读", "长读"]})
    assert c.post("/api/dims/delete", json={"dim": "tags", "name": "重读"}).json() == {"name": "重读", "books": 1}

    b = c.get("/api/books/1").json()
    assert b["tags"] == ["长读"] and b["authors"] == ["作者甲"]
    assert c.get("/api/books", params={"page_size": 10}).json()["total"] == 1
    assert c.get("/api/facets").json()["tags"] == ["长读"]
    # 删完的不能再删，也不该 404 之外的状态
    assert c.post("/api/dims/delete", json={"dim": "tags", "name": "重读"}).status_code == 400


@pytest.mark.parametrize("dim", sorted(_DIMS))
def test_delete_any_dim_unbinds_without_leaving_an_empty_id(tmp_path, dim):
    """字典页删值（作者/出版社/分类/平台/标签同一套 delete_dim）：关联行整行摘掉，
    不是留一个空 id——书还在，只是少了这一栏。词表行与关联行都不留 NULL / 悬空引用。"""
    c = client(tmp_path)
    bid = c.post("/api/books", json={"title": "甲", dim: ["甲值", "乙值"]}).json()
    assert c.post("/api/dims/delete",
                  json={"dim": dim, "name": "甲值"}).json() == {"name": "甲值", "books": 1}

    b = c.get(f"/api/books/{bid}").json()
    assert b[dim] == ["乙值"]
    assert c.get("/api/facets").json()[dim] == ["乙值"]
    assert [x["name"] for x in c.get("/api/dims").json()[dim]] == ["乙值"]

    table, join, fk = _DIMS[dim]
    with sqlite3.connect(tmp_path / "t.db") as conn:
        assert conn.execute(
            f"SELECT COUNT(*) FROM {join} WHERE {fk} IS NULL").fetchone()[0] == 0
        assert conn.execute(
            f"SELECT COUNT(*) FROM {join} j LEFT JOIN {table} d ON d.id = j.{fk} "
            f"WHERE d.id IS NULL").fetchone()[0] == 0


def test_delete_author_drops_its_nationalities(tmp_path):
    c = client(tmp_path)
    bid = c.post("/api/books", json={"title": "甲", "authors": ["作者甲"]}).json()
    c.put(f"/api/books/{bid}/author-nationalities",
          json={"nationalities": {"作者甲": ["中国", "未知"]}})
    bid2 = c.post("/api/books", json={"title": "乙", "authors": ["作者乙"]}).json()
    c.put(f"/api/books/{bid2}/author-nationalities", json={"nationalities": {"作者乙": ["中国"]}})

    assert c.post("/api/dims/delete", json={"dim": "authors", "name": "作者甲"}).json() == {"name": "作者甲", "books": 1}
    nats = [x["name"] for x in c.get("/api/dims").json()["nationalities"]]
    assert nats == ["中国"]                                  # 只剩作者乙 的一个
    assert c.get("/api/books", params={"nationality": "中国"}).json()["total"] == 1


def test_nationality_dim_renames_and_deletes(tmp_path):
    c = client(tmp_path)
    c.post("/api/books", json={"title": "甲", "authors": ["作者甲"]})
    c.put("/api/books/1/author-nationalities", json={"nationalities": {"作者甲": ["日本"]}})

    r = c.post("/api/dims/rename", json={"dim": "nationality", "old": "日本", "new": "日本国"}).json()
    assert r["merged"] is False and r["books"] == 1
    assert c.get("/api/books/1").json()["nationalities"] == ["日本国"]

    assert c.post("/api/dims/delete", json={"dim": "nationality", "name": "日本国"}).json() == {"name": "日本国", "books": 1}
    assert c.get("/api/books/1").json()["nationalities"] == []
    assert c.get("/api/dims").json()["nationalities"] == []
