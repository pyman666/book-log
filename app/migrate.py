"""一次性迁移：Books/*.md(frontmatter) + Books/~售出.md → books.db；
内容移到 raw/books/（剥 frontmatter）；旧 Dataview 索引页归档 _trash/。

用法（仓库根目录）：
  .venv/bin/python -m app.migrate --dry-run   # 只报告不写
  .venv/bin/python -m app.migrate             # 执行（books 表非空时拒绝）
  .venv/bin/python -m app.migrate --force     # 非空表上重跑
"""
import argparse
import json
import shutil
from pathlib import Path

from . import db as dbmod
from .parsers import parse_book, parse_sold_table, split_frontmatter

ROOT = Path(__file__).resolve().parent.parent
BOOKS_DIR = ROOT / "Books"
RAW_DIR = ROOT / "raw" / "books"
TRASH = ROOT / "_trash"
DB_PATH = ROOT / "books.db"

INDEX_FILES = ["📚 Books 总览.md"]
INDEX_DIRS = ["Authors", "Publishers", "Categories", "Platforms"]


def collect():
    if not BOOKS_DIR.is_dir() or not list(BOOKS_DIR.glob("*.md")):
        raise SystemExit("Books/ 源目录不存在（已迁移过？）。重建需先从 git 历史恢复 Books/，再用 --force")
    books, errors = [], []
    for f in sorted(BOOKS_DIR.glob("*.md")):
        if f.name == "~售出.md":
            continue
        try:
            b = parse_book(f.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            errors.append(f"{f.name}: {e}")
            continue
        b["file_path"] = f.name
        books.append(b)
    sold = parse_sold_table((BOOKS_DIR / "~售出.md").read_text(encoding="utf-8"))
    return books, sold, errors


def run(dry_run=False, force=False):
    books, sold, errors = collect()
    report = {
        "in_library": len(books),
        "sold": len(sold),
        "total": len(books) + len(sold),
        "in_library_with_price": sum(1 for b in books if b["price"] is not None),
        "in_library_with_rating": sum(1 for b in books if b["rating"] is not None),
        "errors": errors,
    }
    if dry_run:
        return report
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    with dbmod.db_conn(DB_PATH) as conn:
        dbmod.init_db(conn)
        n = conn.execute("SELECT COUNT(*) FROM books").fetchone()[0]
        if n and not force:
            raise SystemExit(f"books 表已有 {n} 行，拒绝重复迁移（确认后用 --force）")
        for b in books:
            dbmod.save_book(conn, b)
        for b in sold:
            dup = conn.execute(
                """SELECT 1 FROM books b LEFT JOIN platforms f ON f.id = b.platform_id
                   WHERE b.status = 'sold' AND b.title = ? AND b.price IS ?
                   AND b.isbn IS ? AND f.name IS ?""",
                (b["title"], b["price"], b["isbn"], b["platform"])).fetchone()
            if not dup:
                dbmod.save_book(conn, b)
    for f in sorted(BOOKS_DIR.glob("*.md")):
        if f.name == "~售出.md":
            continue
        _meta, body = split_frontmatter(f.read_text(encoding="utf-8"))
        (RAW_DIR / f.name).write_text(body, encoding="utf-8")
        f.unlink()
    (BOOKS_DIR / "~售出.md").unlink()
    TRASH.mkdir(exist_ok=True)
    for name in INDEX_FILES:
        p = ROOT / name
        if p.is_file():
            shutil.move(str(p), str(TRASH / name))
    for d in INDEX_DIRS:
        src = ROOT / d
        if src.is_dir():
            shutil.move(str(src), str(TRASH / d))
    if BOOKS_DIR.is_dir() and not any(BOOKS_DIR.iterdir()):
        BOOKS_DIR.rmdir()
    return report


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="只报告不写")
    ap.add_argument("--force", action="store_true", help="允许在非空表上重跑")
    args = ap.parse_args()
    print(json.dumps(run(args.dry_run, args.force), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
