"""豆瓣封面：抓取 og:image → books.cover_url →（可选）本地化 raw/covers/<isbn>.<ext>。

- 单本：fetch_cover_url(douban_id)，前端"补封面"按钮/新书按需调用
- 批量抓远程 URL：python -m app.douban                （原有逻辑，落库是热链地址）
- 批量本地化：python -m app.douban --localize         （远程图下载到 raw/covers/，
  cover_url 改 /covers/<isbn>.<ext>；豆瓣 2026-09 起 CDN 校验 Referer，热链在浏览器里 403）
- 手工补图挂接：python -m app.douban --link           （把 raw/covers/ 里按 isbn 命名的
  jpg/png 关联到书，覆盖无封面/占位图/热链行；orphan 报文件名）
所有网络模式共用纪律：2.5s+抖动限速、成功即提交、Ctrl-C 安全、连续 6 败刹车、幂等续跑。
"""
import argparse
import json
import random
import re
import sqlite3
import sys
import time
from pathlib import Path

import httpx

DB_PATH = Path(__file__).resolve().parent.parent / "books.db"
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
      "Referer": "https://book.douban.com/"}
OG = re.compile(r'<meta property="og:image"\s+content="([^"]+)"')
SMALL = re.compile(r"/(l|m)/public/")


def fetch_cover_url(douban_id: str, timeout: float = 12) -> str:
    """→ 小尺寸封面 URL；页面结构变化/被ban/网络错误 时抛 RuntimeError。"""
    try:
        r = httpx.get(f"https://book.douban.com/subject/{douban_id}/",
                      headers=UA, timeout=timeout, follow_redirects=True)
    except httpx.HTTPError as e:  # 超时/连接失败等统一成 RuntimeError，调用方只 catch 一种
        raise RuntimeError(f"网络错误: {type(e).__name__}") from e
    if r.status_code in (403, 418) or r.status_code >= 500:
        raise RuntimeError(f"HTTP {r.status_code}")
    m = OG.search(r.text)
    if not m:
        raise RuntimeError("页面无 og:image（可能ban或条目失效）")
    return SMALL.sub("/s/public/", m.group(1))


def backfill(db_path=DB_PATH, sleep=2.5, limit=None, max_abort=6):
    """遍历缺封面的记录逐本抓；成功即提交；连续失败 max_abort 次（疑似被ban）刹车。"""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT id, douban_id FROM books WHERE douban_id IS NOT NULL "
        "AND cover_url IS NULL ORDER BY id").fetchall()
    rep = {"ok": 0, "fail": 0, "aborted": False, "todo": len(rows)}
    fail_run = 0
    for i, r in enumerate(rows[:limit]):
        try:
            conn.execute("UPDATE books SET cover_url=? WHERE id=?",
                         (fetch_cover_url(r["douban_id"]), r["id"]))
            conn.commit()
            rep["ok"] += 1
            fail_run = 0
        except RuntimeError:
            rep["fail"] += 1
            fail_run += 1
            if fail_run >= max_abort:
                rep["aborted"] = True
                break
        time.sleep(sleep + random.uniform(0, 1.5))
    conn.close()
    return rep


def _download(url: str, timeout: float = 15) -> bytes:
    """拉一张远程封面字节；异常统一 RuntimeError（与 fetch_cover_url 同口径）。"""
    try:
        r = httpx.get(url, headers=UA, timeout=timeout, follow_redirects=True)
        r.raise_for_status()
    except httpx.HTTPError as e:
        raise RuntimeError(f"网络错误: {type(e).__name__}") from e
    return r.content


PLACEHOLDER = "book-static"   # 豆瓣无封面时的默认占位图路径，不值得落盘
EXTS = ("jpg", "jpeg", "png", "webp", "gif")


def _cover_path(covers_dir, isbn: str, url: str) -> Path:
    """按 isbn 定本地路径（扩展名取自远程 URL）。"""
    ext = url.rsplit(".", 1)[-1].lower()
    return covers_dir / f"{isbn}.{ext if ext in EXTS else 'jpg'}"


def fetch_cover_local(douban_id: str, isbn: str, covers_dir: Path) -> str:
    """新书单本：抓 og:image 并下载落盘 raw/covers/<isbn>，→ /covers/ 相对路径。
    占位图/无 isbn 时只回远程 URL（不存脏图）；网络/解析失败抛 RuntimeError。"""
    url = fetch_cover_url(douban_id)
    if not isbn or PLACEHOLDER in url:
        return url
    covers_dir.mkdir(parents=True, exist_ok=True)
    dest = _cover_path(covers_dir, isbn, url)
    if not dest.exists():
        try:
            dest.write_bytes(_download(url))
        except RuntimeError:
            dest.unlink(missing_ok=True)
            raise
    return f"/covers/{dest.name}"


def localize_covers(conn, covers_dir, *, sleep_s=2.5, jitter=1.5, max_abort=6, limit=None):
    """把远程 cover_url 下载到 covers_dir/<isbn>.<ext>，字段改写为 /covers/ 相对路径。
    幂等：文件已存在只改路径不再下载；豆瓣占位图跳过（留给 --link 人工补）；
    同 isbn 多行（多批次）共用一个文件；连续失败 max_abort 次刹车（防 ban）。"""
    covers_dir.mkdir(parents=True, exist_ok=True)
    rows = conn.execute(
        "SELECT id, isbn, cover_url FROM books "
        "WHERE cover_url LIKE 'http%' AND isbn IS NOT NULL AND isbn != '' ORDER BY id"
    ).fetchall()
    rep = {"downloaded": 0, "path_only": 0, "placeholder": 0, "fail": 0,
           "aborted": False, "todo": len(rows)}
    fail_run = 0
    for r in rows[:limit]:
        if PLACEHOLDER in r["cover_url"]:
            rep["placeholder"] += 1
            continue
        dest = _cover_path(covers_dir, r["isbn"], r["cover_url"])
        if dest.exists():
            rep["path_only"] += 1
        else:
            try:
                dest.write_bytes(_download(r["cover_url"]))
            except RuntimeError:
                dest.unlink(missing_ok=True)
                rep["fail"] += 1
                fail_run += 1
                if fail_run >= max_abort:
                    rep["aborted"] = True
                    break
                continue
            rep["downloaded"] += 1
            fail_run = 0
            time.sleep(sleep_s + random.uniform(0, jitter))
        conn.execute("UPDATE books SET cover_url=? WHERE id=?", (f"/covers/{dest.name}", r["id"]))
        conn.commit()
    return rep


def link_local_covers(conn, covers_dir):
    """把 covers_dir 里 <isbn>.<ext> 手工/已下载图片挂到对应书行。
    只改写「无封面 or 还是远程热链」的行，已本地化的不覆盖；报 orphan（无书对应的文件）。"""
    rep = {"files": 0, "linked": 0, "orphan": 0, "orphans": []}
    if not covers_dir.is_dir():
        return rep
    for p in sorted(covers_dir.iterdir()):
        if p.suffix.lower().lstrip(".") not in EXTS:
            continue
        rep["files"] += 1
        cur = conn.execute(
            "UPDATE books SET cover_url=? WHERE isbn=? "
            "AND (cover_url IS NULL OR cover_url = '' OR cover_url LIKE 'http%')",
            (f"/covers/{p.name}", p.stem))
        rep["linked"] += cur.rowcount
        if cur.rowcount == 0:
            rep["orphan"] += 1
            rep["orphans"].append(p.name)
    conn.commit()
    return rep


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--test", help="只抓单个 douban_id 打印结果")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--localize", action="store_true",
                    help="远程封面下载到 raw/covers/<isbn> 并改写 cover_url（限速，可断点续跑）")
    ap.add_argument("--link", action="store_true",
                    help="把 raw/covers/ 里手工放的 <isbn>.jpg/png 挂到书")
    ap.add_argument("--db", default=str(DB_PATH))
    args = ap.parse_args()
    if args.test:
        print(json.dumps({"cover_url": fetch_cover_url(args.test)}, ensure_ascii=False))
        return
    covers_dir = Path(args.db).resolve().parent / "raw" / "covers"
    if args.link:
        conn = sqlite3.connect(args.db)
        conn.row_factory = sqlite3.Row
        rep = link_local_covers(conn, covers_dir)
        conn.close()
        print(json.dumps(rep, ensure_ascii=False))
        return
    if args.localize:
        conn = sqlite3.connect(args.db)
        conn.row_factory = sqlite3.Row
        rep = localize_covers(conn, covers_dir, limit=args.limit)
        conn.close()
        print(json.dumps(rep, ensure_ascii=False))
        sys.exit(1 if rep["aborted"] else 0)
    rep = backfill(limit=args.limit)
    print(json.dumps(rep, ensure_ascii=False))
    sys.exit(1 if rep["aborted"] else 0)


if __name__ == "__main__":
    main()
