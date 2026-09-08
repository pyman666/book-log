"""筛选维度与仪表盘统计路由。"""
from fastapi import APIRouter, HTTPException, Request

from .. import analytics
from .. import db as dbmod
from ..dependencies import conn_of, covers_dir, local_cover_stems

router = APIRouter()


@router.get("/api/facets")
def facets(request: Request):
    with conn_of(request) as conn:
        return dbmod.facets(conn)


@router.get("/api/stats/summary")
def stats_summary(request: Request):
    with conn_of(request) as conn:
        return dbmod.stats_summary(conn)


@router.get("/api/stats/group")
def stats_group(request: Request, by: str, agg: str = "count"):
    with conn_of(request) as conn:
        try:
            return dbmod.stats_group(conn, by, agg)
        except (KeyError, ValueError):
            raise HTTPException(400, "by/agg 参数无效")


@router.get("/api/stats/daily")
def stats_daily(request: Request):
    with conn_of(request) as conn:
        return analytics.daily_counts(conn)


@router.get("/api/stats/curve")
def stats_curve(request: Request, gran: str = "month"):
    with conn_of(request) as conn:
        try:
            return analytics.reading_curve(conn, gran)
        except ValueError:
            raise HTTPException(400, "gran 参数须为 week/month/year")


@router.get("/api/stats/spectrum")
def stats_spectrum(request: Request):
    with conn_of(request) as conn:
        return analytics.taste_spectrum(conn)


@router.get("/api/stats/quadrant")
def stats_quadrant(request: Request):
    with conn_of(request) as conn:
        return analytics.quadrant(conn)


@router.get("/api/stats/wall")
def stats_wall(request: Request):
    stems = local_cover_stems(covers_dir(request))
    with conn_of(request) as conn:
        data = analytics.cover_wall(conn)
    data["items"] = [item for item in data["items"] if item["isbn"] in stems]
    return data

