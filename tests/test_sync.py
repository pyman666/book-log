"""raw/books/ 对账：建存根 / 挂接 / 撞名消歧（方案 A）/ 幂等。"""
from fastapi.testclient import TestClient

from app.main import create_app


def _mk(root, name, text="正文"):
    d = root / "raw" / "books"
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(text, encoding="utf-8")


def test_sync_creates_stubs_and_reports_missing(tmp_path):
    _mk(tmp_path, "新发现.md")
    c = TestClient(create_app(tmp_path / "t.db", tmp_path))
    bid = c.post("/api/books", json={"title": "没文件", "file_path": "raw/books/没文件.md"}).json()
    rep = c.post("/api/sync").json()
    assert "新发现" in rep["created"]                          # 有 md 无记录 → 建存根
    assert any(m["id"] == bid for m in rep["missing"])         # 有记录无文件 → 报告
    rep2 = c.post("/api/sync").json()
    assert "新发现" not in rep2["created"]                      # 幂等，不重复建
    assert c.get("/api/books", params={"q": "新发现"}).json()["total"] == 1
    stub = c.get("/api/books", params={"q": "新发现"}).json()["items"][0]
    assert stub["file_path"] == "raw/books/新发现.md"


def test_sync_links_record_without_file(tmp_path):
    """库里已有同名记录但 file_path 空 → 挂接，不新建。"""
    c = TestClient(create_app(tmp_path / "t.db", tmp_path))
    bid = c.post("/api/books", json={"title": "空链接书"}).json()
    _mk(tmp_path, "空链接书.md")
    rep = c.post("/api/sync").json()
    assert rep["created"] == [] and rep["linked"] == ["raw/books/空链接书.md"]
    assert c.get(f"/api/books/{bid}").json()["file_path"] == "raw/books/空链接书.md"
    assert c.post("/api/sync").json()["linked"] == []          # 幂等


def test_sync_collision_author_disambiguation(tmp_path):
    """同名不同书：裸「父与子.md」给 id 序第一行；「父与子（卜劳恩）.md」剥括号按作者二轮关联。"""
    c = TestClient(create_app(tmp_path / "t.db", tmp_path))
    b1 = c.post("/api/books", json={"title": "父与子", "authors": ["屠格涅夫"]}).json()
    b2 = c.post("/api/books", json={"title": "父与子", "authors": ["卜劳恩"]}).json()
    _mk(tmp_path, "父与子.md", "长篇小说")
    _mk(tmp_path, "父与子（卜劳恩）.md", "漫画绘本")
    rep = c.post("/api/sync").json()
    assert rep["created"] == []                                # 两文件都挂上，没造污染存根
    assert rep["linked"] == ["raw/books/父与子.md", "raw/books/父与子（卜劳恩）.md"]
    assert c.get(f"/api/books/{b1}").json()["file_path"] == "raw/books/父与子.md"
    assert c.get(f"/api/books/{b2}").json()["file_path"] == "raw/books/父与子（卜劳恩）.md"


def test_sync_never_steals_linked_file(tmp_path):
    """同名记录但 file_path 已被别的书占着 → 不再从别人手里抢文件。"""
    c = TestClient(create_app(tmp_path / "t.db", tmp_path))
    _mk(tmp_path, "甲书.md")
    b1 = c.post("/api/books", json={"title": "甲书", "file_path": "raw/books/甲书.md"}).json()
    b2 = c.post("/api/books", json={"title": "甲书"}).json()   # 同名不同书（未及消歧命名）
    rep = c.post("/api/sync").json()
    assert rep["linked"] == [] and rep["created"] == []        # 甲书.md 已关联，不重复挂给 b2
    assert c.get(f"/api/books/{b1}").json()["file_path"] == "raw/books/甲书.md"
    assert c.get(f"/api/books/{b2}").json()["file_path"] is None
