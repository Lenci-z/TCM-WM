# -*- coding: utf-8 -*-
"""随访 API（B-T5）：计划生成（模板节点+Day0）/历史/完成登记。"""
import sys
import os
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

router = APIRouter()


class FuGenerate(BaseModel):
    patient_id: int


class FuComplete(BaseModel):
    actual_date: str = None
    handler: str = None
    note: str = None


def _require(request: Request, permission: str):
    from api.patient import _require as _r
    return _r(request, permission)


def _day0(repo, pid: int) -> date:
    """Day 0：手术日期优先，其次建档日期，最后今天。"""
    day0_str = repo.get_day0(pid)
    if day0_str:
        try:
            return date.fromisoformat(day0_str[:10])
        except ValueError:
            pass
    return date.today()


@router.post("/followups/generate", status_code=201)
def generate_plan(body: FuGenerate, request: Request):
    """按模板生成随访计划（已存在同类型不重复）。"""
    _require(request, "followup:create")
    from api.main import get_repo
    repo = get_repo(request.app)

    patient = repo.get_patient(body.patient_id)
    if not patient:
        raise HTTPException(status_code=404, detail="患者不存在")
    dc = patient.get("disease_category") or "CAD_PCI"
    nodes = repo.get_followup_template(dc)
    if isinstance(nodes, dict):
        nodes = nodes.get("nodes", [])
    if not nodes:
        raise HTTPException(status_code=422, detail="病种未配置随访模板")

    day0 = _day0(repo, body.patient_id)
    existing = set(repo.list_existing_fu_types(body.patient_id))
    created = []
    for node in nodes:
        code = node.get("code") or node.get("fu_type")
        if code in existing:
            continue
        fu_id = repo.insert_followup({
            "patient_id": body.patient_id,
            "plan_date": (day0 + timedelta(days=node.get("offset_days", 0))).isoformat(),
            "fu_type": code,
            "status": "待随访",
        })
        created.append({"fu_id": fu_id, "fu_type": code})
    return {"created": len(created), "day0": day0.isoformat(), "items": created}


@router.get("/followups/{patient_id}")
def list_followups(patient_id: int, request: Request):
    """随访计划/历史（前端标注逾期）。"""
    _require(request, "followup:view")
    from api.main import get_repo
    repo = get_repo(request.app)
    if not repo.get_patient(patient_id):
        raise HTTPException(status_code=404, detail="患者不存在")
    rows = repo.list_followups(patient_id)
    today = date.today().isoformat()
    out = []
    for r in rows:
        d = dict(r)
        d["overdue"] = bool(r["status"] == "待随访" and r["plan_date"] and r["plan_date"] < today)
        out.append(d)
    return out


@router.post("/followups/{fu_id}/complete")
def complete_followup(fu_id: int, body: FuComplete, request: Request):
    """复评完成登记。"""
    _require(request, "followup:complete")
    from api.main import get_repo
    repo = get_repo(request.app)
    row = repo.query_one("SELECT * FROM follow_up WHERE fu_id=?", (fu_id,))
    if not row:
        raise HTTPException(status_code=404, detail="随访记录不存在")
    data = {"status": "已完成", "actual_date": body.actual_date or date.today().isoformat()}
    if body.handler:
        data["handler"] = body.handler
    if body.note:
        data["record_json"] = body.note
    repo.update_row("follow_up", data, "fu_id=?", (fu_id,))
    return repo.query_one("SELECT * FROM follow_up WHERE fu_id=?", (fu_id,))
