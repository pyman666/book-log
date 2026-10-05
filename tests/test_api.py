import pytest
from fastapi.testclient import TestClient

from app import db as dbmod
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


def test_update_title(client):
    """书名可改（raw/books/ 的 md 要人工同步改名）；改成空串拒绝。"""
    bid = client.post("/api/books", json={"title": "旧名"}).json()
    assert client.put(f"/api/books/{bid}", json={"title": " 新名 "}).json()["title"] == "新名"
    assert client.put(f"/api/books/{bid}", json={"title": "  "}).status_code == 400
    assert client.get(f"/api/books/{bid}").json()["title"] == "新名"   # 拒绝后不落库


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
                                    "categories": ["科幻"], "platforms": ["京东"]})
    f = client.get("/api/facets").json()
    assert f["categories"] == ["科幻"] and f["authors"] == ["张"]
    assert f["platforms"] == ["京东"] and f["publishers"] == []


def test_summary(client):
    client.post("/api/books", json={"title": "a", "price": 5.0, "categories": ["科幻"], "rating": 8})
    client.post("/api/books", json={"title": "b", "price": -2.0, "categories": ["科幻"]})
    client.post("/api/books", json={"title": "c", "progress": 100, "status": "sold", "price": 1.0})
    s = client.get("/api/stats/summary").json()
    assert s["in_lib"] == 2 and s["sold"] == 1
    assert s["finished"] == 1
    assert s["net"] == 4.0 and s["loss"] == 6.0 and s["gain"] == 2.0
    assert s["priced"] == 3 and s["avg_rating"] == 8.0


def test_group(client):
    client.post("/api/books", json={"title": "a", "price": 5.0, "categories": ["科幻"],
                                    "created": "April 27, 2024 11:32 AM", "rating": 9})
    client.post("/api/books", json={"title": "b", "price": -2.0, "categories": ["科幻"],
                                    "created": "October 7, 2023 3:29 PM"})
    g = client.get("/api/stats/group", params={"by": "category", "agg": "sum_price"}).json()
    assert g[0]["key"] == "科幻" and g[0]["value"] == 3.0
    dy = {str(x["key"]): x["value"] for x in
          client.get("/api/stats/group", params={"by": "year", "agg": "count"}).json()}
    assert dy["2024"] == 1 and dy["2023"] == 1
    dr = {str(x["key"]): x["value"] for x in
          client.get("/api/stats/group", params={"by": "rating", "agg": "count"}).json()}
    assert dr["9"] == 1
    assert client.get("/api/stats/group", params={"by": "nope"}).status_code == 400
    assert client.get("/api/stats/group", params={"by": "year", "agg": "bogus"}).status_code == 400


def _set_nats(conn, name, *nats):
    """按作者名写国籍（author_nationalities 关联表）：整组覆盖，和弹层接口同口径。"""
    aid = conn.execute("SELECT id FROM authors WHERE name = ?", (name,)).fetchone()[0]
    conn.execute("DELETE FROM author_nationalities WHERE author_id = ?", (aid,))
    conn.executemany("INSERT INTO author_nationalities (author_id, nationality) VALUES (?, ?)",
                     [(aid, n) for n in nats])


def test_group_nationality(client):
    from app import db as dbmod
    client.post("/api/books", json={"title": "甲", "authors": ["余华"], "price": 10})
    client.post("/api/books", json={"title": "乙", "authors": ["加缪"], "price": -4})
    client.post("/api/books", json={"title": "丙"})   # 无作者：不进国籍维度（JOIN）
    with dbmod.db_conn(client.app.state.db_path) as c:
        _set_nats(c, "余华", "中国")
        _set_nats(c, "加缪", "法国")
        c.commit()
    g = {x["key"]: x["value"] for x in
         client.get("/api/stats/group", params={"by": "nationality"}).json()}
    assert g == {"中国": 1, "法国": 1}
    gm = {x["key"]: x["value"] for x in
          client.get("/api/stats/group", params={"by": "nationality", "agg": "sum_price"}).json()}
    assert gm["中国"] == 10 and gm["法国"] == -4
    # 未判定（一条国籍都没有）归入「未标注」
    client.post("/api/books", json={"title": "丁", "authors": ["未判定作者"]})
    g2 = {x["key"]: x["value"] for x in
          client.get("/api/stats/group", params={"by": "nationality"}).json()}
    assert g2["未标注"] == 1


def test_list_nationality_filter(client):
    from app import db as dbmod
    client.post("/api/books", json={"title": "甲", "authors": ["余华"],
                                    "created": "April 27, 2024 11:32 AM"})
    client.post("/api/books", json={"title": "乙", "authors": ["加缪"],
                                    "created": "May 2, 2023 9:00 AM"})
    with dbmod.db_conn(client.app.state.db_path) as c:
        _set_nats(c, "余华", "中国")
        _set_nats(c, "加缪", "法国")
        c.commit()
    d = client.get("/api/books", params={"nationality": "中国"}).json()
    assert d["total"] == 1 and d["items"][0]["title"] == "甲"
    assert d["items"][0]["nationalities"] == ["中国"]   # _shape 带出国籍
    f = client.get("/api/facets").json()
    assert f["nationalities"] == ["中国", "法国"]
    assert f["years"] == [2024, 2023]                    # 年度筛选选项（按 created 降序）
    assert client.get("/api/books", params={"year": 2024}).json()["total"] == 1


def test_author_multi_nationality(client):
    """一个作者可挂多个国籍：_shape 给列表，两个国名都能筛到、都进分布图。"""
    bid = client.post("/api/books", json={"title": "双籍书", "authors": ["某人"], "price": 7}).json()
    with dbmod.db_conn(client.app.state.db_path) as c:
        _set_nats(c, "某人", "中国", "法国")
        c.commit()
    b = client.get(f"/api/books/{bid}").json()
    assert b["author_nationalities"] == {"某人": ["中国", "法国"]}
    assert b["nationalities"] == ["中国", "法国"]          # 书级并集，按国名排序
    for nat in ("中国", "法国"):
        assert client.get("/api/books", params={"nationality": nat}).json()["total"] == 1
    g = {x["key"]: x["value"] for x in
         client.get("/api/stats/group", params={"by": "nationality"}).json()}
    assert g == {"中国": 1, "法国": 1}                      # 两国各计一次
    f = client.get("/api/facets").json()
    assert f["author_nationalities"] == {"某人": ["中国", "法国"]}
    assert f["nationalities"] == ["中国", "法国"]


def test_put_author_nationalities(client):
    """弹层接口的值是列表：整组覆盖（不追加），空列表=清空；不在这本书作者里的人名不碰。"""
    bid = client.post("/api/books", json={"title": "改国籍", "authors": ["甲", "乙"]}).json()
    r = client.put(f"/api/books/{bid}/author-nationalities",
                   json={"nationalities": {"甲": ["中国", "美国"], "乙": ["法国"], "外人": ["德国"]}})
    assert r.status_code == 200
    b = r.json()
    assert b["author_nationalities"] == {"甲": ["中国", "美国"], "乙": ["法国"]}
    assert b["nationalities"] == ["中国", "法国", "美国"]
    client.put(f"/api/books/{bid}/author-nationalities", json={"nationalities": {"甲": ["日本"]}})
    assert client.get(f"/api/books/{bid}").json()["author_nationalities"]["甲"] == ["日本"]
    client.put(f"/api/books/{bid}/author-nationalities", json={"nationalities": {"甲": []}})
    assert client.get(f"/api/books/{bid}").json()["author_nationalities"]["甲"] == []
    assert client.get(f"/api/books/{bid}").json()["nationalities"] == ["法国"]   # 甲清空后只剩乙


def test_spectrum_excludes_placeholder_author(client):
    """占位作者「其它」(chinese=0, 54 本垃圾桶) 不得污染语言轴的"翻译"计数。"""
    from app import db as dbmod
    client.post("/api/books", json={"title": "占位书", "authors": ["其它"]})
    with dbmod.db_conn(client.app.state.db_path) as c:
        c.execute("UPDATE authors SET chinese=0 WHERE name='其它'")
        _set_nats(c, "其它", "未知")
        c.commit()
    sp = {a["axis"]: {s["key"]: s["value"] for s in a["segments"]}
          for a in client.get("/api/stats/spectrum").json()}
    assert sp.get("语言", {}) == {}                      # 语言轴不计占位作者
    assert sp["读完没"]["未读"] == 1                     # 其它轴照常
    # 「未知」是占位垃圾桶，不进国籍筛选选项
    assert "未知" not in client.get("/api/facets").json()["nationalities"]


def test_douban_id(client):
    bid = client.post("/api/books", json={"title": "丙", "douban_id": "12345"}).json()
    assert client.get(f"/api/books/{bid}").json()["douban_id"] == "12345"
    assert client.get("/api/books").json()["items"][0]["douban_id"] == "12345"
    # PUT 不带该字段时保留（老客户端不清空）；带空串时清空
    assert client.put(f"/api/books/{bid}", json={"rating": 8}).json()["douban_id"] == "12345"
    assert client.put(f"/api/books/{bid}", json={"douban_id": ""}).json()["douban_id"] is None

# ---------- 仪表盘分析 ----------


def _seed(client):
    # 三本都打过分且填了阅读日（read_at=读完日；created 是买书日，两套时间各管各的）
    client.post("/api/books", json={"title": "活着", "authors": ["余华"], "categories": ["长篇"],
        "rating": 9, "importance": 0.9, "price": 50, "created": "April 27, 2024 11:32 AM",
        "read_at": "May 2, 2024"})
    client.post("/api/books", json={"title": "局外人", "authors": ["阿尔贝·加缪"], "categories": ["长篇"],
        "rating": 8, "importance": 0.5, "price": -20, "created": "January 5, 2023 9:00 AM",
        "read_at": "February 1, 2023"})
    client.post("/api/books", json={"title": "八月HALF", "authors": ["宝春溪"], "categories": ["传记"],
        "rating": 7, "importance": 0.8, "price": 40, "created": "April 27, 2024 11:32 AM",
        "read_at": "June 1, 2024"})


def test_stats_daily(client):
    _seed(client)
    d = client.get("/api/stats/daily").json()
    assert set(d) == {"2024-04-27", "2023-01-05"}
    assert d["2024-04-27"]["n"] == 2 and "活着" in d["2024-04-27"]["titles"]


def test_stats_daily_follows_created(client):
    """剁手日历按登记日：就算填了 read_at 也不往日历里挪。"""
    client.post("/api/books", json={"title": "后补笔记", "created": "January 5, 2023 9:00 AM",
                                    "read_at": "June 15, 2024 8:00 PM"})
    d = client.get("/api/stats/daily").json()
    assert "2023-01-05" in d
    assert "2024-06-15" not in d


def test_stats_curve_counts_only_rated(client):
    """曲线只数「读过的一本」= 有评分且有阅读日；没打分的不入曲线。"""
    _seed(client)                       # 3 本读完：2024-05 活着、2024-06 八月HALF、2023-02 局外人
    client.post("/api/books", json={"title": "只买没读",
                                    "created": "April 27, 2024 11:32 AM"})
    rows = {r["period"]: r for r in client.get("/api/stats/curve", params={"gran": "month"}).json()}
    assert set(rows) == {"2024-05-01", "2024-06-01", "2023-02-01"}
    assert all("只买没读" not in r["titles"] for r in rows.values())


def test_stats_curve_requires_read_at(client):
    """曲线严格按阅读日：read_at 没填 = 未读，就算打过分也不入曲线，绝不拿购买日兑数。"""
    client.post("/api/books", json={"title": "读过且填了日", "rating": 8,
                                    "created": "January 5, 2023 9:00 AM",
                                    "read_at": "June 15, 2024 8:00 PM"})
    client.post("/api/books", json={"title": "打分没填日子", "rating": 7,
                                    "created": "March 3, 2023 9:00 AM"})
    assert [r["period"] for r in client.get("/api/stats/curve").json()] == ["2024-06-01"]


def test_stats_spectrum(client):
    _seed(client)
    sp = {a["axis"]: {s["key"]: s["value"] for s in a["segments"]}
          for a in client.get("/api/stats/spectrum").json()}
    assert sp["读什么"]["小说·戏剧"] == 2 and sp["读什么"]["思想·人文·实用"] == 1
    assert sp["语言"]["原创"] == 2 and sp["语言"]["翻译"] == 1
    assert sp["读完没"]["未读"] == 3


def test_stats_quadrant(client):
    _seed(client)
    q = client.get("/api/stats/quadrant").json()
    assert len(q) == 3 and all({"rating", "importance", "price"} <= set(p) for p in q)


def test_list_year_filter(client):
    _seed(client)
    assert client.get("/api/books", params={"year": 2024}).json()["total"] == 2
    assert client.get("/api/books", params={"year": 2023}).json()["total"] == 1
    # 年度=购买年：买来还没读的也算在当年账里（钱是那年花的）
    client.post("/api/books", json={"title": "买来未读", "created": "April 1, 2024"})
    assert client.get("/api/books", params={"year": 2024}).json()["total"] == 3

# ---------- AI ----------


def test_cover_endpoint(client, monkeypatch):
    """单本抓封面只需豆瓣号；占位图不落盘。"""
    import app.douban as dmod
    monkeypatch.setattr(dmod, "fetch_cover_url",
                        lambda i, **k: f"https://img3.doubanio.com/view/subject/s/public/s{i}.jpg")
    monkeypatch.setattr(dmod, "_download", lambda u, **k: b"bytes")
    b0 = client.post("/api/books", json={"title": "无豆瓣号"}).json()
    assert client.post(f"/api/books/{b0}/cover").status_code == 400
    b1 = client.post("/api/books", json={"title": "有书", "douban_id": "999", "isbn": "978999"}).json()
    assert client.post(f"/api/books/{b1}/cover").json() == {"has_cover": True, "douban_id": "999"}
    root = client.app.state.root
    assert (root / "raw/covers/999.jpg").read_bytes() == b"bytes"
    assert client.get("/cover/999").status_code == 200
    assert "999" in client.get("/api/covers").json()
    no_isbn = client.post("/api/books", json={"title": "无 ISBN", "douban_id": "777"}).json()
    assert client.post(f"/api/books/{no_isbn}/cover").json() == {"has_cover": True, "douban_id": "777"}
    assert (root / "raw/covers/777.jpg").read_bytes() == b"bytes"
    # 豆瓣无真封面（占位图）→ 不存脏图
    monkeypatch.setattr(dmod, "fetch_cover_url",
                        lambda i, **k: "https://img1.doubanio.com/cuphead/book-static/x.gif")
    b2 = client.post("/api/books", json={"title": "占位", "douban_id": "888", "isbn": "978888"}).json()
    assert client.post(f"/api/books/{b2}/cover").json() == {"has_cover": False, "douban_id": "888"}
    assert not (root / "raw/covers/888.jpg").exists()


def test_cover_network_error_is_502(client, monkeypatch):
    """httpx 网络异常（超时/断连）被包成 RuntimeError → 路由 502，而不是裸 500。"""
    import httpx
    import app.douban as dmod
    def neterr(*a, **k): raise httpx.ConnectError("断网")
    monkeypatch.setattr(dmod.httpx, "get", neterr)
    b1 = client.post("/api/books", json={"title": "有豆瓣号", "douban_id": "999"}).json()
    assert client.post(f"/api/books/{b1}/cover").status_code == 502


def test_isbn_lookup_is_separate_from_cover(client, monkeypatch):
    import app.douban as dmod
    seen = []
    monkeypatch.setattr(dmod, "lookup_subject_by_isbn", lambda isbn: seen.append(isbn) or "2253642")
    monkeypatch.setattr(dmod, "fetch_cover_url",
                        lambda did: f"https://img3.doubanio.com/view/subject/s/public/s{did}.jpg")
    monkeypatch.setattr(dmod, "_download", lambda url: b"cover")
    bid = client.post("/api/books", json={"title": "明朝那些事儿", "isbn": "9787505723788"}).json()
    assert client.post(f"/api/books/{bid}/cover").status_code == 400
    response = client.post(f"/api/books/{bid}/douban-id")
    assert response.status_code == 200
    assert response.json() == {"douban_id": "2253642"}
    assert seen == ["9787505723788"]
    assert client.get(f"/api/books/{bid}").json()["douban_id"] == "2253642"
    assert not list(client.app.state.covers_dir.iterdir())
    assert client.post(f"/api/books/{bid}/cover").json()["has_cover"] is True
    assert (client.app.state.covers_dir / "2253642.jpg").read_bytes() == b"cover"
    assert len(seen) == 1


def test_cover_does_not_save_unverified_id(client, monkeypatch):
    import app.douban as dmod
    bid = client.post("/api/books", json={"title": "无匹配", "isbn": "9787505723788"}).json()

    def no_match(isbn):
        raise ValueError("豆瓣未找到该 ISBN 对应的条目")

    monkeypatch.setattr(dmod, "lookup_subject_by_isbn", no_match)
    r = client.post(f"/api/books/{bid}/douban-id")
    assert r.status_code == 400
    assert client.get(f"/api/books/{bid}").json()["douban_id"] is None
    no_isbn = client.post("/api/books", json={"title": "无 ISBN"}).json()
    assert client.post(f"/api/books/{no_isbn}/douban-id").status_code == 400
    invalid_id = client.post("/api/books", json={
        "title": "错误编号", "douban_id": "../wrong"}).json()
    assert client.post(f"/api/books/{invalid_id}/cover").status_code == 400


def test_isbn_lookup_rejects_stale_book_change(client, monkeypatch):
    import app.douban as dmod
    bid = client.post("/api/books", json={"title": "旧版", "isbn": "9787505723788"}).json()

    def lookup(isbn):
        client.put(f"/api/books/{bid}", json={"isbn": "9787505723789"})
        return "2253642"

    monkeypatch.setattr(dmod, "lookup_subject_by_isbn", lookup)
    assert client.post(f"/api/books/{bid}/douban-id").status_code == 409
    book = client.get(f"/api/books/{bid}").json()
    assert book["isbn"] == "9787505723789"
    assert book["douban_id"] is None


def test_wall_endpoint(client, monkeypatch):
    """书架只显有本地封面文件的书（判据 = 磁盘文件，不是 DB 列）。"""
    import app.douban as dmod
    monkeypatch.setattr(dmod, "fetch_cover_url",
                        lambda i, **k: f"https://img3.doubanio.com/s{i}.jpg")
    monkeypatch.setattr(dmod, "_download", lambda u, **k: b"x")
    b1 = client.post("/api/books", json={"title": "有封面", "douban_id": "1", "isbn": "9781", "rating": 9,
                                         "created": "April 27, 2024 11:32 AM"}).json()
    client.post(f"/api/books/{b1}/cover")
    client.post("/api/books", json={"title": "无封面", "isbn": "9782"})   # 有 isbn 但未落盘
    b3 = client.post("/api/books", json={"title": "无 ISBN 的封面", "douban_id": "3"}).json()
    client.post(f"/api/books/{b3}/cover")
    w = client.get("/api/stats/wall").json()
    assert w["total"] == 3
    assert [i["id"] for i in w["items"]] == [b1, b3]
    assert set(w["items"][0]) == {"id", "title", "read_at", "rating", "isbn", "douban_id"}
    assert w["items"][0]["isbn"] == "9781"


def test_timestamps_are_server_stamped(client):
    """创建/更改时间由服务端自动写：新增补 created，编辑刷新 last_modified，两者都不吃客户端。"""
    bid = client.post("/api/books", json={"title": "无日期新书"}).json()
    b = client.get(f"/api/books/{bid}").json()
    assert b["created"] and b["last_modified"]            # 没填也有值
    assert dbmod.ts_key(b["created"]) and dbmod.ts_key(b["last_modified"])   # 格式可解析
    first = b["last_modified"]

    client.put(f"/api/books/{bid}", json={"rating": 8, "last_modified": "January 1, 2000 1:00 AM"})
    b2 = client.get(f"/api/books/{bid}").json()
    assert b2["created"] == b["created"]                  # 编辑不动创建时间
    assert b2["last_modified"] != "January 1, 2000 1:00 AM"   # 客户端给的更改时间被服务端覆盖

    keep = client.post("/api/books", json={
        "title": "导入带购入日", "created": "June 1, 2024 8:00 AM"}).json()
    assert client.get(f"/api/books/{keep}").json()["created"] == "June 1, 2024 8:00 AM"


def test_sold_list_desc_stays_descending(client):
    """已售书 created 全空：主键整组相同，副键必须跟主键同向，否则「降序」会翻成 id 升序。"""
    ids = [client.post("/api/books", json={"title": f"卖{i}", "status": "sold"}).json()
           for i in range(3)]
    titles = [x["title"] for x in client.get(
        "/api/books", params={"status": "sold", "sort": "created", "desc": "true"}).json()["items"]]
    assert titles == [f"卖{i}" for i in (2, 1, 0)]        # 新登记的在前（id 降序）
    assert [x["title"] for x in client.get(
        "/api/books", params={"status": "sold", "sort": "created", "desc": "false"}).json()["items"]] \
        == [f"卖{i}" for i in (0, 1, 2)]
