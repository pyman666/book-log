"""app.main 的隔离约定：import 它不许碰生产 books.db。

模块级 `app = create_app(DB_PATH, ROOT)` 时代，`from app.main import create_app`
（tests 里三处都这么写）会在 import 那一刻对仓库里的真库跑 init_db——
read_at 污染治理那次迁移实际就是被 pytest 顺手执行的。改成 build_app() 工厂后，
入口交给 `uvicorn app.main:build_app --factory`，import 变成纯读代码。
"""
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _run(code):
    return subprocess.run([sys.executable, "-c", code], cwd=ROOT,
                          capture_output=True, text=True, check=True).stdout.strip()


def test_importing_main_creates_no_app():
    assert _run("import app.main as m; "
                "print(hasattr(m, 'app'), callable(getattr(m, 'build_app', None)))") == "False True"


def test_importing_main_leaves_default_db_untouched():
    db = ROOT / "books.db"
    if not db.exists():
        pytest.skip("仓库里没有 books.db，无需隔离")
    before = (db.stat().st_mtime_ns, db.stat().st_size)
    _run("import app.main")                          # 子进程：绕开其它测试已完成的 import
    assert (db.stat().st_mtime_ns, db.stat().st_size) == before, \
        "import app.main 写了生产库——检查是不是又有模块级 create_app"
