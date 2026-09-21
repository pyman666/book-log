"""前端契约：表单输入框 ↔ 提交 payload ↔ 后端模型，三处不能漏。

起因：`douban_id` 在 BOOK_FIELDS 里有输入框、详情页也回填了值，但 `formPayload()`
没带这个键——PUT 走 `exclude_unset=True`，于是"填了不保存"且毫无报错。这类 bug 静态
比对一次就能钉死，不必跑浏览器。
"""
import json
import re
import shutil
import subprocess
from pathlib import Path

from app.models import BookIn

JS = Path(__file__).resolve().parent.parent / "app" / "static" / "app.js"


def _js():
    return JS.read_text(encoding="utf-8")


def _form_fields(js):
    block = re.search(r"const BOOK_FIELDS = `(.*?)`;", js, re.S).group(1)
    return {m for m in re.findall(r'<(?:input|select)[^>]*name="(\w+)"', block)}


def _payload_keys(js):
    body = re.search(r"function formPayload\(form\) \{.*?\n}", js, re.S).group(0)
    body = body.split("return {", 1)[1]
    return {m for m in re.findall(r"(\w+)\s*:", body) if m not in {"form"}}


def test_every_form_field_is_submitted():
    js = _js()
    missing = _form_fields(js) - _payload_keys(js)
    assert not missing, f"表单里有输入框、提交时却被丢掉：{sorted(missing)}"


def test_every_form_field_is_accepted_by_api():
    """表单字段必须是 BookIn 的字段，否则 pydantic 静默吞掉，网页看起来"存不上"。"""
    unknown = _form_fields(_js()) - set(BookIn.model_fields)
    assert not unknown, f"前端有输入框但后端模型不认：{sorted(unknown)}"


def test_inline_editable_fields_exist_in_model():
    js = _js()
    inline = set(re.findall(r'data-field="(\w+)"', js))
    assert inline, "书单页行内编辑控件没找到，是改版了还是选择器失效？"
    assert not inline - set(BookIn.model_fields) - {"nationalities"}


def test_new_book_row_reuses_table_controls():
    """登记新书 = 插到现有书最上面一行，控件复用列表行（维度弹层/行内输入）；
    不许再往页面底部沉一个独立表单面板。"""
    js = _js()
    assert "book-form" not in js, "底部表单面板又回来了？新书行应该插在表格第一行"
    block = re.search(r"function newBookRow\(\) \{.*?\n\}", js, re.S).group(0)
    # 作者/分类/出版社/平台走跟列表行同一个 dimBtn 弹层（均为多选），国籍按钮同 markup
    dims = set(re.findall(r'dimBtn\(d,\s*"(\w+)"', block))
    assert dims == {"authors", "categories", "publishers", "platforms"}
    assert 'data-dim="nationality"' in block
    # 列表列没有的四个字段不能丢
    for name in ("isbn", "douban_id", "rating", "importance"):
        assert f'name="{name}"' in block, f"新书行漏了字段 {name}"
    # 保存走 POST /api/books，取消/保存都有着落
    assert 'api("/api/books", { method: "POST"' in js


def test_sort_three_state_cycle():
    """点列名三态：第一次按该列排（默认方向），第二次翻转，第三次取消（回最新在前）。"""
    js = _js()
    m = re.search(r"function nextSortState\([^)]*\)\s*\{.*?\n\}", js, re.S)
    assert m, "nextSortState 没了（排序三态逻辑改了？）"
    pre = re.search(r"const SORT_DESC_FIRST = new Set\(\[.*?\]\);\nconst DEFAULT_SORT = \{[^}]*\};", js, re.S).group(0)
    driver = m.group(0) + """
const t = (sort, desc, col) => nextSortState(sort, desc, col);
console.log(JSON.stringify([
  t("created", "true", "title"),
  t("title", "false", "title"),
  t("title", "true", "title"),
  t("created", "true", "price"),
  t("price", "true", "price"),
  t("price", "false", "price"),
]));
"""
    node = shutil.which("node")
    if not node:
        import pytest
        pytest.skip("node 不可用")
    out = subprocess.run([node, "-e", pre + driver], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    a, b, c, d, e, f = json.loads(out.stdout)
    # 文字列：升序 → 降序 → 取消
    assert (a, b, c) == ({"sort": "title", "desc": "false"},
                         {"sort": "title", "desc": "true"},
                         {"sort": "created", "desc": "true"})
    # 数字列：降序 → 升序 → 取消
    assert (d, e, f) == ({"sort": "price", "desc": "true"},
                         {"sort": "price", "desc": "false"},
                         {"sort": "created", "desc": "true"})
