"""首页路由。"""
import re

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

router = APIRouter()


@router.get("/", include_in_schema=False)
def index(request: Request):
    static_dir = request.app.state.static_dir
    html = (static_dir / "index.html").read_text(encoding="utf-8")

    def stamp(match):
        # 每个静态资源用自身 mtime 作缓存指纹：改了 app.js 下一次就换 URL，
        # 不再依赖 pyproject version（改代码时它不变 → 浏览器一直吃旧缓存）。
        url, quote = match.group(1), match.group(2)
        name = url.split("/static/", 1)[1].split("?", 1)[0]
        try:
            v = int((static_dir / name).stat().st_mtime)
        except OSError:
            v = request.app.state.version
        return f"{url}?v={v}{quote}"

    html = re.sub(r'(/static/[^"\'?]+)(")', stamp, html)
    return HTMLResponse(html, headers={"Cache-Control": "no-cache"})


