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
    bid = client.post("/api/books", json={"title": "有正文", "file_path": "raw/books/有正文.md"}).json()
    r = client.get(f"/api/books/{bid}/content")
    assert r.status_code == 200 and "正文内容" in r.text
    bid2 = client.post("/api/books", json={"title": "无正文"}).json()
    assert client.get(f"/api/books/{bid2}/content").status_code == 404


def test_content_strips_douban_header(client, tmp_path):
    hdr = '> **[《📖 某书](https://book.douban.com/subject/123/)**\n> 内容简介…\n\n'
    (tmp_path / "raw" / "books").mkdir(parents=True)
    (tmp_path / "raw" / "books" / "仅豆瓣头.md").write_text(hdr, encoding="utf-8")
    b1 = client.post("/api/books", json={"title": "仅豆瓣头", "file_path": "raw/books/仅豆瓣头.md"}).json()
    assert client.get(f"/api/books/{b1}/content").status_code == 404
    (tmp_path / "raw" / "books" / "豆瓣头加笔记.md").write_text(hdr + "# 我的笔记\n很好看", encoding="utf-8")
    b2 = client.post("/api/books", json={"title": "豆瓣头加笔记", "file_path": "raw/books/豆瓣头加笔记.md"}).json()
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


def test_group_nationality(client):
    from app import db as dbmod
    client.post("/api/books", json={"title": "甲", "authors": ["余华"], "price": 10})
    client.post("/api/books", json={"title": "乙", "authors": ["加缪"], "price": -4})
    client.post("/api/books", json={"title": "丙"})   # 无作者：不进国籍维度（JOIN）
    with dbmod.db_conn(client.app.state.db_path) as c:
        c.execute("UPDATE authors SET nationality='中国' WHERE name='余华'")
        c.execute("UPDATE authors SET nationality='法国' WHERE name='加缪'")
        c.commit()
    g = {x["key"]: x["value"] for x in
         client.get("/api/stats/group", params={"by": "nationality"}).json()}
    assert g == {"中国": 1, "法国": 1}
    gm = {x["key"]: x["value"] for x in
          client.get("/api/stats/group", params={"by": "nationality", "agg": "sum_price"}).json()}
    assert gm["中国"] == 10 and gm["法国"] == -4
    # 未判定（nationality 为 NULL）归入「未标注」
    client.post("/api/books", json={"title": "丁", "authors": ["未判定作者"]})
    g2 = {x["key"]: x["value"] for x in
          client.get("/api/stats/group", params={"by": "nationality"}).json()}
    assert g2["未标注"] == 1


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


def test_spectrum_excludes_placeholder_author(client):
    """占位作者「其它」(chinese=0, 54 本垃圾桶) 不得污染语言轴的"翻译"计数。"""
    from app import db as dbmod
    client.post("/api/books", json={"title": "占位书", "authors": ["其它"]})
    with dbmod.db_conn(client.app.state.db_path) as c:
        c.execute("UPDATE authors SET chinese=0, nationality='未知' WHERE name='其它'")
        c.commit()
    sp = {a["axis"]: {s["key"]: s["value"] for s in a["segments"]}
          for a in client.get("/api/stats/spectrum").json()}
    assert sp.get("语言", {}) == {}                      # 语言轴不计占位作者
    assert sp["读完没"]["未读"] == 1                     # 其它轴照常


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


def test_stats_daily_follows_created(client):
    """剁手日历按登记日：就算填了 read_at 也不往日历里挪。"""
    client.post("/api/books", json={"title": "后补笔记", "created": "January 5, 2023 9:00 AM",
                                    "read_at": "June 15, 2024 8:00 PM"})
    d = client.get("/api/stats/daily").json()
    assert "2023-01-05" in d
    assert "2024-06-15" not in d


def test_stats_curve_counts_only_rated(client):
    """曲线只数“读过的一本”= 有评分；没打分的不入曲线。"""
    _seed(client)                       # 3 本都有评分：2024-04 两本、2023-01 一本
    client.post("/api/books", json={"title": "只买没读",
                                    "created": "April 27, 2024 11:32 AM"})
    rows = {r["period"]: r for r in client.get("/api/stats/curve", params={"gran": "month"}).json()}
    assert rows["2024-04-01"]["n"] == 2 and "只买没读" not in rows["2024-04-01"]["titles"]
    assert rows["2023-01-01"]["n"] == 1


def test_stats_curve_prefers_read_at(client):
    """曲线分桶：read_at 有值用它，没值回落 created（刚打分还没来得及填阅读日也不丢）。"""
    client.post("/api/books", json={"title": "读过且填了日", "rating": 8,
                                    "created": "January 5, 2023 9:00 AM",
                                    "read_at": "June 15, 2024 8:00 PM"})
    client.post("/api/books", json={"title": "刚打分", "rating": 7,
                                    "created": "March 3, 2023 9:00 AM"})
    assert [r["period"] for r in client.get("/api/stats/curve").json()] == ["2023-03-01", "2024-06-01"]


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

# ---------- AI ----------
def test_summary_endpoint(client, tmp_path, monkeypatch):
    from app.ai import gen
    monkeypatch.setattr(gen.llm, "chat", lambda msgs, **kw: "一句话摘要。")
    (tmp_path / "raw" / "books").mkdir(parents=True)
    (tmp_path / "raw" / "books" / "活着.md").write_text("福贵的一生…", encoding="utf-8")
    bid = client.post("/api/books", json={"title": "活着", "file_path": "raw/books/活着.md"}).json()
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

def test_yearly_portrait_only_rated_books(client, monkeypatch):
    """年度画像只取打过分的话，跟曲线同口径：不然 2024 曲线 28 本、画像 prompt 108 本。"""
    from app.ai import gen
    prompts = []
    def fake(msgs, **kw):
        prompts.append(msgs[-1]["content"])
        return "画像文本"
    monkeypatch.setattr(gen.llm, "chat", fake)
    client.post("/api/books", json={"title": "读过", "rating": 8,
                                    "created": "April 27, 2024 11:32 AM"})
    client.post("/api/books", json={"title": "只买没读",
                                    "created": "April 27, 2024 11:32 AM"})
    assert client.get("/api/ai/yearly").json()["years"] == [2024]
    client.get("/api/ai/yearly", params={"year": 2024})
    assert "《读过》" in prompts[0] and "只买没读" not in prompts[0]
    assert client.get("/api/ai/yearly", params={"year": 2023}).status_code == 404

def test_author_meta_fallback(client, monkeypatch):
    """LLM 调用失败 → 抛错（路由 502 / CLI 退出码 1）且不写库（chinese/nationality 保持 NULL），重新触发即重试。"""
    from app import db as dbmod
    from app.ai import gen
    def boom(msgs, **kw): raise RuntimeError("断网")
    monkeypatch.setattr(gen.llm, "chat", boom)
    _seed(client)
    with dbmod.db_conn(client.app.state.db_path) as c:
        with pytest.raises(RuntimeError):
            gen.ensure_author_meta(c)
    with dbmod.db_conn(client.app.state.db_path) as c:
        flags = dict(c.execute("SELECT name, chinese || '|' || nationality FROM authors").fetchall())
    assert flags and all(v is None for v in flags.values())

def test_author_meta_llm_success(client, monkeypatch):
    """LLM 正常返回 → 国籍+标志落库；响应里漏掉的名字走启发式兜底（中文名→中国/华人）。"""
    from app import db as dbmod
    from app.ai import gen
    monkeypatch.setattr(gen.llm, "chat",
                        lambda msgs, **kw: '[{"name":"余华","country":"中国","cn":1},'
                                           '{"name":"阿尔贝·加缪","country":"法国","cn":0}]')
    _seed(client)
    with dbmod.db_conn(client.app.state.db_path) as c:
        judged = gen.ensure_author_meta(c)
    assert judged == 3
    with dbmod.db_conn(client.app.state.db_path) as c:
        rows = dict((r["name"], (r["nationality"], r["chinese"])) for r in
                    c.execute("SELECT name, nationality, chinese FROM authors"))
    assert rows == {"余华": ("中国", 1), "阿尔贝·加缪": ("法国", 0), "宝春溪": ("中国", 1)}

def test_author_meta_routes(client, monkeypatch):
    from app import db as dbmod
    from app.ai import gen
    _seed(client)
    # 状态：3 位作者全部未判定
    assert client.get("/api/ai/author-meta").json() == {"total": 3, "pending": 3}
    # 断网 → POST 502，不写库
    def boom(msgs, **kw): raise RuntimeError("断网")
    monkeypatch.setattr(gen.llm, "chat", boom)
    assert client.post("/api/ai/author-meta").status_code == 502
    assert client.get("/api/ai/author-meta").json()["pending"] == 3
    # 成功 → judged + pending 归零；再 POST 幂等（无 pending，不调模型）
    calls = []
    monkeypatch.setattr(gen.llm, "chat",
                        lambda msgs, **kw: calls.append(1) or
                        '[{"name":"余华","country":"中国","cn":1},{"name":"阿尔贝·加缪","country":"法国","cn":0},'
                        '{"name":"宝春溪","country":"中国","cn":1}]')
    assert client.post("/api/ai/author-meta").json() == {"total": 3, "pending": 0, "judged": 3}
    assert client.post("/api/ai/author-meta").json()["judged"] == 0
    assert len(calls) == 1

def test_spectrum_is_pure_read(client, monkeypatch):
    """spectrum 不再触发判定：无 LLM 也直接 200（语言轴按调用启发式兜底），且不写库。"""
    from app import db as dbmod
    from app.ai import gen
    def boom(msgs, **kw): raise RuntimeError("断网")
    monkeypatch.setattr(gen.llm, "chat", boom)
    _seed(client)
    sp = client.get("/api/stats/spectrum")
    assert sp.status_code == 200 and len(sp.json()) == 3
    with dbmod.db_conn(client.app.state.db_path) as c:
        flags = dict(c.execute("SELECT name, chinese FROM authors").fetchall())
    assert all(v is None for v in flags.values())

def test_cli_meta_no_pending(tmp_path):
    """CLI python -m app.ai.gen --meta：无 pending 时不调模型、正常退出（--db 指向临时库，不碰真库）。"""
    import json, subprocess, sys
    from pathlib import Path
    from app import db as dbmod
    dbp = tmp_path / "cli.db"
    with dbmod.db_conn(dbp) as c:
        dbmod.init_db(c)
    r = subprocess.run([sys.executable, "-m", "app.ai.gen", "--meta", "--db", str(dbp)],
                       capture_output=True, text=True, cwd=Path(__file__).parent.parent)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout) == {"ok": True, "judged": 0, "total": 0, "pending": 0}

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

def test_wall_endpoint(client, monkeypatch):
    """书架只显有本地封面文件的书（判据 = 磁盘文件，不是 DB 列）。"""
    import app.douban as dmod
    monkeypatch.setattr(dmod, "fetch_cover_url",
                        lambda i, **k: f"https://img3.doubanio.com/s{i}.jpg")
    monkeypatch.setattr(dmod, "_download", lambda u, **k: b"x")
    b1 = client.post("/api/books", json={"title": "有封面", "douban_id": "1", "isbn": "9781", "rating": 9,
                                         "created": "April 27, 2024 11:32 AM"}).json()
    client.post(f"/api/books/{b1}/cover")                       # 落盘 9781
    client.post("/api/books", json={"title": "无封面", "isbn": "9782"})   # 有 isbn 但未落盘
    w = client.get("/api/stats/wall").json()
    assert w["total"] == 2                                   # total 是全库本数
    assert [i["id"] for i in w["items"]] == [b1]             # items 只含磁盘有文件的
    assert set(w["items"][0]) == {"id", "title", "read_at", "rating", "isbn"}
    assert w["items"][0]["isbn"] == "9781"

def test_yearly_reads_from_app_root(client, tmp_path, monkeypatch):
    """年度画像的笔记摘录必须读注入的 vault root（create_app 的 root 参数），不是硬编码路径。"""
    from app.ai import gen
    prompts = []
    def fake(msgs, **kw):
        prompts.append(msgs[-1]["content"]); return "画像文本"
    monkeypatch.setattr(gen.llm, "chat", fake)
    (tmp_path / "raw" / "books").mkdir(parents=True)
    (tmp_path / "raw" / "books" / "根探针笔记.md").write_text("探针内容:只存在于测试 vault", encoding="utf-8")
    client.post("/api/books", json={"title": "根探针", "file_path": "raw/books/根探针笔记.md",
                                    "rating": 8, "created": "April 27, 2024 11:32 AM"})
    assert client.get("/api/ai/yearly", params={"year": 2024}).status_code == 200
    assert "探针内容:只存在于测试 vault" in prompts[0]
