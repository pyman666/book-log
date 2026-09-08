"""书名 → raw/books/ 里的笔记文件名，纯推导，不入库。

库里不再存 file_path：文件名本来就是 (书名, 作者) 的函数，存了反而要 Sync，
Sync 反而造存根。推导规则（对全库逐条核过：121 条与旧 file_path 列完全相同，另修好 10 条指向已改名文件的死链）：

1. **作者限定文件** `书名（作者）.md`（括号里的标签与本书任一作者名互相包含）最优先
   ——真撞名靠它。
2. **裸文件** `书名.md` 只归「同名记录里 id 序最早的作者组合」那一组，组内所有记录
   共用（同一本书的不同版本/多批次 = 一组，所以 63/352/353 都看得到《卡拉马佐夫兄弟》）；
   别的作者组合拿不到它——宁可判无正文，也不把屠格涅夫的笔记塞给卜劳恩，
   后者该写 `父与子（卜劳恩）.md`。
3. 书名尾巴带限定括号的（`围城（盗版）`）**剥掉再走 1、2**，与正版共用一篇笔记。

推导要用到「同名记录有哪些」，所以一次算全库（resolve），别一条一条查。
"""
import re
from pathlib import Path

_TAIL_PAREN = re.compile(r"[（(][^（）()]*[）)]\s*$")   # 书名尾部的限定括号
_SEP = "\x01"                                       # group_concat 分隔符，作者名里不会有


def peel(title: str) -> str:
    """剥掉书名尾部的限定括号：'围城（盗版）' → '围城'；没有则原样返回。"""
    return _TAIL_PAREN.sub("", title or "").strip()


def names(title: str) -> list:
    """这本书可能的裸文件名候选：原书名 → 剥尾括号后的书名（去重保序）。"""
    return [n for n in dict.fromkeys([title, peel(title)]) if n]


def disk_stems(root) -> set:
    """raw/books/ 下所有 md 的文件名主干（不带 .md）。目录不存在则空集。"""
    d = Path(root) / "raw" / "books"
    return {f.stem for f in d.glob("*.md")} if d.is_dir() else set()


def note_path(root, note_file):
    """笔记文件名 → 绝对路径（挡住 ../ 逃逸）；不保证文件存在。"""
    if not note_file:
        return None
    books = (Path(root) / "raw" / "books").resolve()
    path = (books / Path(str(note_file)).name).resolve()
    return path if path.is_relative_to(books) else None


def _rows(conn):
    """全库 (id, title, 作者 frozenset)，按 id 升序——分组归属依赖这个顺序。"""
    return [(r["id"], r["title"], frozenset(x for x in (r["aus"] or "").split(_SEP) if x))
            for r in conn.execute(
                """SELECT b.id, b.title, group_concat(a.name, ?) AS aus
                     FROM books b LEFT JOIN book_authors ba ON ba.book_id = b.id
                     LEFT JOIN authors a ON a.id = ba.author_id
                    GROUP BY b.id ORDER BY b.id""", (_SEP,))]


def _qualifier_hit(stem, name, authors) -> bool:
    """stem 是否是「name（本书某作者）」：标签与作者名互相包含即命中
    （复现旧 sync 的 LIKE 宽容度：作者「卡洛·卜劳恩」也认 `父与子（卜劳恩）.md`）。"""
    if not stem.startswith(name + "（") or not stem.endswith("）"):
        return False
    tag = stem[len(name) + 1:-1]
    return any(tag in a or a in tag for a in authors)


def _resolve(conn, files: set) -> dict:
    recs = _rows(conn)
    owner = {}                                    # 裸名 → 有资格认领它的作者组合
    for _bid, title, aus in recs:                 #   = 同名记录里 id 序最早的那一组
        for n in names(title):
            owner.setdefault(n, aus)
    out = {}
    for bid, title, aus in recs:
        for n in names(title):
            if any(_qualifier_hit(f, n, aus) for f in files):            # 规则 1
                out[bid] = next(f for f in sorted(files)
                                if _qualifier_hit(f, n, aus)) + ".md"
                break
            if n in files and owner.get(n) == aus:                       # 规则 2
                out[bid] = f"{n}.md"
                break
    return out


def resolve(conn, root) -> dict:
    """book_id → 笔记文件名（含 .md）。只返回磁盘上确实有文件的书。"""
    return _resolve(conn, disk_stems(root))


def annotate(conn, root, books: list) -> list:
    """给 /api/books 与详情页的 payload 补 note_file 字段（None = 无正文）。"""
    owned = resolve(conn, root)
    for b in books:
        b["note_file"] = owned.get(b["id"])
    return books


def note_file_for(conn, root, bid) -> str:
    """单本的笔记文件名（给正文/摘要路由用），没有则 None。"""
    return resolve(conn, root).get(bid)


def audit(conn, root) -> dict:
    """只读体检（取代原先会写库的 Sync）：谁的文件没书认领、哪些在库的书没有笔记。"""
    owned = resolve(conn, root)
    on_disk = {f"{s}.md" for s in disk_stems(root)}
    in_lib = [(r["id"], r["title"]) for r in conn.execute(
        "SELECT id, title FROM books WHERE status = 'in_library' ORDER BY id")]
    return {
        "notes_on_disk": len(on_disk),
        "books_with_note": len(owned),
        "files_unclaimed": sorted(on_disk - set(owned.values())),
        "in_library_without_note": [{"id": i, "title": t} for i, t in in_lib if i not in owned],
    }


def main():
    """CLI：`uv run python -m app.notes` 打一份只读体检报告（JSON）。
    没有网页入口了——文件名写错时，书的行上会显示「无正文」，`files_unclaimed` 则指出
    磁盘上有谁没被认领。"""
    import argparse
    import json
    import sys
    from . import db as dbmod                       # 局部导入：db 不 import notes，无环
    if hasattr(sys.stdout, "reconfigure"):          # Windows 控制台 cp936/cp1252 打中文会 UnicodeEncodeError
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="笔记文件体检（只读，不写库）")
    ap.add_argument("--db", default=str(Path(__file__).resolve().parent.parent / "books.db"))
    args = ap.parse_args()
    with dbmod.db_conn(args.db) as conn:
        print(json.dumps(audit(conn, Path(args.db).resolve().parent), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
