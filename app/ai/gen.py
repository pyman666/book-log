"""AI 生成 + ai_cache 表读写。缓存键带源文件 mtime，笔记一改缓存自动失效。"""
import time
from pathlib import Path

from . import llm

ROOT = Path(__file__).resolve().parent.parent.parent  # book-log 仓库根

SYSTEM = "你是个人读书笔记库的助手。只依据用户提供的笔记内容作答，不编造笔记里没有的信息；语言简洁，用中文。"


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


def yearly_portrait(conn, year):
    """年度读书画像。数据多、生成慢，前端按钮触发。"""
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
        if r["file_path"]:
            p = Path(str(r["file_path"]))
            if not p.is_absolute():
                p = ROOT / p
            if p.is_file():
                excerpt = p.read_text(encoding="utf-8")[:500]
                frag += f"\n笔记摘录: {excerpt[:max(0, budget)]}"
                budget -= len(excerpt)
        parts.append(frag)
    prompt = (f"这是我 {year} 年购入/登记的 {len(rows)} 本书及其部分笔记摘录：\n\n"
              + "\n\n".join(parts)[:24000] +
              "\n\n请给我这个年度的读书画像：3~5句总评（兴趣脉络、读得杂还是专、花钱与评分的反差等），"
              "再列3条要点。直接输出内容，不要客套。")
    text = llm.chat([{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}])
    cache_put(conn, key, None, text)
    return {"text": text, "cached": False}


def ensure_author_flags(conn):
    """authors.chinese 为空时一次性让 LLM 批量判定国籍（232 个名字一把过）。
    失败退回启发式：含拉丁字母或·的外文译名 → 非华人。"""
    import json, re
    pending = conn.execute("SELECT id, name FROM authors WHERE chinese IS NULL").fetchall()
    if not pending:
        return
    def guess(n):
        return 1 if not (re.search(r"[A-Za-z]{2}", n) or "·" in n) else 0
    by = {r["name"]: guess(r["name"]) for r in pending}
    try:
        text = llm.chat([
            {"role": "system", "content": "你是文学翻译，只输出 JSON。"},
            {"role": "user", "content": "判断下列作家是否为中国作者（含港澳台，用中文名写作也算）。"
                '只输出 JSON 数组：[{"name":"余华","cn":1},{"name":"加缪","cn":0}]，顺序与输入一致。\n\n'
                + "、".join(by)}])
        for d in json.loads(re.search(r"\[.*\]", text, re.S).group(0)):
            if d.get("name") in by:
                by[d["name"]] = 1 if d.get("cn") else 0
    except Exception:
        pass  # 断网/额度问题不致命，启发式兜底
    for r in pending:
        conn.execute("UPDATE authors SET chinese=? WHERE id=?", (by[r["name"]], r["id"]))
    conn.commit()
