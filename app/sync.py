"""raw/books/ 内容与 db 对账。"""
import re
from pathlib import Path

from . import db as dbmod

_STUB = {"isbn": None, "price": None, "importance": None, "progress": None, "rating": None,
         "created": None, "last_modified": None, "authors": [], "publishers": [],
         "categories": [], "platform": None}

_QUAL = re.compile(r"^(.+?)（([^（）]+)）$")   # 撞名消歧文件名：书名（作者）


def _match(conn, fp, stem):
    """文件名 → 记录 id。空 file_path 的行才有资格被挂，绝不抢别人已挂的文件。"""
    hit = conn.execute(
        "SELECT id FROM books WHERE title = ? AND (file_path IS NULL OR file_path = '') "
        "ORDER BY id LIMIT 1", (stem,)).fetchone()
    if hit:
        return hit["id"]
    # 书名（限定）.md：整名匹配不上时，剥尾括号按「书名+作者」二次关联（方案 A 撞名消歧）
    m = _QUAL.match(stem)
    if m:
        hit = conn.execute(
            "SELECT b.id FROM books b "
            "JOIN book_authors ba ON ba.book_id = b.id "
            "JOIN authors a ON a.id = ba.author_id "
            "WHERE b.title = ? AND a.name LIKE ? AND (b.file_path IS NULL OR b.file_path = '') "
            "ORDER BY b.id LIMIT 1", (m.group(1), f"%{m.group(2)}%")).fetchone()
        if hit:
            return hit["id"]
    return None


def sync_vault(conn, root: Path) -> dict:
    """- raw/books/ 有 md 未关联 → 挂到同名记录（或「书名（作者）」消歧匹配的作者行）；
       都匹配不上 → 建存根（title=文件名，含限定后缀，人眼可读、可再改名）
       - 记录在库且有 file_path 但文件不存在 → 只报告，不自动删数据
       撞名不同书（父与子·屠格涅夫 vs 父与子·卜劳恩）：裸「书名.md」按 id 序给第一条
       同名空行；其余各书请命名为「书名（作者）.md」走二次关联。"""
    report = {"created": [], "linked": [], "missing": []}
    books = Path(root) / "raw" / "books"
    if books.is_dir():
        for f in sorted(books.glob("*.md")):
            fp = f"raw/books/{f.name}"
            if conn.execute("SELECT 1 FROM books WHERE file_path = ?", (fp,)).fetchone():
                continue                                    # 该文件已有关联记录
            bid = _match(conn, fp, f.stem)
            if bid is not None:
                conn.execute("UPDATE books SET file_path = ? WHERE id = ?", (fp, bid))
                conn.commit()
                report["linked"].append(fp)
            else:
                dbmod.save_book(conn, {**_STUB, "title": f.stem, "status": "in_library",
                                       "file_path": fp})
                report["created"].append(f.stem)
    for r in conn.execute(
            "SELECT id, title, file_path FROM books "
            "WHERE status = 'in_library' AND file_path IS NOT NULL"):
        if not (Path(root) / r["file_path"]).exists():
            report["missing"].append({"id": r["id"], "title": r["title"]})
    return report
