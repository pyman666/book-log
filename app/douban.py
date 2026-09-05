"""豆瓣封面抓取：subject 页 og:image → books.cover_url。

- 单本：fetch_cover_url(douban_id)，前端"补封面"按钮/新书按需调用
- 批量：python -m app.douban   （限速+抖动，连续被ban即刹车退出，可反复重跑续传）
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
    """→ 小尺寸封面 URL；页面结构变化/被ban 时抛 RuntimeError。"""
    r = httpx.get(f"https://book.douban.com/subject/{douban_id}/",
                  headers=UA, timeout=timeout, follow_redirects=True)
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--test", help="只抓单个 douban_id 打印结果")
    ap.add_argument("--limit", type=int)
    args = ap.parse_args()
    if args.test:
        print(json.dumps({"cover_url": fetch_cover_url(args.test)}, ensure_ascii=False))
        return
    rep = backfill(limit=args.limit)
    print(json.dumps(rep, ensure_ascii=False))
    sys.exit(1 if rep["aborted"] else 0)


if __name__ == "__main__":
    main()
