"""封面本地化：以豆瓣编号抓取，兼容旧 ISBN 封面。"""
import sqlite3
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from app import douban
from app.dependencies import local_cover_stems
from app.main import create_app


def _db():
    """books 不再存 cover_url；封面真值 = 磁盘文件。这里造 douban_id+isbn 行。"""
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.execute("CREATE TABLE books (id INTEGER PRIMARY KEY, isbn TEXT, douban_id TEXT)")
    c.executemany("INSERT INTO books (id, isbn, douban_id) VALUES (?,?,?)", [
        (1, "978A", "d1"),                     # 正常：有封面
        (2, "978B", "d2"),                     # 豆瓣只有占位图 → skip
        (3, "978C", None),                     # 无豆瓣号 → localize 不碰
        (4, "978A", "d1"),                     # 同 isbn+douban 的多批次 → DISTINCT 合并
        (5, None, "d3"),                       # 无 ISBN 也能抓封面
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
        "d3": "https://img3.doubanio.com/s3.jpg",
    }, calls)
    c = _db()
    rep = douban.localize_covers(c, tmp_path)
    assert rep == {"downloaded": 2, "skipped": 0, "placeholder": 1, "fail": 0,
                   "aborted": False, "already_have": 0, "todo": 3}
    assert (tmp_path / "d1.jpg").read_bytes() == b"jpegbytes"
    assert (tmp_path / "d3.jpg").read_bytes() == b"jpegbytes"
    assert len(calls) == 2
    # 幂等重跑：已有文件不再请求；占位图可重试
    rep2 = douban.localize_covers(c, tmp_path)
    assert rep2["downloaded"] == 0 and rep2["todo"] == 1
    assert len(calls) == 2


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
    assert rep["downloaded"] == 1 and rep["todo"] == 3


def test_localize_skips_legacy_isbn_cover(tmp_path, monkeypatch):
    (tmp_path / "978A.jpg").write_bytes(b"legacy")
    calls = []
    _stub_net(monkeypatch, {"d2": "https://img3.doubanio.com/s2.jpg",
                            "d3": "https://img3.doubanio.com/s3.jpg"}, calls)
    rep = douban.localize_covers(_db(), tmp_path)
    assert rep["already_have"] == 1
    assert "https://img3.doubanio.com/s2.jpg" in calls
    assert not (tmp_path / "d1.jpg").exists()


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


def _search_html(*ids):
    items = ",".join(f'{{"id": {i}, "title": "x"}}' for i in ids)
    return f'<script>window.__DATA__ = {{"items": [{items}], "total": {len(ids)}}};\n</script>'


def _subject_html(isbn):
    return f'<script type="application/ld+json">{{"@type":"Book","isbn":"{isbn}"}}</script>'


def _fake_douban(monkeypatch, search_ids, subject_isbn, calls=None):
    def get(url, **kwargs):
        if calls is not None:
            calls.append((url, kwargs.get("params")))
        if "search.douban.com" in url:
            return SimpleNamespace(status_code=200, text=_search_html(*search_ids))
        return SimpleNamespace(status_code=200, text=_subject_html(subject_isbn))
    monkeypatch.setattr(douban.httpx, "get", get)


def test_lookup_subject_by_isbn_verifies_edition(monkeypatch):
    calls = []
    _fake_douban(monkeypatch, [2253642, 999], "9787505723788", calls)
    assert douban.lookup_subject_by_isbn("978-7505723788") == "2253642"
    assert calls == [
        ("https://search.douban.com/book/subject_search",
         {"search_text": "9787505723788", "cat": "1001"}),
        ("https://book.douban.com/subject/2253642/", None),
    ]


def test_lookup_subject_by_isbn_rejects_missing_or_wrong_edition(monkeypatch):
    _fake_douban(monkeypatch, [123], "9787505723789")
    with pytest.raises(ValueError, match="9787505723789.*不一致"):
        douban.lookup_subject_by_isbn("9787505723788")
    with pytest.raises(ValueError, match="ISBN"):
        douban.lookup_subject_by_isbn("../bad")
    _fake_douban(monkeypatch, [], "")
    with pytest.raises(ValueError, match="搜不到") as e:
        douban.lookup_subject_by_isbn("9787505723788")
    assert "校验位" not in str(e.value)
    with pytest.raises(ValueError, match="校验位不对"):
        douban.lookup_subject_by_isbn("9787532237354")
    monkeypatch.setattr(douban.httpx, "get",
                        lambda url, **kwargs: SimpleNamespace(status_code=200, text="<html></html>"))
    with pytest.raises(RuntimeError, match="结构变化"):
        douban.lookup_subject_by_isbn("9787505723788")
    monkeypatch.setattr(douban.httpx, "get",
                        lambda url, **kwargs: SimpleNamespace(status_code=418, text="blocked"))
    with pytest.raises(RuntimeError, match="418"):
        douban.lookup_subject_by_isbn("9787505723788")
    monkeypatch.setattr(douban.httpx, "get", lambda url, **kwargs: (_ for _ in ()).throw(
        httpx.ConnectError("offline")))
    with pytest.raises(RuntimeError, match="网络错误"):
        douban.lookup_subject_by_isbn("9787505723788")
