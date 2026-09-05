"""raw/ 内容与 db 对账。"""
from pathlib import Path

from . import db as dbmod

_STUB = {"isbn": None, "price": None, "importance": None, "progress": None, "rating": None,
         "created": None, "last_modified": None, "authors": [], "publishers": [],
         "categories": [], "platform": None}


def sync_vault(conn, root: Path) -> dict:
    """- raw/ 有 md 无记录 → 建存根（title=文件名）；已有同名记录但 file_path 空 → 补 file_path
       - 记录在库且有 file_path 但文件不存在 → 只报告，不自动删数据"""
    report = {"created": [], "missing": []}
    raw = Path(root) / "raw"
    if raw.is_dir():
        for f in sorted(raw.glob("*.md")):
            fp = f"raw/{f.name}"
            hit = conn.execute(
                "SELECT id, file_path FROM books WHERE file_path = ? OR title = ?",
                (fp, f.stem)).fetchone()
            if hit:
                if not hit["file_path"]:
                    conn.execute("UPDATE books SET file_path = ? WHERE id = ?", (fp, hit["id"]))
                    conn.commit()
                continue
            dbmod.save_book(conn, {**_STUB, "title": f.stem, "status": "in_library",
                                   "file_path": fp})
            report["created"].append(f.stem)
    for r in conn.execute(
            "SELECT id, title, file_path FROM books "
            "WHERE status = 'in_library' AND file_path IS NOT NULL"):
        if not (Path(root) / r["file_path"]).exists():
            report["missing"].append({"id": r["id"], "title": r["title"]})
    return report
