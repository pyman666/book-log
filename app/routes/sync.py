"""Markdown 书库同步路由。"""
from fastapi import APIRouter, Request

from ..dependencies import conn_of
from ..sync import sync_vault

router = APIRouter()


@router.post("/api/sync")
def sync(request: Request):
    with conn_of(request) as conn:
        return sync_vault(conn, request.app.state.root)

