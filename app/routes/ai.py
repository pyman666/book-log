"""AI 摘要、年度画像与作者元数据路由。"""
from fastapi import APIRouter, HTTPException, Request

from .. import db as dbmod
from ..ai import gen
from ..dependencies import conn_of
from ..paths import normalize_file_path

router = APIRouter()


@router.get("/api/books/{bid}/summary")
def get_summary(request: Request, bid: int, fresh: int = 0):
    with conn_of(request) as conn:
        book = dbmod.get_book(conn, bid)
        if not book:
            raise HTTPException(404, "不存在")
        if fresh:
            conn.execute("DELETE FROM ai_cache WHERE key = ?",
                         (normalize_file_path(book["file_path"]),))
            conn.commit()
        try:
            return gen.summarize_book(conn, request.app.state.root, book)
        except ValueError as e:
            raise HTTPException(404, str(e))
        except Exception as e:
            raise HTTPException(502, f"模型调用失败: {type(e).__name__}: {e}")


@router.get("/api/ai/yearly")
def get_yearly(request: Request, year: int = 0, fresh: int = 0, pending: int = 0):
    with conn_of(request) as conn:
        years = [r[0] for r in conn.execute(
            f"SELECT DISTINCT year_of({dbmod.read_time()}) y FROM books "
            f"WHERE rating IS NOT NULL AND year_of({dbmod.read_time()}) IS NOT NULL "
            f"ORDER BY y DESC") if r[0]]
        if not year:
            return {"years": years}
        if pending:
            text = gen.cache_get(conn, f"yearly:{year}")
            return {"text": text, "cached": text is not None}
        if fresh:
            conn.execute("DELETE FROM ai_cache WHERE key = ?", (f"yearly:{year}",))
            conn.commit()
        try:
            return gen.yearly_portrait(conn, request.app.state.root, year)
        except ValueError as e:
            raise HTTPException(404, str(e))
        except Exception as e:
            raise HTTPException(502, f"模型调用失败: {type(e).__name__}: {e}")


@router.get("/api/ai/author-meta")
def author_meta_status(request: Request):
    with conn_of(request) as conn:
        return gen.flag_status(conn)


@router.post("/api/ai/author-meta")
def author_meta_run(request: Request):
    with conn_of(request) as conn:
        try:
            judged = gen.ensure_author_meta(conn)
        except Exception as e:
            raise HTTPException(502, f"模型调用失败: {type(e).__name__}: {e}")
        return {**gen.flag_status(conn), "judged": judged}

