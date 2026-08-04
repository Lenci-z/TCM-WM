# -*- coding: utf-8 -*-
"""预警 API（B-T6）：预警列表（待处置/全部）+ 处置登记。"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

router = APIRouter()


class AlertHandle(BaseModel):
    content: str


def _require(request: Request, permission: str):
    from api.patient import _require as _r
    return _r(request, permission)


@router.get("/alerts")
def list_alerts(request: Request, status: str = "open", limit: int = 200):
    """预警列表：status=open（待处置，默认）/ all（含已关闭历史）。"""
    _require(request, "alert:view")
    from api.main import get_repo
    repo = get_repo(request.app)
    if status == "all":
        return repo.list_alerts(limit=limit)
    return repo.list_open_alerts(limit=limit)


@router.post("/alerts/{alert_id}/handle")
def handle_alert(alert_id: int, body: AlertHandle, request: Request):
    """处置预警：待处置 → 已关闭（处置人=当前用户，内容必填）。"""
    from api.patient import _require as _r
    user = _r(request, "alert:handle")
    from api.main import get_repo
    repo = get_repo(request.app)
    row = repo.query_one("SELECT * FROM alert WHERE alert_id=?", (alert_id,))
    if not row:
        raise HTTPException(status_code=404, detail="预警不存在")
    if row["status"] != "待处置":
        raise HTTPException(status_code=409, detail="该预警已处置")
    if not body.content.strip():
        raise HTTPException(status_code=422, detail="处置内容不能为空")
    handler = user.get("display_name") or user.get("username") or "系统"
    repo.handle_alert(alert_id, handler, body.content.strip())
    return repo.query_one("SELECT * FROM alert WHERE alert_id=?", (alert_id,))
