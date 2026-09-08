"""仪表盘聚合查询（只读，纯函数：conn → 可 JSON 序列化结构）。

三块看板数据的单一出处，路由层不做任何加工：
- daily_counts(conn)    登记日历（GitHub 热力图，按 created）
- reading_curve(conn)   读书节奏曲线（按有效阅读时间分桶，只数读过的书 = 有评分）
- taste_spectrum(conn)  口味光谱（StoryGraph 式三条堆叠 bar）
- quadrant(conn)        评分 × 重要度象限（气泡=盈亏）
- cover_wall(conn)      封面墙（只出 id/title/read_at/rating/isbn 五字段，按 isbn 关联本地封面）
"""
import re
from collections import defaultdict
from datetime import datetime, timedelta

from .db import read_time

_MONTHS = {m: i for i, m in enumerate(
    "January February March April May June July August September October November December".split(), 1)}

# 口味光谱·书目轴：多分类各占 1/n 权重
FICTION = {"长篇", "短篇", "戏剧", "漫画", "流行", "经典", "外文", "小品"}
VERSE = {"诗歌", "散文", "书信"}
# 其余分类（历史/社科/传记/科普/艺术/摄影/技能/辞书/书帖/国学/诸子）→ 思想与实用

LATIN = re.compile(r"[A-Za-z]{2,}")  # 作者名含连续拉丁字母 → 翻译


def _read_date(s):
    """'April 27, 2024 11:32 AM' → date | None（宽容解析，失败即 None）"""
    if not s:
        return None
    m = re.match(r"([A-Za-z]+) (\d{1,2}), (\d{4})", s)
    if not m or m.group(1) not in _MONTHS:
        return None
    try:
        return datetime(int(m.group(3)), _MONTHS[m.group(1)], int(m.group(2))).date()
    except ValueError:
        return None


def daily_counts(conn):
    """按登记日（created）聚合：{"2024-04-27": {"n": 2, "titles": [...]}}。
    不用 read_at：那种「某一天读过」的精度库里根本没有（见 db._migrate_read_at），
    读过的书也只有一个 Notion 建条目日期，热力图讲的老是「哪天在记账」。"""
    out = defaultdict(lambda: {"n": 0, "titles": []})
    for d, title in conn.execute("SELECT created, title FROM books WHERE created IS NOT NULL"):
        day = _read_date(d)
        if day:
            e = out[day.isoformat()]
            e["n"] += 1
            e["titles"].append(title)
    return dict(out)


_GRAN = ("week", "month", "year")


def _period_start(day, gran):
    """date → 该周期起点 date（week=周一，month=1 号，year=1 月 1 日）。"""
    if gran == "week":
        return day - timedelta(days=day.weekday())
    if gran == "month":
        return day.replace(day=1)
    return day.replace(month=1, day=1)


def reading_curve(conn, gran="month"):
    """读书节奏曲线：按有效阅读时间（read_at，空则回落 created）分桶。gran ∈ week/month/year。
    「读过一本」= 有评分：进过数据库的书 487 本，真读完的远少于这个数，
    不加这道筛就是购书曲线。没评分但确实读完的，补个评分就会回到曲线里。
    返回按时间正序的 [{period, n, titles}]，period 是该周期起始日的 ISO 日期
    （week → 周一，month → 1 号，year → 1 月 1 日）。
    空周期（该周/月/年没读书）跳过，不做补零——曲线只连有读过的点。"""
    if gran not in _GRAN:
        raise ValueError(f"gran 须为 {_GRAN} 之一")
    buckets = defaultdict(lambda: {"n": 0, "titles": []})
    for d, title in conn.execute(
            f"SELECT {read_time('b')} AS rt, title FROM books b WHERE b.rating IS NOT NULL"):
        day = _read_date(d)
        if not day:
            continue
        e = buckets[_period_start(day, gran)]
        e["n"] += 1
        e["titles"].append(title)
    return [{"period": s.isoformat(), "n": buckets[s]["n"], "titles": buckets[s]["titles"]}
            for s in sorted(buckets)]


def _book_axes(conn):
    """逐书取 (分类集合, 作者[(名,国籍)], status, progress)，多对多在此收敛。
    「其它/其他/无」是导入遗留的占位作者（54 本垃圾桶，nationality=未知），
    从作者维度剔除——否则 chinese=0 会把它们全算成"翻译"。"""
    PLACEHOLDER = ("其它", "其他", "无")
    cats, authors = defaultdict(list), defaultdict(list)
    for bid, c in conn.execute("SELECT bc.book_id, c.name FROM book_categories bc "
                               "JOIN categories c ON c.id=bc.category_id"):
        cats[bid].append(c)
    for bid, n, cn in conn.execute("SELECT ba.book_id, au.name, au.chinese FROM book_authors ba "
                                   "JOIN authors au ON au.id=ba.author_id"):
        if n not in PLACEHOLDER:
            authors[bid].append((n, cn))
    rows = conn.execute("SELECT id, status, progress FROM books").fetchall()
    return [(r["id"], set(cats[r["id"]]), authors[r["id"]], r["status"], r["progress"]) for r in rows]


def taste_spectrum(conn):
    """三条轴，每条 = [{key, value}]（value 为按本数加权，多分类均摊）。"""
    form = {"小说·戏剧": 0.0, "诗歌·散文": 0.0, "思想·人文·实用": 0.0}
    lang = {"原创": 0.0, "翻译": 0.0}
    state = {"读完": 0.0, "未读": 0.0, "售出": 0.0}
    for _bid, cs, aus, status, progress in _book_axes(conn):
        form["小说·戏剧" if cs & FICTION else "诗歌·散文" if cs & VERSE else "思想·人文·实用"] += 1
        if aus:  # 语言轴：任一外国作者即翻译；无作者不计入
            if "外文" in cs or any(c == 0 for _, c in aus):
                lang["翻译"] += 1
            elif all(c == 1 for _, c in aus):
                lang["原创"] += 1
            elif any(LATIN.search(n) or "·" in n for n, _ in aus):
                lang["翻译"] += 1
            else:
                lang["原创"] += 1
        state["售出" if status == "sold" else "读完" if progress == 100 else "未读"] += 1
    bar = lambda d: [{"key": k, "value": round(v, 1)} for k, v in d.items() if v]
    return [
        {"axis": "读什么", "segments": bar(form)},
        {"axis": "语言", "segments": bar(lang)},
        {"axis": "读完没", "segments": bar(state)},
    ]


def quadrant(conn):
    """有评分且有重要度的书：气泡 x=评分 y=重要度 size=|price| color=主分类。"""
    out = []
    for r in conn.execute(
            """SELECT b.id, b.title, b.rating, b.importance, b.price, b.douban_id,
                      (SELECT c.name FROM book_categories bc JOIN categories c ON c.id=bc.category_id
                        WHERE bc.book_id=b.id LIMIT 1) AS cat
               FROM books b WHERE b.rating IS NOT NULL AND b.importance IS NOT NULL"""):
        out.append({"id": r["id"], "title": r["title"], "rating": r["rating"],
                    "importance": r["importance"], "price": r["price"],
                    "cat": r["cat"] or "—", "douban_id": r["douban_id"]})
    return out


def cover_wall(conn):
    """封面墙：只返回前端需要的 5 字段（/api/books 全量 payload 对纯展示太肥）。
    以 isbn 为经键（封面 = 本地 raw/covers/<isbn>.* 文件）；是否“有封面”由路由层
    按磁盘实际文件过滤（analytics 不碰文件系统，保持纯函数）。total = 全库本数。
    输出的 read_at 是有效阅读时间（read_at 空则用 created）——纯展示字段，
    编辑表单读的是 /api/books/{id} 的原值，不会被回写污染。"""
    total = conn.execute("SELECT COUNT(*) FROM books").fetchone()[0]
    rows = conn.execute(
        f"SELECT id, title, {read_time()} AS read_at, rating, isbn FROM books "
        "WHERE isbn IS NOT NULL AND isbn != '' ORDER BY id").fetchall()
    return {"total": total, "items": [dict(r) for r in rows]}
