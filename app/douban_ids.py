"""一次性任务：把豆瓣 subject 号提进 books.douban_id，并删掉 md 头部的豆瓣引用块。

- 号源1：raw 文件头 `> **[📖 书名](https://book.douban.com/subject/5406559/)**`（含变体：裸链接行）
- 号源2（兜底）：raw/notion/ 同名页面里的 subject 链接
- 剥离规则：首个非空行是以 > 开头且含 book.douban.com/📖 的引用行，则吃掉紧相邻的连续 > 行
  （用户自己的笔记引用前有空行，紧相邻规则不会误吃）。再检查一行裸链接。
- 剥完无正文 → 删文件、file_path 置 NULL（sync 不会反向重建；前端按 NULL 显示"无正文"）。
- 必须在 app.consolidate 之前跑：每个版本的 subject 号只存在于各自文件头。

用法：
  uv run python -m app.douban_ids --dry-run
  uv run python -m app.douban_ids
"""
import argparse
import json
import re
import sqlite3
from collections import defaultdict
from pathlib import Path

from .paths import resolve_book_path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "books.db"
NOTION_BOOKS = ROOT / "raw" / "notion"

SUBJ = re.compile(r"book\.douban\.com/subject/(\d+)")
BARE = re.compile(r"^(\[[^\]]*\]\((https?://)?book\.douban\.com/subject/\d+/\)\**|(https?://)?book\.douban\.com/subject/\d+/?\**)$")
SUFFIX = re.compile(r"\s*(（售出）|（送出）)?\s*[0-9a-f]{32}\s*$")
PAREN = re.compile(r"（[^）]*）$")


def base_title(t):
    return PAREN.sub("", t or "")


def notion_id_index():
    idx = defaultdict(lambda: defaultdict(int))
    for p in NOTION_BOOKS.glob("*.md"):
        m = SUBJ.search(p.read_text(encoding="utf-8"))
        if m:
            idx[base_title(SUFFIX.sub("", p.stem))][m.group(1)] += 1
    # 仅当同名页面都指向同一 subject 号才采信
    return {t: (next(iter(c)) if len(c) == 1 else None) for t, c in idx.items()}


def strip_header(text):
    """循环剥掉开头的豆瓣/百科引用块（紧相邻 > 行）与裸链接行。→ (douban_id|None, 剩余正文)"""
    lines = text.splitlines()
    did = None
    while True:
        i = 0
        while i < len(lines) and not lines[i].strip():
            i += 1
        if i >= len(lines):
            break
        head = lines[i].strip()
        if head.startswith(">") and ("📖" in head or "book.douban.com" in head):
            j = i
            while j < len(lines) and lines[j].strip().startswith(">"):
                j += 1
            m = SUBJ.search("\n".join(lines[i:j]))
            did = did or (m.group(1) if m else None)
            lines = lines[j:]
            continue
        if BARE.match(head):
            m = SUBJ.search(head)
            did = did or (m.group(1) if m else None)
            lines = lines[i + 1:]
            continue
        break
    return did, "\n".join(lines).strip()


def run(dry_run=False):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    nidx = notion_id_index()
    rep = {"stripped": 0, "emptied_deleted": 0, "id_from_file": 0, "id_from_notion": 0}
    seen_files = set()
    for r in conn.execute("SELECT id, title, file_path, douban_id FROM books WHERE file_path IS NOT NULL").fetchall():
        try:
            p = resolve_book_path(ROOT, r["file_path"])
        except ValueError:
            continue
        if not p.is_file() or str(p) in seen_files:
            continue
        seen_files.add(str(p))
        text = p.read_text(encoding="utf-8")
        did, rest = strip_header(text)
        if did:
            rep["id_from_file"] += 1
            if not dry_run:
                conn.execute("UPDATE books SET douban_id = ? WHERE id = ? AND douban_id IS NULL", (did, r["id"]))
        if rest == text.strip():
            continue
        rep["stripped"] += 1
        if rest:
            if not dry_run:
                p.write_text(rest + "\n", encoding="utf-8")
        else:
            rep["emptied_deleted"] += 1
            if not dry_run:
                p.unlink()
                conn.execute("UPDATE books SET file_path = NULL WHERE id = ?", (r["id"],))
    # 同一文件可能被多条记录共享（sold 两批），把号同步过去
    if not dry_run:
        conn.execute("""UPDATE books SET douban_id = (
              SELECT b2.douban_id FROM books b2 WHERE b2.file_path = books.file_path AND b2.douban_id IS NOT NULL LIMIT 1)
            WHERE douban_id IS NULL AND file_path IS NOT NULL""")
    for r in conn.execute("SELECT id, title FROM books WHERE douban_id IS NULL").fetchall():
        did = nidx.get(base_title(r["title"]))
        if did:
            rep["id_from_notion"] += 1
            if not dry_run:
                conn.execute("UPDATE books SET douban_id = ? WHERE id = ?", (did, r["id"]))
    if not dry_run:
        conn.commit()
    rep["still_no_id"] = conn.execute("SELECT COUNT(*) FROM books WHERE douban_id IS NULL").fetchone()[0]
    conn.close()
    return rep


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    print(json.dumps(run(args.dry_run), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
