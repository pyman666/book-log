"""笔记文件名推导（app/notes.py）：不入库、不写库、撞名有归属。

取代原来的 tests/test_sync.py——Sync 会写库（建存根），现在没有可写的东西了。
"""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import db as dbmod, notes
from app.main import create_app


def _mk(root, *names):
    d = Path(root) / "raw" / "books"
    d.mkdir(parents=True, exist_ok=True)
    for n in names:
        (d / f"{n}.md").write_text(f"{n} 的正文内容", encoding="utf-8")


@pytest.fixture
def client(tmp_path):
    return TestClient(create_app(tmp_path / "t.db", tmp_path))


def _derived(c):
    with dbmod.db_conn(c.app.state.db_path) as conn:
        return notes.resolve(conn, c.app.state.root)


def _audit(c):
    with dbmod.db_conn(c.app.state.db_path) as conn:
        return notes.audit(conn, c.app.state.root)


def test_books_table_no_longer_stores_paths(client):
    with dbmod.db_conn(client.app.state.db_path) as conn:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(books)")}
    assert "file_path" not in cols


def test_payload_carries_derived_note_file(client):
    bid = client.post("/api/books", json={"title": "甲书", "authors": ["张三"]}).json()
    _mk(client.app.state.root, "甲书")
    item = client.get("/api/books").json()["items"][0]
    assert item["note_file"] == "甲书.md"
    assert client.get(f"/api/books/{bid}").json()["note_file"] == "甲书.md"


def test_adding_md_needs_no_sync(client):
    """根治的目标：新写一个 md 就自动被认出来，没有 Sync 这一步。"""
    bid = client.post("/api/books", json={"title": "新笔记书"}).json()
    assert client.get(f"/api/books/{bid}/content").status_code == 404
    _mk(client.app.state.root, "新笔记书")
    r = client.get(f"/api/books/{bid}/content")
    assert r.status_code == 200 and "新笔记书 的正文内容" in r.text


def test_client_sent_file_path_is_ignored(client):
    """客户端再传 file_path 也没用：库里没这列，路径只认命名法。"""
    _mk(client.app.state.root, "甲书")
    bid = client.post("/api/books", json={"title": "乙书", "file_path": "raw/books/甲书.md"}).json()
    assert _derived(client) == {}                        # 甲书.md 不属于乙书
    assert client.get(f"/api/books/{bid}/content").status_code == 404
    assert _audit(client)["files_unclaimed"] == ["甲书.md"]


def test_note_path_blocks_traversal(client):
    root = client.app.state.root
    p = notes.note_path(root, "../secret.md")
    assert p is not None and p.parent == (root / "raw" / "books").resolve()   # 只剩文件名


def test_collision_bare_name_goes_to_earliest_author_group(client):
    """《父与子》屠格涅夫(204) 与 卜劳恩(205)：裸名只归 id 序最早的作者组合。"""
    b1 = client.post("/api/books", json={"title": "父与子", "authors": ["屠格涅夫"]}).json()
    b2 = client.post("/api/books", json={"title": "父与子", "authors": ["卜劳恩"]}).json()
    _mk(client.app.state.root, "父与子")
    d = _derived(client)
    assert d == {b1: "父与子.md"}                        # 宁可让 b2 无正文，也不塞错笔记
    assert b2 not in d


def test_qualified_file_takes_precedence(client):
    b1 = client.post("/api/books", json={"title": "父与子", "authors": ["屠格涅夫"]}).json()
    b2 = client.post("/api/books", json={"title": "父与子", "authors": ["卜劳恩"]}).json()
    _mk(client.app.state.root, "父与子", "父与子（卜劳恩）")
    assert _derived(client) == {b1: "父与子.md", b2: "父与子（卜劳恩）.md"}


def test_qualified_tag_matches_author_partial_name(client):
    """文件名里的标签与作者名互相包含即命中：「卡洛·卜劳恩」认 `父与子（卜劳恩）.md`。"""
    bid = client.post("/api/books", json={"title": "父与子", "authors": ["卡洛·卜劳恩"]}).json()
    _mk(client.app.state.root, "父与子（卜劳恩）")
    assert _derived(client) == {bid: "父与子（卜劳恩）.md"}


def test_same_book_multiple_batches_share_one_note(client):
    b1 = client.post("/api/books", json={"title": "局外人", "authors": ["加缪"],
                                         "created": "January 5, 2023 9:00 AM"}).json()
    b2 = client.post("/api/books", json={"title": "局外人", "authors": ["加缪"],
                                         "created": "June 6, 2024 9:00 AM"}).json()
    _mk(client.app.state.root, "局外人")
    assert _derived(client) == {b1: "局外人.md", b2: "局外人.md"}


def test_title_tail_paren_peels_to_shared_note(client):
    """「围城（盗版）」与「围城」是同一本书 → 共用 围城.md。"""
    b1 = client.post("/api/books", json={"title": "围城（盗版）", "authors": ["钱钟书"]}).json()
    b2 = client.post("/api/books", json={"title": "围城", "authors": ["钱钟书"]}).json()
    _mk(client.app.state.root, "围城")
    assert _derived(client) == {b1: "围城.md", b2: "围城.md"}


def test_resolve_never_writes_the_database(client):
    db = Path(client.app.state.db_path)
    client.post("/api/books", json={"title": "只读书"})
    _mk(client.app.state.root, "只读书")
    before = (db.stat().st_mtime_ns, db.stat().st_size)
    with dbmod.db_conn(db) as conn:
        assert notes.resolve(conn, client.app.state.root)
        assert notes.audit(conn, client.app.state.root)["notes_on_disk"] == 1
    assert (db.stat().st_mtime_ns, db.stat().st_size) == before


def test_audit_two_directions(client):
    bid = client.post("/api/books", json={"title": "有笔记的书"}).json()
    client.post("/api/books", json={"title": "光有记录没笔记"})
    _mk(client.app.state.root, "有笔记的书", "没人认领的文件")
    a = _audit(client)
    assert a["notes_on_disk"] == 2 and a["books_with_note"] == 1
    assert a["files_unclaimed"] == ["没人认领的文件.md"]
    assert a["in_library_without_note"] == [{"id": bid + 1, "title": "光有记录没笔记"}]


def test_cli_audit_prints_report(tmp_path):
    """`python -m app.notes` 是体检的唯一入口（网页按钮已删）——输出 JSON，不写库。"""
    import json
    import subprocess
    import sys
    db = tmp_path / "cli.db"
    with dbmod.db_conn(db) as conn:
        dbmod.init_db(conn)
        dbmod.save_book(conn, {"title": "体检书", "status": "in_library", "authors": []})
    _mk(tmp_path, "体检书", "没人认领的文件")
    r = subprocess.run([sys.executable, "-m", "app.notes", "--db", str(db)], capture_output=True,
                       text=True, encoding="utf-8", cwd=Path(__file__).resolve().parent.parent)
    assert r.returncode == 0, r.stderr
    rep = json.loads(r.stdout)
    assert rep["notes_on_disk"] == 2 and rep["books_with_note"] == 1
    assert rep["files_unclaimed"] == ["没人认领的文件.md"]
