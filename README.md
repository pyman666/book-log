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
| `raw/books/` 与数据库对账 | 网页右上 **Sync** |
| 保存变更进 git | `git add -A && git commit`（push 手动执行） |

## 约定

- **价格 = 花费 − 收入**：正数 = 净亏，负数 = 净赚；空 = 无价格（不参与统计）
- 进度：100=读完，0=未读，-1=售出；评分 1~10
- `created` 是创建/购入时间，`read_at` 是阅读时间：**写入侧不设默认值**，`read_at` 只为「读过的书」存在（存量库已治理：打过分保留 `created`，其余清 NULL）
  - 年度口径统一走「有效阅读时间」（`read_at` 空则回落 `created`）：剁手日历例外，它本来就是“哪天买的”图，直属 `created`
- **schema 迁移走 `PRAGMA user_version`**：`db.init_db` 里每个迁移函数守卫 `if version < N … ; PRAGMA user_version = N`（当前 v2 = read_at 污染治理）。⚠ **不可静默回滚**：跨某个迁移退回旧代码再升回来，旧代码的回填会把污染复位而新治理不会重跑，得手动把 user_version 调回上一版再启动一次
- 同一本书多个批次（不同时间买/卖）= 多条记录，不要合并
- **同名同作者 = 同一本书**：不同版本各一行元数据（ISBN、douban_id 各不同），
  共用一个 `raw/books/书名.md`；**同名不同作者 = 两本书**，各配各的 md，勿合并
- 真撞名（如父与子·屠格涅夫 vs 父与子·卜劳恩）：裸 `书名.md` 归 id 序第一条同名记录，
  另一本命名 **`书名（作者）.md`**，Sync 会剥尾括号按「书名+作者」二轮精确挂接（不会造污染存根）；
  md 用**书名**命名不用 isbn：封面是版本级（一版一图，isbn 天然唯一），笔记是作品级（一本书 N 版本共用一篇）
- 售出书的笔记与在库版本放同一个 md（`raw/sold/` 已废弃并回 `raw/books/`）
- md 只放自己的笔记，**不写 frontmatter、不写豆瓣链接头**（subject 号存 db 的 `douban_id` 列）
- 没留过字的书 `raw/books/` 里没有文件（262 本空壳已清理），前端标"无正文"
- 分类/作者/出版社可多个（逗号分隔）；平台单值
- 新增 md 后点一次 Sync，数据库会自动建存根记录

## 仪表盘 & AI

后端三块，互不依赖，可单测（全部有测试覆盖）：

- **`app/analytics.py`** — 只读纯聚合：`daily_counts`（剁手日历，按 `created`）、`reading_curve`（节奏曲线，只数有评分的书）、`taste_spectrum`（口味光谱三轴，语言轴用 `authors.chinese`；占位作者「其它/无」不参与）、`quadrant`（评分×重要度）、`cover_wall`（书架数据，`GET /api/stats/wall` 只出 5 字段）；国籍分布走 `stats_group?by=nationality`。路由零加工直出。
- **视觉**：暖纸编辑排版（Anthropic 式米色纸底 + 朱砂印章 + 宋体展示字 + 章节号）；封面是 iPod Cover Flow 式 3D 书架（随机开场、左右留隐藏封面，点封面进详情，← → 翻书）；全部图表色走 `style.css` token（8-slot 分类色过 validate_palette.js 双模式）；系统切深浅色时页面自动重渲染。
- **`app/douban.py`** — 豆瓣封面，**以 `douban_id` 为真源**（og:image → 下载 → `raw/covers/<isbn>.<ext>`）。
  封面真值 = **磁盘上是否存在 `<isbn>` 文件**，DB 不再存 URL（豆瓣 CDN 2026-09 起校验 Referer，浏览器热链大面积 403，封面必须本地化）。三种用法：
  `--localize` 遍历有 douban_id+isbn、尚缺本地封面的书，逐本 og:image→下载落盘（同 isbn 多批次去重、占位图跳过）；
  手动补图按 `<isbn>.jpg` 扔进 `raw/covers/` 即自动被识别（**无需挂接命令**，存在即关联）；单本按需 `POST /api/books/{id}/cover`。
  共用纪律：2.5s+抖动限速、成功即落盘、Ctrl-C 安全、幂等续跑、连续 6 败刹车。前端经 `/cover/<isbn>`（忽略扩展名、无文件 404）取图，`/api/covers` 出本地清单，书架只显示已落封面的书。
- **`app/ai/`** — DashScope Qwen（OpenAI 兼容 SDK）。`llm.py` 只管 chat()（key 读 bosch-ai-framework/.env 的 DASHSCOPE_API_KEY，不入库不入 git）；`gen.py` 管缓存（`ai_cache` 表：笔记按 file_path+mtime 失效，年度按 `yearly:<年>`）与提示词。
  - `GET /api/books/{id}/summary[?fresh=1]` 单本 AI 读后摘要
  - `GET /api/ai/yearly?year=N[&fresh=1|&pending=1]` 年度画像（只取打过分的书，与节奏曲线同口径）；pending=1 只查缓存不生成
  - 作者国籍判定 `ensure_author_meta`：显式触发——`POST /api/ai/author-meta` 或 `uv run python -m app.ai.gen --meta`（LLM 一把判定 → `authors.nationality`（中文国名）+ `authors.chinese`（0/1），幂等；失败不写库可重跑，LLM 漏判的个别名字走启发式兜底）。口味光谱纯读，未判定时语言轴按启发式临时算，前端给"判定"按钮
- **分布面板**（伍）：单图动态切换 维度（国籍/作者/出版社/类别/平台/年度）× 指标（本数/净花费），点柱条跳书单页并自动带对应筛选（如 nationality=法国）；`GET /api/books` 新增 `nationality`/`year` 参数，书单页有国籍列与国籍/年份筛选器

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
uv run python -m app.ai.gen --meta   # 批量判定作者国籍/华人标志（LLM，幂等；失败不写库可重跑）
uv run pytest -q                     # 68 测试，全离线（LLM/抓取均 monkeypatch）；import app.main 不碰生产 books.db
```

## 一次性脚本（已执行，留档备查）

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
