"""按 ISBN 补全新书表单：豆瓣号 + 书名/作者/出版社，ISBN 必须与条目吻合。"""
import json
from types import SimpleNamespace

import httpx
from fastapi.testclient import TestClient

from app import douban
from app.main import create_app


def _search(*ids):
    items = ",".join(f'{{"id": {i}}}' for i in ids)
    return f'<script>window.__DATA__ = {{"items": [{items}]}};\n</script>'


def _subject(isbn, **meta):
    data = {"@type": "Book", "isbn": isbn, **meta}
    return f'<script type="application/ld+json">{json.dumps(data, ensure_ascii=False)}</script>'


def _stub(monkeypatch, search_ids, subject_html):
    def get(url, **kwargs):
        if "search.douban.com" in url:
            return SimpleNamespace(status_code=200, text=_search(*search_ids))
        return SimpleNamespace(status_code=200, text=subject_html)
    monkeypatch.setattr(douban.httpx, "get", get)


def client(tmp_path):
    return TestClient(create_app(tmp_path / "t.db", tmp_path))


def test_lookup_returns_book_meta(tmp_path, monkeypatch):
    _stub(monkeypatch, [2253642], _subject(
        "9787505723788", name="卡拉马佐夫兄弟",
        author=[{"@type": "Person", "name": "陀思妥耶夫斯基"},
                {"@type": "Person", "name": "陀思妥耶夫斯基"}],   # 重复名去重
        publisher={"@type": "Organization", "name": "上海译文出版社"}))
    r = client(tmp_path).get("/api/lookup/isbn", params={"isbn": "978-7505723788"})
    assert r.status_code == 200
    assert r.json() == {"douban_id": "2253642", "isbn": "9787505723788",
                        "title": "卡拉马佐夫兄弟", "authors": ["陀思妥耶夫斯基"],
                        "publishers": ["上海译文出版社"]}


def test_lookup_accepts_string_author_and_publisher_list(monkeypatch):
    """ld+json 的 author/publisher 可能是纯字符串或数组，两种都得认。"""
    _stub(monkeypatch, [1], _subject("9787505723788", name="书", author="某人",
                                     publisher=["甲社", "乙社"]))
    got = douban.lookup_book_by_isbn("9787505723788")
    assert got["authors"] == ["某人"] and got["publishers"] == ["甲社", "乙社"]


def test_lookup_rejects_bad_isbn_and_edition_mismatch(tmp_path, monkeypatch):
    c = client(tmp_path)
    _stub(monkeypatch, [123], _subject("9787505723789", name="别的版本"))
    r = c.get("/api/lookup/isbn", params={"isbn": "9787505723788"})
    assert r.status_code == 400 and "不一致" in r.json()["detail"]
    assert c.get("/api/lookup/isbn", params={"isbn": "../bad"}).status_code == 400
    _stub(monkeypatch, [], "")
    assert c.get("/api/lookup/isbn", params={"isbn": "9787505723788"}).status_code == 400


def test_lookup_maps_network_errors_to_502(tmp_path, monkeypatch):
    def boom(url, **kwargs):
        raise httpx.ConnectError("offline")
    monkeypatch.setattr(douban.httpx, "get", boom)
    r = client(tmp_path).get("/api/lookup/isbn", params={"isbn": "9787505723788"})
    assert r.status_code == 502 and "网络错误" in r.json()["detail"]
