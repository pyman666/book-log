# book-log —— 本地书库

元数据在 SQLite（`books.db`），读书笔记在 Markdown（`raw/books/`），git 同步，网页查看与编辑。

## 启动

```bash
uv sync
uv run uvicorn app.main:build_app --factory --host 127.0.0.1 --port 8000
```

浏览器打开 `http://127.0.0.1:8000`。

## 日常

| 操作 | 位置 |
|------|------|
| 加书 / 改价格·评分·进度·豆瓣编号 / 标记售出 / 删除 | 网页 |
| 写读后感、摘抄 | Obsidian（vault 根 = 本仓库，笔记一律放 `raw/books/`） |
| 跳豆瓣条目页 | 书单书名后的 🌐 / 详情页「🌐 豆瓣」（由 `douban_id` 拼 URL） |
| 笔记文件与书名/作者对不上时查报告 | `uv run python -m app.notes`（只读体检，网页按钮已删） |
| 保存变更进 git | 终端 `git add -A && git commit && git push`（网页里的 Commit&Push 按钮已删：`add -A` 会无差别扫库、还一条 message 推全网） |

## 约定

- **价格 = 花费 − 收入**：正数 = 净亏，负数 = 净赚；空 = 无价格（不参与统计）
- 进度：100=读完，0=未读，-1=售出；评分 1~10
- `created` 是创建/购入时间，`read_at` 是阅读时间：**写入侧不设默认值**，`read_at` 只为「读过的书」存在（存量库已治理：打过分保留 `created`，其余清 NULL）
  - 年度口径统一走「有效阅读时间」（`read_at` 空则回落 `created`）：剁手日历例外，它本来就是“哪天买的”图，直属 `created`
- **schema 迁移走 `PRAGMA user_version`**：`db.init_db` 里每个迁移函数守卫 `if version < N … ; PRAGMA user_version = N`（当前 v2 = read_at 污染治理）。⚠ **不可静默回滚**：跨某个迁移退回旧代码再升回来，旧代码的回填会把污染复位而新治理不会重跑，得手动把 user_version 调回上一版再启动一次
- 同一本书多个批次（不同时间买/卖）= 多条记录，不要合并
- **笔记路径不入库**：`raw/books/书名.md` 属于哪本书，由 `app/notes.py` 按 (书名, 作者) 推导——
  新写/改名 md **立刻生效，没有 Sync 这一步**（库里 `books.file_path` 列已删，旧库启动自动弃列）。
  代价是命名必须合规则：写错的 md 只会让那本书显示「无正文」，孤儿文件要靠 `python -m app.notes` 体检才看得见（不会静默造存根）
- **同名同作者 = 同一本书**：不同版本/多批次各一行元数据（ISBN、douban_id 各不同），
  共用一个 `raw/books/书名.md`；**同名不同作者 = 两本书**，各配各的 md，勿合并
- 真撞名（如父与子·屠格涅夫 vs 父与子·卜劳恩）：裸 `书名.md` 只归**同名记录里 id 序最早的作者组合**，
  其他作者必须命名 **`书名（作者）.md`**（括号里的标签与作者名互相包含即命中），
  宁可判无正文也不会把屠格涅夫的笔记塞给卜劳恩；
  md 用**书名**命名不用 isbn：封面是版本级（一版一图，isbn 天然唯一），笔记是作品级（一本书 N 版本共用一篇）
- 书名尾巴带限定括号的（如 `围城（盗版）`）推导时会**剥掉再试一次**，与正版共用一篇笔记
- 售出书的笔记与在库版本放同一个 md（`raw/sold/` 已废弃并回 `raw/books/`）
- md 只放自己的笔记，**不写 frontmatter、不写豆瓣链接头**（subject 号存 db 的 `douban_id` 列）
- 没留过字的书 `raw/books/` 里没有文件（262 本空壳已清理），前端按推导结果标"无正文"
- 分类/作者/出版社可多个（逗号分隔）；平台单值

## 封面

- **`app/douban.py`** —— 豆瓣封面，**以 `douban_id` 为真源**（og:image → 下载 → `raw/covers/<isbn>.<ext>`）。
  封面真值 = **磁盘上是否存在 `<isbn>` 文件**，DB 不存 URL（豆瓣 CDN 2026-09 起校验 Referer，浏览器热链大面积 403，封面必须本地化）。三种用法：
  `--localize` 遍历有 douban_id+isbn、尚缺本地封面的书，逐本 og:image→下载落盘（同 isbn 多批次去重、占位图跳过）；
  手动补图按 `<isbn>.jpg` 扔进 `raw/covers/` 即自动被识别（**无需挂接命令**，存在即关联）；单本按需 `POST /api/books/{id}/cover`。
  共用纪律：2.5s+抖动限速、成功即落盘、Ctrl-C 安全、幂等续跑、连续 6 败刹车。前端经 `/cover/<isbn>`（忽略扩展名、无文件 404）取图，`/api/covers` 出本地清单。
- **视觉**：暖纸编辑排版（Anthropic 式米色纸底 + 朱砂印章 + 宋体展示字）；系统深浅色自动跟随。

> 仪表盘 / AI 摘要 / 年度画像 / 3D 书架已于 2026-07 整体下线——代码在 git 里（`git show 2bb38cc:app/ai` 等可整块捞回），等好 idea 再上。
> `authors.nationality/chinese` 两列**数据**保留（LLM 判过一次、重判费 token），判定代码已删；手工维护走 `PUT /api/authors/nationality`，书单页国籍筛选器继续可用。

## 目录与存档

- `raw/books/*.md` —— 有笔记的书（93 个文件，文件名 = 书名，撞名书加（作者）后缀），Obsidian 直接编辑
- `raw/covers/<isbn>.(jpg|png|webp|gif)` —— 本地封面库（文件名 = ISBN，豆瓣没有的手工补）
- `raw/notion/` —— Notion 原始导出**只读存档**（图书页 495 + 作者/出版社等维度页，图书页直接放在根目录），
  是部分售出书笔记的唯一副本，不要改动或删除
- `_trash/` —— 旧 Dataview 索引页归档

## 同步与冲突

`books.db` 是二进制文件，直接提交 git。两台设备都改过再 pull 会冲突：
保留较新设备的那份（`git checkout --theirs books.db`），解决后提交。
万一数据损坏，可从 `raw/books/` + `raw/notion/` 恢复源文件后
`python -m app.migrate --force` 重建。

## 常用命令

```bash
uv run python -m app.douban --localize  # 以 douban_id 为源，逐本 og:image→下载 raw/covers/<isbn>（限速，428本约35分钟，可断点续跑）
uv run python -m app.douban --test <id>  # 只打印某 douban_id 的 og:image URL（调试用）
# 手工补图：按 <isbn>.jpg 放进 raw/covers/ 即可，前端自动识别（无需命令）
uv run python -m app.notes           # 只读体检：磁盘 md 数、被认领的本数、没人认领的文件、无笔记的在库书
uv run pytest -q                     # 全离线（抓取均 monkeypatch）；import app.main 不碰生产 books.db
```

## 一次性脚本（已执行，留档备查；**不再可跑**）

这几个脚本直接读写已删除的 `books.file_path` 列，只作历史存档：

```bash
uv run python -m app.recover_notion   # 从 raw/notion 找回流失笔记（追加/建 raw/sold）
uv run python -m app.douban_ids       # 提取豆瓣 subject 号进 douban_id 列 + 剥 md 豆瓣头
uv run python -m app.consolidate      # 同名同作者多 md 合并、记录归挂到规范文件
```

校验基准：487 行（317 在库 + 170 售出）；431 行有 douban_id（56 本无豆瓣条目/字帖）；
笔记文件 93 个；售出书价格合计 350.62。

## 测试

```bash
uv run pytest tests/ -v
```
