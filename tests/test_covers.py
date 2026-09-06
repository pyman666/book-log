"""封面本地化：--localize / --link 纯函数逻辑（全离线，_download 被 monkeypatch）。"""
import sqlite3

import pytest
from fastapi.testclient import TestClient

from app import douban
from app.main import create_app


def _db():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.execute("CREATE TABLE books (id INTEGER PRIMARY KEY, isbn TEXT, cover_url TEXT)")
    c.executemany("INSERT INTO books (id, isbn, cover_url) VALUES (?,?,?)", [
        (1, "978A", "https://img3.doubanio.com/view/subject/s/public/s1.jpg"),
        (2, "978B", "https://img1.doubanio.com/cuphead/book-static/pics/x.gif"),  # 占位图
        (3, "978C", None),
        (4, "978A", "https://img2.doubanio.com/view/subject/s/public/s4.jpg"),    # 同 isbn 多批次
    ])
    c.commit()
    return c


def test_localize_offline(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(douban, "_download", lambda u, **kw: calls.append(u) or b"jpegbytes")
    monkeypatch.setattr(douban.time, "sleep", lambda s: None)   # 免限速等待
    c = _db()
    rep = douban.localize_covers(c, tmp_path)
    assert rep["downloaded"] == 1 and rep["path_only"] == 1 and rep["placeholder"] == 1
    assert not rep["aborted"]
    assert (tmp_path / "978A.jpg").read_bytes() == b"jpegbytes"  # 同 isbn 只下一张
    url = dict(c.execute("SELECT id, cover_url FROM books").fetchall())
    assert url[1] == url[4] == "/covers/978A.jpg"
    assert url[2].startswith("http")                            # 占位图留给人工补
    # 幂等重跑：只剩占位图一行待处理，且直接跳过、不再触发网络
    rep2 = douban.localize_covers(c, tmp_path)
    assert rep2["downloaded"] == 0 and rep2["todo"] == 1 and len(calls) == 1


def test_localize_breaker(tmp_path, monkeypatch):
    def boom(u, **kw): raise RuntimeError("403")
    monkeypatch.setattr(douban, "_download", boom)
    monkeypatch.setattr(douban.time, "sleep", lambda s: None)
    c = _db()
    rep = douban.localize_covers(c, tmp_path, max_abort=2)
    assert rep["aborted"] and rep["fail"] == 2
    rows = dict(c.execute("SELECT id, cover_url FROM books").fetchall())
    assert rows[1].startswith("http")                           # 失败行不改库
    assert not any(tmp_path.iterdir())                          # 不留半截文件


def test_link_local(tmp_path):
    (tmp_path / "978C.jpg").write_bytes(b"x")    # 补无封面的行
    (tmp_path / "978B.jpg").write_bytes(b"x")    # 覆盖 http 占位图行
    (tmp_path / "999Z.png").write_bytes(b"x")    # 孤儿（无书对应）
    (tmp_path / "readme.txt").write_text("")     # 非图片忽略
    c = _db()
    rep = douban.link_local_covers(c, tmp_path)
    assert rep["files"] == 3 and rep["linked"] == 2 and rep["orphan"] == 1
    url = dict(c.execute("SELECT id, cover_url FROM books").fetchall())
    assert url[3] == "/covers/978C.jpg" and url[2] == "/covers/978B.jpg"
    assert url[1].startswith("http")          # 已本地化/正常热链的不乱动
    # 幂等：再跑一次 linked 归 0（已挂接的行不再匹配 UPDATE 条件）
    assert douban.link_local_covers(c, tmp_path)["linked"] == 0


def test_covers_static_mount(tmp_path):
    (tmp_path / "raw").mkdir()
    client = TestClient(create_app(tmp_path / "t.db", tmp_path))
    assert (tmp_path / "raw" / "covers").is_dir()               # 启动自动建目录
    (tmp_path / "raw" / "covers" / "978X.jpg").write_bytes(b"abc")
    r = client.get("/covers/978X.jpg")
    assert r.status_code == 200 and r.content == b"abc"
