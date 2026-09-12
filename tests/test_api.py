import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture


def client(tmp_path):
    (tmp_path / "raw").mkdir()
    return TestClient(create_app(tmp_path / "t.db", tmp_path))


def test_crud_roundtrip(client):
    bid = client.post("/api/books", json={
        "title": "API书", "price": 2.5, "authors": ["作者X"],
        "categories": ["科幻"], "created": "June 1, 2024 8:00 AM"}).json()
    assert isinstance(bid, int)
    b = client.get(f"/api/books/{bid}").json()
    assert b["title"] == "API书" and b["price"] == 2.5
    assert b["authors"] == ["作者X"] and b["categories"] == ["科幻"]
    r = client.put(f"/api/books/{bid}", json={"rating": 9})
    assert r.status_code == 200
    b = client.get(f"/api/books/{bid}").json()
    assert b["rating"] == 9 and b["price"] == 2.5          # 部分更新保留旧值
    r = client.put(f"/api/books/{bid}", json={"price": None})  # 显式清空
    assert r.status_code == 200
    assert client.get(f"/api/books/{bid}").json()["price"] is None
    assert client.delete(f"/api/books/{bid}").status_code == 200
    assert client.get(f"/api/books/{bid}").status_code == 404


def test_create_requires_title(client):
    assert client.post("/api/books", json={"title": "  "}).status_code == 400


def test_list_filters(client):
    client.post("/api/books", json={"title": "甲", "price": 5, "categories": ["科幻"]})
    client.post("/api/books", json={"title": "乙", "price": -2, "categories": ["传记", "科幻"], "authors": ["张"]})
    assert client.get("/api/books", params={"category": "传记"}).json()["total"] == 1
    assert client.get("/api/books", params={"category": "科幻"}).json()["total"] == 2   # 多分类各计
    assert client.get("/api/books", params={"author": "张"}).json()["total"] == 1
    assert client.get("/api/books", params={"q": "甲"}).json()["total"] == 1
    assert client.get("/api/books", params={"min_price": 0}).json()["total"] == 1
    data = client.get("/api/books", params={"sort": "price", "desc": "true"}).json()
    assert [x["title"] for x in data["items"]] == ["甲", "乙"]
    assert data["total"] == 2


def test_content_endpoint(client, tmp_path):
    (tmp_path / "raw" / "books").mkdir(parents=True)
    (tmp_path / "raw" / "books" / "有正文.md").write_text("# 标题\n正文内容", encoding="utf-8")
    bid = client.post("/api/books", json={"title": "有正文"}).json()
    r = client.get(f"/api/books/{bid}/content")
    assert r.status_code == 200 and "正文内容" in r.text
    bid2 = client.post("/api/books", json={"title": "无正文"}).json()
    assert client.get(f"/api/books/{bid2}/content").status_code == 404


def test_content_strips_douban_header(client, tmp_path):
    hdr = '> **[《📖 某书](https://book.douban.com/subject/123/)**\n> 内容简介…\n\n'
    (tmp_path / "raw" / "books").mkdir(parents=True)
    (tmp_path / "raw" / "books" / "仅豆瓣头.md").write_text(hdr, encoding="utf-8")
    b1 = client.post("/api/books", json={"title": "仅豆瓣头"}).json()
    assert client.get(f"/api/books/{b1}/content").status_code == 404
    (tmp_path / "raw" / "books" / "豆瓣头加笔记.md").write_text(hdr + "# 我的笔记\n很好看", encoding="utf-8")
    b2 = client.post("/api/books", json={"title": "豆瓣头加笔记"}).json()
    r = client.get(f"/api/books/{b2}/content")
    assert r.status_code == 200 and "我的笔记" in r.text and "douban" not in r.text


def test_content_ignores_client_sent_path(client, tmp_path):
    """库里不再有 file_path：客户端传什么都不认，只按命名法推导，路径穿越无从下手。"""
    (tmp_path / "secret.txt").write_text("secret", encoding="utf-8")
    bid = client.post("/api/books", json={"title": "穿越", "file_path": "../secret.txt"}).json()
    assert client.get(f"/api/books/{bid}/content").status_code == 404


def test_facets(client):
    client.post("/api/books", json={"title": "甲", "authors": ["张"],
                                    "categories": ["科幻"], "platform": "京东"})
    f = client.get("/api/facets").json()
    assert f["categories"] == ["科幻"] and f["authors"] == ["张"]
    assert f["platforms"] == ["京东"] and f["publishers"] == []


def test_list_nationality_filter(client):
    from app import db as dbmod
    client.post("/api/books", json={"title": "甲", "authors": ["余华"],
                                    "created": "April 27, 2024 11:32 AM"})
    client.post("/api/books", json={"title": "乙", "authors": ["加缪"]})
    with dbmod.db_conn(client.app.state.db_path) as c:
        c.execute("UPDATE authors SET nationality='中国' WHERE name='余华'")
        c.execute("UPDATE authors SET nationality='法国' WHERE name='加缪'")
        c.commit()
    d = client.get("/api/books", params={"nationality": "中国"}).json()
    assert d["total"] == 1 and d["items"][0]["title"] == "甲"
    assert d["items"][0]["nationalities"] == ["中国"]   # _shape 带出国籍
    f = client.get("/api/facets").json()
    assert f["nationalities"] == ["中国", "法国"]
    assert f["years"] == [2024]                          # 年度筛选选项
    assert client.get("/api/books", params={"year": 2024}).json()["total"] == 1


def test_douban_id(client):
    bid = client.post("/api/books", json={"title": "丙", "douban_id": "12345"}).json()
    assert client.get(f"/api/books/{bid}").json()["douban_id"] == "12345"
    assert client.get("/api/books").json()["items"][0]["douban_id"] == "12345"
    # PUT 不带该字段时保留（老客户端不清空）；带空串时清空
    assert client.put(f"/api/books/{bid}", json={"rating": 8}).json()["douban_id"] == "12345"
    assert client.put(f"/api/books/{bid}", json={"douban_id": ""}).json()["douban_id"] is None

# ---------- 仪表盘分析 ----------


def _seed(client):
    client.post("/api/books", json={"title": "活着", "authors": ["余华"], "categories": ["长篇"],
        "rating": 9, "importance": 0.9, "price": 50, "created": "April 27, 2024 11:32 AM"})
    client.post("/api/books", json={"title": "局外人", "authors": ["阿尔贝·加缪"], "categories": ["长篇"],
        "rating": 8, "importance": 0.5, "price": -20, "created": "January 5, 2023 9:00 AM"})
    client.post("/api/books", json={"title": "八月HALF", "authors": ["宝春溪"], "categories": ["传记"],
        "rating": 7, "importance": 0.8, "price": 40, "created": "April 27, 2024 11:32 AM"})


def test_list_year_filter(client):
    _seed(client)
    assert client.get("/api/books", params={"year": 2024}).json()["total"] == 2
    assert client.get("/api/books", params={"year": 2023}).json()["total"] == 1

# ---------- AI ----------


def test_cover_endpoint(client, monkeypatch):
    """单本抓封面：douban_id+isbn → 下载落盘；占位图→不落盘 has_cover=False。"""
    import app.douban as dmod
    monkeypatch.setattr(dmod, "fetch_cover_url",
                        lambda i, **k: f"https://img3.doubanio.com/view/subject/s/public/s{i}.jpg")
    monkeypatch.setattr(dmod, "_download", lambda u, **k: b"bytes")
    b0 = client.post("/api/books", json={"title": "无豆瓣号"}).json()
    assert client.post(f"/api/books/{b0}/cover").status_code == 400
    b1 = client.post("/api/books", json={"title": "有书", "douban_id": "999", "isbn": "978999"}).json()
    assert client.post(f"/api/books/{b1}/cover").json() == {"has_cover": True, "isbn": "978999"}
    root = client.app.state.root
    assert (root / "raw/covers/978999.jpg").read_bytes() == b"bytes"
    assert client.get("/cover/978999").status_code == 200        # 动态路由伺服本地文件
    assert "978999" in client.get("/api/covers").json()
    # 豆瓣无真封面（占位图）→ 不存脏图
    monkeypatch.setattr(dmod, "fetch_cover_url",
                        lambda i, **k: "https://img1.doubanio.com/cuphead/book-static/x.gif")
    b2 = client.post("/api/books", json={"title": "占位", "douban_id": "888", "isbn": "978888"}).json()
    assert client.post(f"/api/books/{b2}/cover").json() == {"has_cover": False, "isbn": "978888"}
    assert not (root / "raw/covers/978888.jpg").exists()


def test_cover_network_error_is_502(client, monkeypatch):
    """httpx 网络异常（超时/断连）被包成 RuntimeError → 路由 502，而不是裸 500。"""
    import httpx
    import app.douban as dmod
    def neterr(*a, **k): raise httpx.ConnectError("断网")
    monkeypatch.setattr(dmod.httpx, "get", neterr)
    b1 = client.post("/api/books", json={"title": "有豆瓣号", "douban_id": "999"}).json()
    assert client.post(f"/api/books/{b1}/cover").status_code == 502
