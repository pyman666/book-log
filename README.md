# book-log —— 本地书库 

元数据在 SQLite（`books.db`），读书笔记在 Markdown（`raw/books/`），git 同步，网页查看与编辑。 

## 启动 

```bash 
uv sync 
uv run uvicorn app.main:build_app --factory --host 127.0.0.1 --port 8000
uv run python -m app.douban --localize  # 从豆瓣下载封面，限速，可断点续跑
uv run python -m app.note  # 只读体检：磁盘 md 数、被认领的本数、没人认领的文件、无笔记的在库书
```

浏览器打开 `http://127.0.0.1:8000`。

## 日常

| 操作 | 位置 |
|------|------|
| 加书 / 改价格·评分·进度·豆瓣编号 / 标记售出 / 删除 | 网页 |
| 写读后感、摘抄 | Obsidian（vault 根 = 本仓库，笔记一律放 `raw/books/`） |
| 跳豆瓣条目页 | 书单书名后的 🌐 / 详情页「🌐 豆瓣」（由 `douban_id` 拼 URL） |
| 笔记文件与书名/作者对不上时查报告 | `uv run python -m app.notes` |
| 保存变更进 git | 终端 `git add -A && git commit && git push` |

## 约定

- **价格 = 花费 − 收入**：正数 = 支出，负数 = 收入；空 = 无价格（不参与统计）
- 进度：100=读完，0=未读，-1=售出；评分 1~10
- 同一本书多个批次（不同时间买/卖）= 多条记录，不要合并
- **笔记路径不入库**：`raw/books/书名（作者）.md` 属于哪本书，由 `app/notes.py` 按 (书名, 作者) 推导
    - md 用**书名**命名不用 isbn：封面是版本级（一版一图，isbn 天然唯一），笔记是作品级（一本书 N 版本共用一篇）
    - 书名尾巴带限定括号的（如 `围城（盗版）`）推导时会**剥掉再试一次**，与正版共用一篇笔记

## 仪表盘

六块面板，全部纯 SQL 只读聚合（`app/analytics.py` + `app/routes/stats.py`，无 LLM）：

- **壹·书影长廊**：iPod Cover Flow 式 3D 书架（随机开场，点封面进详情，← → 翻书）；只显本地已有封面的书
- **贰·剁手日历**：年度热力格（按 `created`）——一天买几本
- **叁·口味光谱**：体裁/语言/完成度三轴堆叠条（语言轴读 `authors.chinese` 现值）
- **肆·评价点阵**：散点象限，气泡=盈亏，红亏绿赚
- **伍·读书节奏**：月度/季度曲线，只数打过分的书
- **陆·钱去哪了**：维度（国籍/作者/出版社/类别/平台/年度）× 指标（本数/金额）单图切换，点柱条跳书单页带筛选

## 目录与存档

- `raw/books/*.md` —— 有笔记的书（93 个文件，文件名 = 书名，撞名书加（作者）后缀），Obsidian 直接编辑
- `raw/covers/<isbn>.(jpg|png|webp|gif)` —— 本地封面库（文件名 = ISBN，豆瓣没有的手工补）
- `raw/notion/` —— Notion 原始导出**只读存档**， 是部分售出书笔记的唯一副本，不要改动或删除

## 同步与冲突

`books.db` 是二进制文件，直接提交 git。两台设备都改过再 pull 会冲突：
保留较新设备的那份（`git checkout --theirs books.db`），解决后提交。
万一数据损坏，可从 `raw/books/` + `raw/notion/` 恢复源文件后
`python -m app.migrate --force` 重建。

## 常用命令

```bash

```
