from app.parsers import parse_book, parse_price, parse_sold_table, split_frontmatter, strip_wiki

FM = """---
title: "安娜·卡列尼娜"
author: "[[托尔斯泰]]"
category: "[[长篇|📙长篇]]"
isbn: "9787532132256"
price: "1.83"
platform: "[[京东]]"
publisher: ["[[上海文艺出版社]]", "[[凤凰壹力]]"]
importance: "1"
progress: "100"
rating: "10"
created: "April 27, 2024 11:32 AM"
last_modified: "July 8, 2025 2:18 PM"
tags: [长篇]
---

> **[📖 安娜·卡列尼娜](https://book.douban.com/subject/2253380/)**
> 正文内容
"""

def test_split_frontmatter():
    meta, body = split_frontmatter(FM)
    assert meta["title"] == "安娜·卡列尼娜"
    assert "正文内容" in body
    assert not body.startswith("---")

def test_split_frontmatter_absent():
    meta, body = split_frontmatter("纯正文，没有 frontmatter")
    assert meta is None
    assert body.startswith("纯正文")

def test_strip_wiki():
    assert strip_wiki("[[托尔斯泰]]") == "托尔斯泰"
    assert strip_wiki("[[长篇|📙长篇]]") == "长篇"
    assert strip_wiki(["[[A]]", "[[B|b]]"]) == ["A", "B"]
    assert strip_wiki(None) is None
    assert strip_wiki("无链接") == "无链接"
    assert strip_wiki("—") is None        # 占位符 → None，不是字符串 "—"
    assert strip_wiki("") is None

def test_parse_price():
    assert parse_price("1.83") == 1.83
    assert parse_price("-0.00") == 0.0
    assert parse_price("-5.63") == -5.63
    assert parse_price(None) is None      # 无价格 → None，不是 0
    assert parse_price("") is None
    assert parse_price("—") is None

def test_parse_book_full():
    b = parse_book(FM)
    assert b["title"] == "安娜·卡列尼娜"
    assert b["authors"] == ["托尔斯泰"]
    assert b["publishers"] == ["上海文艺出版社", "凤凰壹力"]
    assert b["categories"] == ["长篇"]
    assert b["platform"] == "京东"
    assert b["price"] == 1.83
    assert b["importance"] == 1.0
    assert b["progress"] == 100
    assert b["rating"] == 10
    assert b["status"] == "in_library"
    assert b["created"] == "April 27, 2024 11:32 AM"
    assert b["last_modified"] == "July 8, 2025 2:18 PM"

def test_parse_book_multi_category():
    """68 本书有多个分类（YAML 数组），全部保留。"""
    b = parse_book('---\ntitle: "红楼梦"\ncategory: ["[[长篇]]", "[[经典]]"]\n---\n正文\n')
    assert b["categories"] == ["长篇", "经典"]

def test_parse_book_missing_fields():
    b = parse_book('---\ntitle: "X"\n---\n正文\n')
    assert b["title"] == "X"
    assert b["price"] is None
    assert b["isbn"] is None
    assert b["authors"] == []
    assert b["categories"] == []
    assert b["created"] is None

SOLD = """| 书名            | 价格         | ISBN          | 平台      | 作者              | 出版社                   |
| ------------- | ---------- | ------------- | ------- | --------------- | --------------------- |
| 一个陌生女人的来信 | 1.36 | 9787538754872 | [[淘宝]] | [[茨威格]] | [[时代文艺出版社]] [[科文图书]] |
| 三国演义 | -0.00 | 9787532237354 | [[孔夫子]] | [[其它]] | — |
| **合计** | **350.62** |  |  |  |  |
"""

def test_parse_sold_table():
    rows = parse_sold_table(SOLD)
    assert len(rows) == 2                      # 表头/分隔/合计都不算
    r0, r1 = rows
    assert r0["title"] == "一个陌生女人的来信"
    assert r0["price"] == 1.36
    assert r0["isbn"] == "9787538754872"
    assert r0["status"] == "sold"
    assert r0["progress"] == -1
    assert r0["authors"] == ["茨威格"]
    assert r0["publishers"] == ["时代文艺出版社", "科文图书"]   # 一格两个 wikilink
    assert r0["platform"] == "淘宝"
    assert r0["created"] is None
    assert r1["price"] == 0.0                  # 显式 -0.00 = 真持平
    assert r1["publishers"] == []              # — 占位 → 空
