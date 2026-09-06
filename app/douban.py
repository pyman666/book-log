"""豆瓣封面：以 douban_id 为真源，抓取 og:image 并落盘 raw/covers/<isbn>.<ext>。

封面真值 = 磁盘上是否存在 `<isbn>.<ext>` 文件（DB 不再存 cover_url，douban_id 才是可重推的根）。

- 单本：fetch_cover_local(douban_id, isbn, dir)，前端“抓封面”按钮按需调用
- 批量：python -m app.douban --localize [--limit N]
  遍历有 douban_id+isbn 且尚无本地封面的书，逐本 og:image→下载落盘。
  （豆瓣 2026-09 起 CDN 校验 Referer，热链在浏览器里 403，必须本地化）
- 单页测试：python -m app.douban --test <douban_id>（只打印 og:image URL）
网络纪律：2.5s+抖动限速、成功即落盘、Ctrl-C 安全、连续 6 败刹车、幂等续跑（文件在就跳）。
手工补图：直接把图命名为 <isbn>.jpg 放进 raw/covers/ 即可，前端自动认（无需挂接命令）。
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


def _local_stems(covers_dir):
    return {p.stem for p in covers_dir.iterdir()
            if p.suffix.lower().lstrip(".") in EXTS} if covers_dir.is_dir() else set()


def fetch_cover_local(douban_id, isbn, covers_dir):
    """新书单本：拓 og:image 并下载落盘 covers_dir/<isbn>.<ext>。
    返回落盘 Path；占位图/无 isbn 返回 None（不存脏图）；网络/解析失败抛 RuntimeError。"""
    url = fetch_cover_url(douban_id)
    if not isbn or PLACEHOLDER in url:
        return None
    covers_dir.mkdir(parents=True, exist_ok=True)
    dest = _cover_path(covers_dir, isbn, url)
    if not dest.exists():
        try:
            dest.write_bytes(_download(url))
        except RuntimeError:
            dest.unlink(missing_ok=True)
            raise
    return dest


def localize_covers(conn, covers_dir, *, sleep_s=2.5, jitter=1.5, max_abort=6, limit=None):
    """以 douban_id 为源批量本地化：遍历有 douban_id+isbn、尚缺本地封面的书，
    逐本 og:image → 下载落盘 raw/covers/<isbn>.<ext>。不读不写 DB 列（douban_id 是可重推真源）。
    幂等：文件已存在直接跳过（续跑零成本）；同 isbn 多批次去重；占位图计入 skip；
    连续失败 max_abort 次刹车（防 ban）。"""
    covers_dir.mkdir(parents=True, exist_ok=True)
    have = _local_stems(covers_dir)
    rows = conn.execute(
        "SELECT DISTINCT isbn, douban_id FROM books "
        "WHERE douban_id IS NOT NULL AND douban_id != '' AND isbn IS NOT NULL AND isbn != '' "
        "ORDER BY isbn").fetchall()
    todo = [r for r in rows if r["isbn"] not in have]
    rep = {"downloaded": 0, "skipped": 0, "placeholder": 0, "fail": 0,
           "aborted": False, "already_have": len(rows) - len(todo), "todo": len(todo)}
    fail_run = 0
    for r in todo[:limit]:
        try:
            url = fetch_cover_url(r["douban_id"])
        except RuntimeError:
            rep["fail"] += 1; fail_run += 1
            if fail_run >= max_abort:
                rep["aborted"] = True
                break
            time.sleep(sleep_s + random.uniform(0, jitter))
            continue
        if PLACEHOLDER in url:
            rep["placeholder"] += 1
            time.sleep(sleep_s + random.uniform(0, jitter))
            continue
        dest = _cover_path(covers_dir, r["isbn"], url)
        try:
            dest.write_bytes(_download(url))
        except RuntimeError:
            dest.unlink(missing_ok=True)
            rep["fail"] += 1; fail_run += 1
            if fail_run >= max_abort:
                rep["aborted"] = True
                break
            time.sleep(sleep_s + random.uniform(0, jitter))
            continue
        rep["downloaded"] += 1
        fail_run = 0
        time.sleep(sleep_s + random.uniform(0, jitter))
    return rep


def main():
    ap = argparse.ArgumentParser(description="豆瓣封面本地化（以 douban_id 为源）")
    ap.add_argument("--test", help="只打印单个 douban_id 的 og:image URL")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--localize", action="store_true",
                    help="有 douban_id 尚无本地封面的书，逐本 og:image→下载 raw/covers/<isbn>（限速、可断点续跑）")
    ap.add_argument("--db", default=str(DB_PATH))
    args = ap.parse_args()
    if args.test:
        print(json.dumps({"cover_url": fetch_cover_url(args.test)}, ensure_ascii=False))
        return
    if not args.localize:
        ap.print_help()
        print("\n提示：补图用 --localize；手工图直接按 <isbn>.jpg 放进 raw/covers/ 即可。")
        return
    covers_dir = Path(args.db).resolve().parent / "raw" / "covers"
    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    try:
        rep = localize_covers(conn, covers_dir, limit=args.limit)
    finally:
        conn.close()
    print(json.dumps(rep, ensure_ascii=False))
    sys.exit(1 if rep["aborted"] else 0)


if __name__ == "__main__":
    main()
