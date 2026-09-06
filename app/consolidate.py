"""同名同作者（=同一书的不同版本/批次）的记录归拢：md 合并成一个，全部记录指向它。

- 分组键 = (书名去尾部括号限定, 作者串精确匹配)。同名不同作者 = 不同书，不动。
  （父与子〔卜劳恩〕 vs 父与子〔屠格涅夫〕 各自独立）
- 组内多个文件 → 合并进一个规范文件（优先 raw/books/书名.md；主文件取内容最多者）；其余删除。
- 组内 file_path 为 NULL 的记录（如空壳版本被 douban_ids 删文件后）也挂到规范文件。
- 豆瓣头由 app.douban_ids 先行剥除，本脚本合并前文件应已是纯笔记。
- 用法：uv run python -m app.consolidate [--dry-run]
"""
import argparse
import collections
import json
import re
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "books.db"


def base_title(t: str) -> str:
    return re.sub(r"（[^）]*）$", "", t)


def split_header(text: str):
    lines = text.splitlines()
    i = 0
    while i < len(lines) and not lines[i].strip():
        i += 1
    if i < len(lines) and lines[i].strip().startswith(">") and "book.douban.com" in lines[i]:
        j = i
        while j < len(lines) and (lines[j].strip().startswith(">") or not lines[j].strip()):
            if not lines[j].strip() and (j + 1 >= len(lines) or not lines[j + 1].strip().startswith(">")):
                break
            j += 1
        return "\n".join(lines[i:j]).rstrip(), "\n".join(lines[j:]).strip()
    return None, text.strip()


def read_file(p: Path):
    hdr, body = split_header(p.read_text(encoding="utf-8"))
    return hdr, body


def merge_group(files):
    """files: 绝对路径列表 → (canonical内容, 各文件并入统计)"""
    infos = [(f, *read_file(f)) for f in files]
    infos.sort(key=lambda x: -len(x[2]))          # 内容最多的作主文件
    canon_f, canon_hdr, canon_body = infos[0]
    seen = {l.strip() for l in canon_body.splitlines() if l.strip()}
    parts = [(canon_hdr or "") + ("\n\n" if canon_hdr else "") + canon_body]
    stats = [{"file": canon_f.relative_to(ROOT).as_posix(), "kept": len(canon_body.splitlines())}]
    for f, hdr, body in infos[1:]:
        new = []
        prev_blank = False
        for ln in body.splitlines():
            if not ln.strip():
                if not prev_blank and new:
                    new.append("")
                    prev_blank = True
                continue
            prev_blank = False
            if ln.strip() not in seen:
                seen.add(ln.strip())
                new.append(ln)
        stats.append({"file": f.relative_to(ROOT).as_posix(),
                      "merged_in": len(new), "dropped_dup": len(body.splitlines()) - len(new)})
        if new:
            parts.append(f"<!-- 并入自 {f.name} -->\n\n" + "\n".join(new))
    return canon_f, "\n\n".join(p for p in parts if p.strip()) + "\n", stats


def run(dry_run=False):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    groups = collections.defaultdict(lambda: {"files": {}, "ids": []})
    for r in conn.execute("""SELECT b.id, b.title, b.file_path, group_concat(a.name,'・') AS au
            FROM books b LEFT JOIN book_authors ba ON ba.book_id=b.id
            LEFT JOIN authors a ON a.id=ba.author_id GROUP BY b.id"""):
        g = groups[(base_title(r["title"]), r["au"] or "")]
        g["ids"].append(r["id"])
        p = ROOT / r["file_path"] if r["file_path"] else None
        if p and p.is_file():
            g["files"][p] = None

    report = {"merged_groups": [], "relinked_only": 0, "moved_out_sold": [], "renamed": [], "deleted": 0, "records_updated": 0}
    for (title, au), g in sorted(groups.items()):
        files = list(g["files"])
        if not files:
            continue
        if len(files) > 1:
            canon, content, stats = merge_group(files)
            want = ROOT / "raw" / "books" / (title.replace("/", "／") + ".md")
            # 规范名 raw/books/书名.md：组内已有就用它；磁盘上没被别的书占用就重命名过去；否则保留主文件原名
            # （同名不同书撞名时，后到者保留「书名（作者）.md」限定名，与 sync 的二轮关联约定一致）
            if want in files or not want.exists():
                target = want
                if target != canon:
                    report["renamed"].append({"from": canon.relative_to(ROOT).as_posix(), "to": target.relative_to(ROOT).as_posix()})
            else:
                target = canon
            report["deleted"] += len([f for f in files if f != target])
            report["merged_groups"].append({"book": f"{title}〔{au}〕", "target": target.relative_to(ROOT).as_posix(),
                                            "stats": stats, "records": len(g["ids"])})
        else:
            target = files[0]
            content = None
            # sold 目录废弃：单文件的组若住在 raw/sold/，把规范文件搬回 raw/books/
            if target.parent == ROOT / "raw" / "sold":
                want = ROOT / "raw" / "books" / target.name
                if not want.exists():
                    report["moved_out_sold"].append({"from": target.relative_to(ROOT).as_posix(),
                                                     "to": want.relative_to(ROOT).as_posix()})
                    content = target.read_text(encoding="utf-8")
                    target = want
            if len(g["ids"]) > 1 and any(
                    not conn.execute("SELECT file_path FROM books WHERE id=?", (i,)).fetchone()[0]
                    for i in g["ids"]):
                report["relinked_only"] += 1
        report["records_updated"] += len(g["ids"])
        if not dry_run:
            if content is not None:
                target.write_text(content, encoding="utf-8")
            for f in files:
                if f != target:
                    f.unlink()
            conn.executemany("UPDATE books SET file_path = ? WHERE id = ?",
                             [(target.relative_to(ROOT).as_posix(), i) for i in g["ids"]])
    if not dry_run:
        conn.commit()
    sold_dir = ROOT / "raw" / "sold"
    if not dry_run and sold_dir.is_dir() and not any(sold_dir.iterdir()):
        sold_dir.rmdir()
        report["sold_dir_removed"] = True
    conn.close()
    return report


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    print(json.dumps(run(args.dry_run), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
