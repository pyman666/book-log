# book-log —— 本地书库

元数据在 SQLite（`books.db`），读书笔记在 Markdown（`raw/`），git 同步，网页查看与编辑。

## 启动

```bash
uv sync                                   # 首次（按 pyproject.toml 装依赖，uv.lock 保证各设备一致）
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
```

浏览器打开 `http://127.0.0.1:8000`。

## 日常

| 操作 | 位置 |
|------|------|
| 加书 / 改价格·评分·进度·豆瓣编号 / 标记售出 / 删除 | 网页 |
| 写读后感、摘抄 | Obsidian（vault 根 = 本仓库，内容放 `raw/`） |
| 跳豆瓣条目页 | 书单书名后的 🌐 / 详情页「🌐 豆瓣」（由 `douban_id` 拼 URL） |
| raw/ 与数据库对账 | 网页右上 **Sync** |
| 保存变更进 git | `git add -A && git commit`（push 手动执行） |

## 约定

- **价格 = 花费 − 收入**：正数 = 净亏，负数 = 净赚；空 = 无价格（不参与统计）
- 进度：100=读完，0=未读，-1=售出；评分 1~10
- 同一本书多个批次（不同时间买/卖）= 多条记录，不要合并
- **同名同作者 = 同一本书**：不同版本各一行元数据（ISBN、douban_id 各不同），
  共用一个 `raw/书名.md`；同名不同作者是两本书，各配各的 md，勿合并
- 售出书的笔记与在库版本放同一个 md（`raw/sold/` 已废弃并回 `raw/`）
- md 只放自己的笔记，**不写 frontmatter、不写豆瓣链接头**（subject 号存 db 的 `douban_id` 列）
- 没留过字的书 `raw/` 里没有文件（262 本空壳已清理），前端标"无正文"
- 分类/作者/出版社可多个（逗号分隔）；平台单值
- 新增 md 后点一次 Sync，数据库会自动建存根记录

## 仪表盘 & AI

后端三块，互不依赖，可单测（全部有测试覆盖）：

- **`app/analytics.py`** — 只读纯聚合：`daily_counts`（剁手日历）、`taste_spectrum`（口味光谱三轴）、`quadrant`（评分×重要度）、`cover_wall`（封面墙，`GET /api/stats/wall` 只出 5 字段）。路由零加工直出。
- **`app/douban.py`** — 豆瓣封面抓取（og:image → `books.cover_url`）。批量：`uv run python -m app.douban`（限速+抖动+连续 6 败刹车，可反复重跑续传）；单本按需：`POST /api/books/{id}/cover`。图片 CDN 校验 Referer，浏览器 <img> 直连没问题。
- **`app/ai/`** — DashScope Qwen（OpenAI 兼容 SDK）。`llm.py` 只管 chat()（key 读 bosch-ai-framework/.env 的 DASHSCOPE_API_KEY，不入库不入 git）；`gen.py` 管缓存（`ai_cache` 表：笔记按 file_path+mtime 失效，年度按 `yearly:<年>`）与提示词。
  - `GET /api/books/{id}/summary[?fresh=1]` 单本 AI 读后摘要
  - `GET /api/ai/yearly?year=N[&fresh=1|&pending=1]` 年度画像；pending=1 只查缓存不生成
  - 作者国籍判定 `ensure_author_flags`：显式触发——`POST /api/ai/author-flags` 或 `uv run python -m app.ai.gen --flags`（LLM 一把判定 → `authors.chinese`，幂等；失败不写库可重跑）。口味光谱纯读，未判定时语言轴按调用走启发式，前端给"判定"按钮

## 目录与存档

- `raw/*.md` —— 有笔记的书（93 个文件），Obsidian 直接编辑
- `raw/notion-export/` —— Notion 原始导出**只读存档**（图书页 495 + 作者/出版社等维度页），
  是部分售出书笔记的唯一副本，不要改动或删除
- `_trash/` —— 旧 Dataview 索引页归档

## 同步与冲突

`books.db` 是二进制文件，直接提交 git。两台设备都改过再 pull 会冲突：
保留较新设备的那份（`git checkout --theirs books.db`），解决后提交。
万一数据损坏，可从 `raw/` + `raw/notion-export/` 恢复源文件后
`python -m app.migrate --force` 重建。

## 常用命令

```bash
uv run python -m app.douban          # 补全缺失封面（幂等，可中断续跑）
uv run python -m app.ai.gen --flags  # 批量判定作者国籍（LLM，幂等；失败不写库可重跑）
uv run pytest -q                     # 47 测试，全离线（LLM/抓取均 monkeypatch）
```

## 一次性脚本（已执行，留档备查）

```bash
uv run python -m app.recover_notion   # 从 notion-export 找回流失笔记（追加/建 raw/sold）
uv run python -m app.douban_ids       # 提取豆瓣 subject 号进 douban_id 列 + 剥 md 豆瓣头
uv run python -m app.consolidate      # 同名同作者多 md 合并、记录归挂到规范文件
```

校验基准：487 行（317 在库 + 170 售出）；431 行有 douban_id（56 本无豆瓣条目/字帖）；
笔记文件 93 个；售出书价格合计 350.62。

## 测试

```bash
uv run pytest tests/ -v
```
