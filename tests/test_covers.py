"""封面本地化：localize_covers 以 douban_id 为源（全离线，fetch_cover_url/_download 被打桩）
   + /cover/<isbn> 动态伺服 / /api/covers 清单 / 书架按本地文件过滤。"""
import sqlite3

from fastapi.testclient import TestClient

from app import douban
from app.main import create_app, local_cover_stems


def _db():
    """books 不再存 cover_url；封面真值 = 磁盘文件。这里造 douban_id+isbn 行。"""
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.execute("CREATE TABLE books (id INTEGER PRIMARY KEY, isbn TEXT, douban_id TEXT)")
    c.executemany("INSERT INTO books (id, isbn, douban_id) VALUES (?,?,?)", [
        (1, "978A", "d1"),                     # 正常：有封面
        (2, "978B", "d2"),                     # 豆瓣只有占位图 → skip
        (3, "978C", None),                     # 无豆瓣号 → localize 不碰（留人工按 isbn 放图）
        (4, "978A", "d1"),                     # 同 isbn+douban 的多批次 → DISTINCT 合并
    ])
    c.commit()
    return c


def _stub_net(monkeypatch, url_map, calls):
    monkeypatch.setattr(douban, "fetch_cover_url",
                        lambda did, **kw: url_map[did])
    monkeypatch.setattr(douban, "_download",
                        lambda u, **kw: calls.append(u) or b"jpegbytes")
    monkeypatch.setattr(douban.time, "sleep", lambda s: None)   # 免限速等待


def test_localize_offline(tmp_path, monkeypatch):
    calls = []
    _stub_net(monkeypatch, {
        "d1": "https://img3.doubanio.com/view/subject/s/public/s1.jpg",
        "d2": "https://img1.doubanio.com/cuphead/book-static/pics/x.gif",
    }, calls)
    c = _db()
    rep = douban.localize_covers(c, tmp_path)
    assert rep == {"downloaded": 1, "skipped": 0, "placeholder": 1, "fail": 0,
                   "aborted": False, "already_have": 0, "todo": 2}
    assert (tmp_path / "978A.jpg").read_bytes() == b"jpegbytes"   # 同 isbn 只下一张
    assert len(calls) == 1                                        # 占位图不触发下载
    # 幂等重跑：978A 已有文件不再 og；只剩 978B（占位图永远无文件，重推但跳过）
    rep2 = douban.localize_covers(c, tmp_path)
    assert rep2["downloaded"] == 0 and rep2["todo"] == 1
    assert len(calls) == 1


def test_localize_breaker(tmp_path, monkeypatch):
    def boom(did, **kw): raise RuntimeError("403")
    monkeypatch.setattr(douban, "fetch_cover_url", boom)
    monkeypatch.setattr(douban.time, "sleep", lambda s: None)
    c = _db()
    rep = douban.localize_covers(c, tmp_path, max_abort=2)
    assert rep["aborted"] and rep["fail"] == 2
    assert not any(tmp_path.iterdir())          # 不留半截文件


def test_localize_limit(tmp_path, monkeypatch):
    calls = []
    _stub_net(monkeypatch, {
        "d1": "https://img3.doubanio.com/s1.jpg",
        "d2": "https://img3.doubanio.com/s2.jpg",   # d2 当正常图，配合 limit 截断
    }, calls)
    c = _db()
    rep = douban.localize_covers(c, tmp_path, limit=1)
    assert rep["downloaded"] == 1 and rep["todo"] == 2   # todo 报全量，limit 只处理前 1


def _app(tmp_path):
    (tmp_path / "raw" / "covers").mkdir(parents=True)
    return TestClient(create_app(tmp_path / "t.db", tmp_path))


def test_cover_routes(tmp_path):
    client = _app(tmp_path)
    covers = tmp_path / "raw" / "covers"
    (covers / "978A.jpg").write_bytes(b"abc")     # 正常落盘
    (covers / "978C.webp").write_bytes(b"ww")     # 手工按 isbn 放图 → 自动被认（无需挂接命令）
    (covers / "readme.txt").write_text("")        # 非图片忽略

    assert client.get("/api/covers").json() == ["978A", "978C"]
    assert client.get("/cover/978A").status_code == 200        # 扩展名由路由嗅探
    assert client.get("/cover/978A").content == b"abc"
    assert client.get("/cover/978C").content == b"ww"          # 忽略扩展名命中 webp
    assert client.get("/cover/nope").status_code == 404        # 无文件 → 404 → 前端退书名卡
    assert local_cover_stems(covers) == {"978A", "978C"}
