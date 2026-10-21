"""导出：把活着的书目摊平 CSV / JSON。纯函数，不碰 IO（响应头由路由加）。

CSV 是给人看／丢进 Excel 的：列按「先认书、再认账」排，多值用「、」连，
带 BOM 以免 Excel 双击中文乱码。要完整字段（含笔记文件名）用 JSON。
"""
import csv
import io
import json
from datetime import datetime

_CSV_COLS = [
    ("title", "书名"), ("authors", "作者"), ("nationalities", "国籍"),
    ("categories", "分类"), ("tags", "标签"), ("publishers", "出版社"),
    ("platforms", "平台"), ("isbn", "ISBN"), ("douban_id", "豆瓣编号"),
    ("price", "价格"), ("progress", "进度"), ("rating", "评分"),
    ("importance", "重要度"), ("status", "状态"), ("created", "购买时间"),
    ("read_at", "阅读时间"), ("last_modified", "最后修改"), ("note_file", "笔记文件"),
]
_MULTI = {"authors", "nationalities", "categories", "tags", "publishers", "platforms"}
_STATUS = {"in_library": "在库", "sold": "已售"}


def _cell(book, key):
    v = book.get(key)
    if v is None:
        return ""
    if key in _MULTI:
        return "、".join(str(x) for x in v)
    if key == "status":
        return _STATUS.get(v, v)
    return v


def to_csv(books):
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow([label for _key, label in _CSV_COLS])
    for b in books:
        writer.writerow([_cell(b, key) for key, _label in _CSV_COLS])
    return "\ufeff" + buf.getvalue()


def to_json(books, exported_at=None):
    return json.dumps({
        "exported_at": exported_at or datetime.now().strftime("%Y-%m-%d %H:%M"),
        "count": len(books),
        "books": books,
    }, ensure_ascii=False, indent=1)
