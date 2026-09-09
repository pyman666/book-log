"""前端契约：表单输入框 ↔ 提交 payload ↔ 后端模型，三处不能漏。

起因：`douban_id` 在 BOOK_FIELDS 里有输入框、详情页也回填了值，但 `formPayload()`
没带这个键——PUT 走 `exclude_unset=True`，于是"填了不保存"且毫无报错。这类 bug 静态
比对一次就能钉死，不必跑浏览器。
"""
import re
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
