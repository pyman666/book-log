# book-log —— 本地书库

元数据在 SQLite（`books.db`），读书内容在 Markdown（`raw/`），git 同步，网页查看与编辑。

## 启动

```bash
uv sync                                   # 首次（按 pyproject.toml 装依赖，uv.lock 保证各设备一致）
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000
```

浏览器打开 `http://127.0.0.1:8000`。手机：同 WiFi 访问 `http://<Mac的IP>:8000`。

## 日常

| 操作 | 位置 |
|------|------|
| 加书 / 改价格·评分·进度 / 标记售出 / 删除 | 网页 |
| 写读后感、摘抄 | Obsidian（vault 根 = 本仓库，内容放 `raw/`） |
| raw/ 与数据库对账 | 网页右上 **Sync** |
| 保存变更进 git | 网页右上 **Commit & Push**（或手动 `git add -A && git commit && git push`） |

## 约定

- **价格 = 花费 − 收入**：正数 = 净亏，负数 = 净赚；空 = 无价格（不参与统计）
- 进度：100=读完，0=未读，-1=售出；评分 1~10
- 同一本书多个批次（不同时间买/卖）= 多条记录，不要合并
- 分类/作者/出版社可多个（逗号分隔）；平台单值
- 新增 md 后点一次 Sync，数据库会自动建存根记录

## 同步与冲突

`books.db` 是二进制文件，直接提交 git。两台设备都改过再 pull 会冲突：
保留较新设备的那份（`git checkout --theirs books.db`），解决后提交。
万一数据损坏，`raw/` 的 md 仍在，可恢复 `Books/` 源文件后 `python -m app.migrate --force` 重建。

## 迁移（已执行过一次，留档）

```bash
uv run python -m app.migrate --dry-run   # 查看报告
```

校验基准：487 行（317 在库 + 170 售出），售出书价格合计 350.62。

## 测试

```bash
uv run pytest tests/ -v
```
