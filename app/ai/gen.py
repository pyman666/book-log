"""AI 生成 + ai_cache 表读写。缓存键带源文件 mtime，笔记一改缓存自动失效。"""
import json
import re
import time
from pathlib import Path

from . import llm

DB_PATH = Path(__file__).resolve().parent.parent.parent / "books.db"

SYSTEM = ("你是个人读书笔记库的助手。只依据用户提供的笔记内容作答，不编造笔记里没有的信息；"
          "语言简洁，用中文。只输出 markdown 纯文本（可用标题、列表），不要输出 HTML 标签。")


def _now():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def cache_get(conn, key, mtime=None):
    row = conn.execute("SELECT mtime, text FROM ai_cache WHERE key = ?", (key,)).fetchone()
    if not row:
        return None
    if mtime is not None and row["mtime"] != mtime:
        return None
    return row["text"]


def cache_put(conn, key, mtime, text, model=None):
    conn.execute(
        """INSERT INTO ai_cache (key, mtime, model, text, updated) VALUES (?,?,?,?,?)
           ON CONFLICT(key) DO UPDATE SET mtime=?, model=?, text=?, updated=?""",
        (key, mtime, model or llm.DEFAULT_MODEL, text, _now(),
         mtime, model or llm.DEFAULT_MODEL, text, _now()))
    conn.commit()


def summarize_book(conn, root, book):
    """返回 {summary, cached}。book 需含 title/file_path；无笔记文件时抛 ValueError。"""
    fp = book.get("file_path")
    if not fp:
        raise ValueError("无正文文件")
    p = Path(root) / fp
    if not p.is_file():
        raise ValueError("正文文件不存在")
    mtime = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(p.stat().st_mtime))
    hit = cache_get(conn, fp, mtime)
    if hit:
        return {"summary": hit, "cached": True}
    notes = p.read_text(encoding="utf-8")[:12000]
    meta = f"《{book['title']}》 作者: {'、'.join(book.get('authors') or [])}"
    text = llm.chat([
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content":
            f"{meta}\n\n以下是我的读书笔记原文：\n\n{notes}\n\n"
            "请输出：第一行一句≤30字的导读（概括这本书在我笔记里聚焦什么）；"
            "空一行后写80~150字的摘要，站在我自己的笔记视角，不要营销腔。只要这两段，不要标题。"},
    ])
    cache_put(conn, fp, mtime, text)
    return {"summary": text, "cached": False}


def yearly_portrait(conn, root, year):
    """年度读书画像。数据多、生成慢，前端按钮触发。root = vault 根（路由注入，勿硬编码）。"""
    key = f"yearly:{year}"
    hit = cache_get(conn, key)
    if hit:
        return {"text": hit, "cached": True}
    rows = conn.execute(
        """SELECT b.title, b.file_path, b.rating, b.price, group_concat(a.name,'、') AS authors
           FROM books b LEFT JOIN book_authors ba ON ba.book_id=b.id
           LEFT JOIN authors a ON a.id=ba.author_id
           WHERE b.created LIKE ? GROUP BY b.id""", (f"% {year}%",)).fetchall()
    if not rows:
        raise ValueError(f"{year} 年没有书记录")
    parts, budget = [], 24000
    for r in rows:
        frag = f"《{r['title']}》{('/' + r['authors']) if r['authors'] else ''} 评分:{r['rating'] or '-'}"
        if r["file_path"] and budget > 0:
            p = Path(r["file_path"])
            if not p.is_absolute():
                p = Path(root) / p
            if p.is_file():
                excerpt = p.read_text(encoding="utf-8")[:min(500, budget)]
                frag += f"\n笔记摘录: {excerpt}"
                budget -= len(excerpt)   # 按实际拼入长度扣，budget 耗尽后剩余书才停止带摘录
        parts.append(frag)
    prompt = (f"这是我 {year} 年购入/登记的 {len(rows)} 本书及其部分笔记摘录：\n\n"
              + "\n\n".join(parts)[:24000] +
              "\n\n请给我这个年度的读书画像：3~5句总评（兴趣脉络、读得杂还是专、花钱与评分的反差等），"
              "再列3条要点。直接输出内容，不要客套。")
    text = llm.chat([{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}])
    cache_put(conn, key, None, text)
    return {"text": text, "cached": False}


def flag_status(conn):
    """→ {"total": 作者数, "pending": 国籍未判定数}。"""
    row = conn.execute("SELECT COUNT(*) AS total, "
                       "SUM(nationality IS NULL OR chinese IS NULL) AS pending "
                       "FROM authors").fetchone()
    return {"total": row["total"], "pending": row["pending"] or 0}


def ensure_author_meta(conn):
    """LLM 一次性批量判定作者国籍+华人标志（nationality/chinese），返回本次判定条数。
    - 无 pending → 0（幂等，不调模型）；
    - LLM 调用/解析失败 → 抛错且不写库，重新触发即重试；
    - LLM 响应漏掉个别名字：该名字按启发式补（含连续拉丁字母或· → 外籍、国籍"未知"）。
    显式触发：POST /api/ai/author-meta 或 python -m app.ai.gen --meta。
    口味光谱是纯读：语言轴只消费 chinese 列，不触发判定。"""
    pending = conn.execute(
        "SELECT id, name FROM authors WHERE nationality IS NULL OR chinese IS NULL").fetchall()
    if not pending:
        return 0
    def guess(n):  # 启发式兜底 → (country, cn)
        return ("未知", 0) if re.search(r"[A-Za-z]{2}", n) or "·" in n else ("中国", 1)
    by = {r["name"]: guess(r["name"]) for r in pending}
    text = llm.chat([
        {"role": "system", "content": "你是文学翻译，只输出 JSON。"},
        {"role": "user", "content": "判断下列作家的国籍（中文国名，古人按其文明，如\"中国\"、\"古希腊\"）"
            "以及是否为中国作者（含港澳台，用中文名写作也算）。只输出 JSON 数组："
            '[{"name":"余华","country":"中国","cn":1},{"name":"加缪","country":"法国","cn":0}]，'
            "顺序与输入一致。\n\n" + "、".join(by)}])
    m = re.search(r"\[.*\]", text, re.S)
    if not m:
        raise ValueError("LLM 响应里没有 JSON 数组")
    for d in json.loads(m.group(0)):
        if d.get("name") in by:
            by[d["name"]] = ((d.get("country") or "未知").strip(), 1 if d.get("cn") else 0)
    for r in pending:
        country, cn = by[r["name"]]
        conn.execute("UPDATE authors SET nationality=?, chinese=? WHERE id=?",
                     (country, cn, r["id"]))
    conn.commit()
    return len(pending)


def main():
    """CLI：python -m app.ai.gen --meta [--db 路径]（与 app/douban.py 同款一次性脚本模式）"""
    import argparse, sys
    from .. import db as dbmod
    ap = argparse.ArgumentParser(description="AI 一次性数据脚本")
    ap.add_argument("--meta", action="store_true",
                    help="批量判定作者国籍/华人标志（LLM）；失败不写库，可重跑")
    ap.add_argument("--db", default=str(DB_PATH))
    args = ap.parse_args()
    if not args.meta:
        ap.print_help()
        sys.exit(1)
    with dbmod.db_conn(Path(args.db)) as conn:
        try:
            judged = ensure_author_meta(conn)
            st = flag_status(conn)
        except Exception as e:
            print(json.dumps({"ok": False, "error": f"{type(e).__name__}: {e}"},
                             ensure_ascii=False))
            sys.exit(1)
    print(json.dumps({"ok": True, "judged": judged, **st}, ensure_ascii=False))


if __name__ == "__main__":
    main()
