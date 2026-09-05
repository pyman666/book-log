from fastapi.testclient import TestClient

from app.main import create_app


def test_sync_creates_stubs_and_reports_missing(tmp_path):
    (tmp_path / "raw").mkdir()
    (tmp_path / "raw" / "新发现.md").write_text("正文", encoding="utf-8")
    c = TestClient(create_app(tmp_path / "t.db", tmp_path))
    bid = c.post("/api/books", json={"title": "没文件", "file_path": "raw/没文件.md"}).json()
    rep = c.post("/api/sync").json()
    assert "新发现" in rep["created"]                          # 有 md 无记录 → 建存根
    assert any(m["id"] == bid for m in rep["missing"])         # 有记录无文件 → 报告
    rep2 = c.post("/api/sync").json()
    assert "新发现" not in rep2["created"]                      # 幂等，不重复建
    assert c.get("/api/books", params={"q": "新发现"}).json()["total"] == 1
    stub = c.get("/api/books", params={"q": "新发现"}).json()["items"][0]
    assert stub["file_path"] == "raw/新发现.md"
