"""一次性恢复：notion-export 里流失的笔记 → raw/books/。

背景：当年从 notion-export 整理进 Books/ 时，在库书截掉了部分笔记（17 本）；
售出/送出的书只留了元数据，65 本书的笔记只存在于 raw/notion-export/。

- 在库：notion 页有、raw 文件没有的笔记行，追加到重叠度最高的 raw 文件，
  以 "## 补：来自 Notion 导出" 分节标记，不动已有内容。
- 售出：笔记（去导出模板）写入 raw/books/<书名>.md，db 中对应 sold 记录挂上 file_path。
  同书多批次共享一个笔记文件；导出页之间的重复行按序去重。

用法（仓库根目录）：
  uv run python -m app.recover_notion --dry-run   # 只报告
  uv run python -m app.recover_notion             # 执行
"""
import argparse
import json
import re
import sqlite3
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAGES = ROOT / "raw" / "notion-export" / "Reading" / "Books"
RAW = ROOT / "raw" / "books"
SOLD = RAW          # 已废弃的 raw/sold 不再重建：售出笔记与在库版本同住 raw/books/（同一 md）
DB_PATH = ROOT / "books.db"

FLD = re.compile(r"^\s*(?:📖\s*)?(?:Author|Category|ISBN|Price|Platform|🏢 Publisher|Importance|Progress|Rating|Created|Last)\s*:")
DBLNK = re.compile(r"^\[.*\]\(https?://book\.douban\.com/.*\)\s*$")
SUFFIX = re.compile(r"（(售出|送出)）")


def page_title(f: Path) -> str:
    return re.sub(r" [0-9a-f]{32}$", "", f.stem)


def base_of(t: str) -> str:
    """去（售出）/（送出）标记，再去尾部括号限定（版本/盗版等），用于跨页/文件归并"""
    return re.sub(r"（[^）]*）$", "", SUFFIX.sub("", t))


def note_lines(f: Path) -> list[str]:
    """剥 frontmatter、导出模板字段、标题行、douban 链接行，保留真实笔记"""
    t = f.read_text(encoding="utf-8")
    fm = re.match(r"^---\n.*?\n---\n", t, re.S)
    if fm:
        t = t[fm.end():]
    title = page_title(f)
    out = []
    for ln in t.splitlines():
        s = ln.strip()
        if not s or FLD.match(ln) or DBLNK.match(s):
            continue
        if s.startswith("# ") and SUFFIX.sub("", s[2:].strip()) == SUFFIX.sub("", title):
            continue
        if s.startswith(">") and "book.douban.com" in s:
            continue
        out.append(ln.rstrip())
    return out


def collect_pages():
    sold, allp = defaultdict(list), defaultdict(list)
    for f in sorted(PAGES.glob("*.md")):
        t = page_title(f)
        (sold if SUFFIX.search(t) else allp)[base_of(t)].append(note_lines(f))
    return sold, allp


def merge(line_groups):
    seen, out = set(), []
    for lines in line_groups:
        for ln in lines:
            if ln.strip() and ln.strip() not in seen:
                seen.add(ln.strip())
                out.append(ln)
    return out


def raw_bases():
    d = defaultdict(list)
    for f in sorted(RAW.glob("*.md")):
        d[base_of(f.stem)].append(f)
    return d


def run(dry_run=False):
    global SOLD
    sold_pages, all_pages = collect_pages()
    rb = raw_bases()
    report = {"append_in_library": [], "sold_files": 0, "sold_records_linked": 0}

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    # ② 在库：追加缺失行
    for base, files in sorted(rb.items()):
        existing_files = [f.read_text(encoding="utf-8") for f in files]
        existing = {s for txt in existing_files for s in map(str.strip, txt.splitlines()) if s}
        pn = merge(all_pages.get(base, []))
        missing = [ln for ln in pn if ln.strip() and ln.strip() not in existing]
        if len(missing) <= 2:
            continue
        # 目标文件：与 notion 笔记重叠度最高者
        def overlap(f):
            ls = {s for s in map(str.strip, f.read_text(encoding="utf-8").splitlines()) if s}
            return len(ls & {ln.strip() for ln in pn})
        target = max(files, key=overlap)
        report["append_in_library"].append({"file": target.name, "lines": len(missing)})
        if not dry_run:
            block = "\n\n## 补：来自 Notion 导出\n\n" + "\n".join(missing) + "\n"
            with target.open("a", encoding="utf-8") as fh:
                fh.write(block)

    # ③ 售出：写 raw/books/*.md 并挂 file_path
    SOLD.mkdir(parents=True, exist_ok=True)
    written = {}
    for r in conn.execute("SELECT id, title FROM books WHERE status = 'sold'").fetchall():
        base = base_of(r["title"])
        if not (SUFFIX.search(r["title"]) or base in sold_pages):
            if base not in all_pages:      # 只有 notion 未售出页可参考的兜底（如 泰伯文化研究）
                continue
        groups = sold_pages.get(base) or (all_pages.get(base) if base not in rb else None)
        # base 同时有在库文件时，不允许用未标记售出的页（那是在库版本的页）
        if not groups:
            continue
        if base not in written:
            body = merge(groups)
            if len(body) <= 2:
                written[base] = None
                continue
            fname = base.replace("/", "／") + ".md"
            if not dry_run:
                (SOLD / fname).write_text("\n".join(body) + "\n", encoding="utf-8")
            written[base] = f"raw/books/{fname}"
        if written[base]:
            report["sold_records_linked"] += 1
            if not dry_run:
                conn.execute("UPDATE books SET file_path = ? WHERE id = ?", (written[base], r["id"]))
    report["sold_files"] = sum(1 for v in written.values() if v)
    if not dry_run:
        conn.commit()
    conn.close()
    return report


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    print(json.dumps(run(args.dry_run), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
