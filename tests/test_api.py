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
    (tmp_path / "raw" / "有正文.md").write_text("# 标题\n正文内容", encoding="utf-8")
    bid = client.post("/api/books", json={"title": "有正文", "file_path": "raw/有正文.md"}).json()
    r = client.get(f"/api/books/{bid}/content")
    assert r.status_code == 200 and "正文内容" in r.text
    bid2 = client.post("/api/books", json={"title": "无正文"}).json()
    assert client.get(f"/api/books/{bid2}/content").status_code == 404


def test_content_strips_douban_header(client, tmp_path):
    hdr = '> **[《📖 某书](https://book.douban.com/subject/123/)**\n> 内容简介…\n\n'
    (tmp_path / "raw" / "仅豆瓣头.md").write_text(hdr, encoding="utf-8")
    b1 = client.post("/api/books", json={"title": "仅豆瓣头", "file_path": "raw/仅豆瓣头.md"}).json()
    assert client.get(f"/api/books/{b1}/content").status_code == 404
    (tmp_path / "raw" / "豆瓣头加笔记.md").write_text(hdr + "# 我的笔记\n很好看", encoding="utf-8")
    b2 = client.post("/api/books", json={"title": "豆瓣头加笔记", "file_path": "raw/豆瓣头加笔记.md"}).json()
    r = client.get(f"/api/books/{b2}/content")
    assert r.status_code == 200 and "我的笔记" in r.text and "douban" not in r.text


def test_content_traversal_blocked(client, tmp_path):
    (tmp_path / "secret.txt").write_text("secret", encoding="utf-8")
    bid = client.post("/api/books", json={"title": "穿越", "file_path": "../secret.txt"}).json()
    assert client.get(f"/api/books/{bid}/content").status_code == 404


def test_facets(client):
    client.post("/api/books", json={"title": "甲", "authors": ["张"],
                                    "categories": ["科幻"], "platform": "京东"})
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


def test_git_push_commits_changes(client, tmp_path):
    import subprocess
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)   # 把 fixture 建的 t.db 收进首个 commit
    subprocess.run(["git", "commit", "-q", "--allow-empty", "-m", "init"], cwd=tmp_path, check=True)
    r1 = client.post("/api/git/push").json()
    assert "nothing to commit" in r1["output"]                 # 无变更时如实报告
    (tmp_path / "new.txt").write_text("x", encoding="utf-8")
    r2 = client.post("/api/git/push").json()
    n = subprocess.run(["git", "rev-list", "--count", "HEAD"], cwd=tmp_path,
                       capture_output=True, text=True).stdout.strip()
    assert n == "2"                                            # commit 成功（push 无 remote，ok=False 可接受）
    assert "git push" in r2["output"]

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

def test_stats_daily(client):
    _seed(client)
    d = client.get("/api/stats/daily").json()
    assert set(d) == {"2024-04-27", "2023-01-05"}
    assert d["2024-04-27"]["n"] == 2 and "活着" in d["2024-04-27"]["titles"]

def test_stats_spectrum(client, monkeypatch):
    from app.ai import gen
    monkeypatch.setattr(gen, "ensure_author_flags", lambda conn: None)  # 测试不打 LLM，走启发式兜底
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

# ---------- AI ----------
def test_summary_endpoint(client, tmp_path, monkeypatch):
    from app.ai import gen
    monkeypatch.setattr(gen.llm, "chat", lambda msgs, **kw: "一句话摘要。")
    (tmp_path / "raw" / "活着.md").write_text("福贵的一生…", encoding="utf-8")
    bid = client.post("/api/books", json={"title": "活着", "file_path": "raw/活着.md"}).json()
    assert client.get(f"/api/books/{bid}/summary").json() == {"summary": "一句话摘要。", "cached": False}
    assert client.get(f"/api/books/{bid}/summary").json()["cached"] is True   # 命中缓存
    bno = client.post("/api/books", json={"title": "无笔记"}).json()
    assert client.get(f"/api/books/{bno}/summary").status_code == 404

def test_yearly_endpoint(client, monkeypatch):
    from app.ai import gen
    calls = []
    monkeypatch.setattr(gen.llm, "chat", lambda msgs, **kw: calls.append(1) or "画像文本")
    _seed(client)
    assert client.get("/api/ai/yearly").json()["years"] == [2024, 2023]
    assert client.get("/api/ai/yearly", params={"year": 2024, "pending": 1}).json()["text"] is None
    assert client.get("/api/ai/yearly", params={"year": 2024}).json()["text"] == "画像文本"
    assert client.get("/api/ai/yearly", params={"year": 2024, "pending": 1}).json()["cached"] is True
    assert len(calls) == 1                          # pending 查询不触发生成
    client.get("/api/ai/yearly", params={"year": 2024})
    assert len(calls) == 1                          # 缓存后不再调模型

def test_author_flags_fallback(client):
    from app import db as dbmod
    from app.ai import gen
    def boom(msgs, **kw): raise RuntimeError("断网")
    orig, gen.llm.chat = gen.llm.chat, boom
    _seed(client)
    try:
        with dbmod.db_conn(client.app.state.db_path) as c:
            gen.ensure_author_flags(c)
    finally:
        gen.llm.chat = orig
    with dbmod.db_conn(client.app.state.db_path) as c:
        flags = dict(c.execute("SELECT name, chinese FROM authors").fetchall())
    assert flags["余华"] == 1 and flags["阿尔贝·加缪"] == 0

def test_cover_endpoint(client, monkeypatch):
    import app.douban as dmod
    monkeypatch.setattr(dmod, "fetch_cover_url", lambda i, **k: f"//c{i}")
    b0 = client.post("/api/books", json={"title": "无豆瓣号"}).json()
    assert client.post(f"/api/books/{b0}/cover").status_code == 400
    b1 = client.post("/api/books", json={"title": "有豆瓣号", "douban_id": "999"}).json()
    assert client.post(f"/api/books/{b1}/cover").json() == {"cover_url": "//c999"}
    assert client.get(f"/api/books/{b1}").json()["cover_url"] == "//c999"
