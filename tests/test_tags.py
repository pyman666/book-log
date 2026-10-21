"""标签：自由词多值维度，跟体裁分类（categories）分开。"""
from fastapi.testclient import TestClient

from app.main import create_app


def client(tmp_path):
    (tmp_path / "raw").mkdir()
    return TestClient(create_app(tmp_path / "t.db", tmp_path))


def test_tags_roundtrip_filter_and_clear(tmp_path):
    c = client(tmp_path)
    a = c.post("/api/books", json={"title": "甲", "tags": ["年度最佳", "重读"]}).json()
    b = c.post("/api/books", json={"title": "乙", "tags": ["待读"]}).json()

    assert c.get(f"/api/books/{a}").json()["tags"] == ["年度最佳", "重读"]
    assert c.get("/api/books", params={"tag": "重读"}).json()["total"] == 1
    assert set(c.get("/api/facets").json()["tags"]) >= {"年度最佳", "重读", "待读"}

    # 显式空列表 = 清空；不带 tags 的部分更新不碰标签
    c.put(f"/api/books/{a}", json={"tags": []})
    assert c.get(f"/api/books/{a}").json()["tags"] == []
    assert c.get("/api/books", params={"tag": "重读"}).json()["total"] == 0
    c.put(f"/api/books/{b}", json={"rating": 8})
    assert c.get(f"/api/books/{b}").json()["tags"] == ["待读"]


def test_stats_group_by_tag(tmp_path):
    c = client(tmp_path)
    c.post("/api/books", json={"title": "甲", "price": 10, "tags": ["重读", "年度最佳"]})
    c.post("/api/books", json={"title": "乙", "price": 20, "tags": ["重读"]})
    rows = {r["key"]: r for r in c.get("/api/stats/group", params={"by": "tag"}).json()}
    assert rows["重读"]["count"] == 2
    assert rows["年度最佳"]["count"] == 1
    money = {r["key"]: r for r in c.get(
        "/api/stats/group", params={"by": "tag", "agg": "sum_price"}).json()}
    assert money["重读"]["value"] == 30


def test_tag_is_not_a_category(tmp_path):
    """标签不进口味光谱：只打标签、不填分类的书仍算「思想·人文·实用」，不会被当成体裁。"""
    c = client(tmp_path)
    c.post("/api/books", json={"title": "标签书", "tags": ["长篇"]})
    axes = c.get("/api/stats/spectrum").json()
    form = {s["key"]: s["value"] for s in axes[0]["segments"]}
    assert form == {"思想·人文·实用": 1}
