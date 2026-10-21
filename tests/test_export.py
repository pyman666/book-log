"""导出：CSV / JSON，只导活库（回收站里的不算），字段与笔记文件名一并带走。"""
import json

from fastapi.testclient import TestClient

from app.main import create_app


def client(tmp_path):
    (tmp_path / "raw").mkdir()
    return TestClient(create_app(tmp_path / "t.db", tmp_path))


def test_csv_has_bom_header_and_live_books_only(tmp_path):
    c = client(tmp_path)
    (tmp_path / "raw" / "books").mkdir(parents=True)
    (tmp_path / "raw" / "books" / "导出书.md").write_text("# 笔记", encoding="utf-8")
    c.post("/api/books", json={
        "title": "导出书", "authors": ["作者甲", "作者乙"], "publishers": ["某社"],
        "categories": ["科幻"], "tags": ["年度最佳"], "price": 12.5,
        "isbn": "9787000000001", "status": "in_library"})
    gone = c.post("/api/books", json={"title": "回收书"}).json()
    c.delete(f"/api/books/{gone}")

    r = c.get("/api/export", params={"format": "csv"})
    assert r.status_code == 200
    assert "text/csv" in r.headers["content-type"]
    assert ".csv" in r.headers["content-disposition"]
    text = r.content.decode("utf-8")
    assert text.startswith("\ufeff书名,作者,国籍,分类,标签,出版社")
    lines = text.splitlines()
    assert "导出书" in text and "回收书" not in text
    row = next(line for line in lines if "导出书" in line)
    # 多值按「、」连；作者按库里 _names 的字母序，不保证录入顺序
    assert "作者甲" in row and "作者乙" in row and "、" in row
    assert "年度最佳" in row and "12.5" in row
    assert "导出书.md" in row          # 笔记文件名按命名法推导，一起带走


def test_json_export_has_full_fields(tmp_path):
    c = client(tmp_path)
    c.post("/api/books", json={"title": "甲", "tags": ["重读"], "price": 3})
    data = c.get("/api/export", params={"format": "json"}).json()
    assert data["count"] == 1 and data["exported_at"]
    b = data["books"][0]
    assert b["title"] == "甲" and b["tags"] == ["重读"] and b["price"] == 3
    assert "note_file" in b and "created" in b
    assert json.loads(c.get("/api/export", params={"format": "json"}).text)["count"] == 1


def test_export_rejects_unknown_format(tmp_path):
    c = client(tmp_path)
    assert c.get("/api/export", params={"format": "xml"}).status_code == 400
