# -*- coding: utf-8 -*-
"""处方 API（B-T4）：生成（自动模板+安全校验）/调整/签发/PDF/历史。
引擎纯函数调用（build_prescription/check_safety/apply_safety/matrix_code/export_rx_pdf），不碰 conn。
"""
import sys
import os
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel

from engine.prescription import build_prescription, matrix_code
from engine.safety import check_safety, apply_safety
from engine.pdf_export import export_rx_pdf

router = APIRouter()


class RxGenerate(BaseModel):
    patient_id: int
    pattern: str
    risk_level: str
    phase: str = "II"
    week_no: int = 1
    resting_hr: float = None
    max_hr: float = None
    age: int = None
    on_beta_blocker: bool = False


class RxUpdate(BaseModel):
    baduanjin_level: str = None
    aerobic_type: str = None
    aerobic_duration: int = None
    aerobic_freq: int = None
    rpe_min: int = None
    rpe_max: int = None
    hr_min: int = None
    hr_max: int = None
    resistance_json: str = None
    tcm_json: str = None
    diet_json: str = None
    monitor_json: str = None
    education_json: str = None


class RxSign(BaseModel):
    physician_sign: str


def _require(request: Request, permission: str):
    from api.patient import _require as _r
    return _r(request, permission)


@router.get("/prescriptions/{patient_id}")
def list_prescriptions(patient_id: int, request: Request):
    """处方历史。"""
    _require(request, "prescription:view")
    from api.main import get_repo
    return get_repo(request.app).list_prescriptions(patient_id)


@router.get("/patients/{patient_id}/latest-assessment")
def latest_assessment(patient_id: int, request: Request):
    """最新评估自动填充（证型/分层/PHQ9）。"""
    _require(request, "prescription:view")
    from api.main import get_repo
    repo = get_repo(request.app)
    return {
        "pattern": repo.get_latest_confirmed_pattern(patient_id),
        "risk_level": repo.get_latest_risk_level(patient_id),
        "phq9": repo.get_latest_phq9(patient_id),
    }


@router.post("/prescriptions/generate", status_code=201)
def generate_rx(body: RxGenerate, request: Request):
    """一键生成处方：模板调取 → 纯函数构建 → 安全校验 → 草稿入库。"""
    _require(request, "prescription:create")
    from api.main import get_repo
    repo = get_repo(request.app)

    patient = repo.get_patient(body.patient_id)
    if not patient:
        raise HTTPException(status_code=404, detail="患者不存在")
    dc = patient.get("disease_category") or "CAD_PCI"

    matrix = matrix_code(dc, body.pattern, body.risk_level)
    template = repo.get_rx_template(dc, matrix)
    if not template:
        raise HTTPException(status_code=422, detail=f"未找到处方模板：{matrix}（请检查证型/分层）")

    rx = build_prescription(
        template, repo.get_baduanjin_cfg(dc), dc, body.pattern, body.risk_level,
        phase=body.phase, week_no=body.week_no,
        resting_hr=body.resting_hr, max_hr=body.max_hr, age=body.age,
        on_beta_blocker=body.on_beta_blocker,
    )
    safety = check_safety(repo.get_safety_rules(),
                          repo.get_disease_contraindication(dc), dc,
                          body.pattern, body.risk_level)
    rx = apply_safety(rx, safety)
    rx.pop("safety", None)  # safety 仅返回前端展示，不落库（非表列）
    rx["patient_id"] = body.patient_id
    rx["status"] = "草稿"
    rx_id = repo.insert_prescription(rx)
    return {**rx, "rx_id": rx_id, "safety": safety}


@router.put("/prescriptions/{rx_id}")
def update_rx(rx_id: int, body: RxUpdate, request: Request):
    """医师调整保存（草稿/未签发可改）。"""
    _require(request, "prescription:edit")
    from api.main import get_repo
    repo = get_repo(request.app)
    rx = repo.get_prescription(rx_id)
    if not rx:
        raise HTTPException(status_code=404, detail="处方不存在")
    if rx["status"] == "已签发":
        raise HTTPException(status_code=409, detail="已签发处方不可修改")
    data = {k: v for k, v in body.model_dump().items() if v is not None}
    repo.update_prescription(rx_id, data)
    return repo.get_prescription(rx_id)


@router.post("/prescriptions/{rx_id}/sign")
def sign_rx(rx_id: int, body: RxSign, request: Request):
    """签发：签名必填，不可跳过。"""
    _require(request, "prescription:sign")
    from api.main import get_repo
    repo = get_repo(request.app)
    rx = repo.get_prescription(rx_id)
    if not rx:
        raise HTTPException(status_code=404, detail="处方不存在")
    if not body.physician_sign.strip():
        raise HTTPException(status_code=422, detail="医师签名不能为空（签发不可跳过）")
    repo.update_prescription(rx_id, {
        "status": "已签发", "physician_sign": body.physician_sign.strip()})
    return repo.get_prescription(rx_id)


@router.get("/prescriptions/{rx_id}/pdf")
def rx_pdf(rx_id: int, request: Request):
    """处方单 PDF 下载（仅已签发）。"""
    _require(request, "pdf:export")
    from api.main import get_repo
    repo = get_repo(request.app)
    rx = repo.get_prescription(rx_id)
    if not rx:
        raise HTTPException(status_code=404, detail="处方不存在")
    if rx["status"] != "已签发":
        raise HTTPException(status_code=409, detail="仅已签发处方可打印")
    patient = repo.get_patient_for_pdf(rx["patient_id"])
    fd, tmp = tempfile.mkstemp(suffix=".pdf")
    os.close(fd)
    export_rx_pdf(patient, rx, tmp)
    from starlette.background import BackgroundTask
    return FileResponse(tmp, filename=f"处方单_{rx_id}.pdf",
                        media_type="application/pdf",
                        background=BackgroundTask(os.unlink, tmp))
