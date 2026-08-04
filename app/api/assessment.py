# -*- coding: utf-8 -*-
"""评估 API（B-T3）：创建评估（自动证型判定 + 自动分层）+ 历史列表。
引擎纯逻辑经 repo 数据调用（judge_pattern/stratify），不碰 conn。
"""
import sys
import os
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from engine.pattern import judge_pattern
from engine.stratification import stratify

router = APIRouter()

# 数值范围校验（与 GUI assessment_view._validate_inputs 一致，P3-T3）
_RANGES = [
    ("LVEF", 0, 100), ("six_mwd", 0, 1000), ("NT_proBNP", 0, 100000),
    ("LDL_C", 0.1, 20), ("HbA1c", 3, 20), ("PHQ9", 0, 27),
    ("GAD7", 0, 21), ("BMI", 10, 60), ("BP_sys", 60, 260), ("BP_dia", 30, 150),
]

_CLINICAL_KEYS = ["LVEF", "NT_proBNP", "LDL_C", "HbA1c", "UACR", "BMI",
                  "six_mwd", "grip", "PHQ9", "GAD7", "BP_sys", "BP_dia"]


class AssessmentCreate(BaseModel):
    patient_id: int
    assessment_type: str = "基线"
    assess_date: str = None
    LVEF: float = None
    NT_proBNP: float = None
    LDL_C: float = None
    HbA1c: float = None
    UACR: float = None
    BMI: float = None
    six_mwd: float = None
    grip: float = None
    PHQ9: float = None
    GAD7: float = None
    BP_sys: float = None
    BP_dia: float = None
    pattern_items: list = []  # 四诊问卷勾选条目


def _require(request: Request, permission: str):
    from api.patient import _require as _r
    return _r(request, permission)


def _validate(body: AssessmentCreate) -> str | None:
    """数值范围校验，越界返回错误信息。"""
    for key, lo, hi in _RANGES:
        v = getattr(body, key)
        if v is None:
            continue
        if not (lo <= v <= hi):
            return f"{key} 超出合理范围（{lo}-{hi}）"
    return None


@router.get("/meta/pattern-keywords")
def pattern_keywords(request: Request):
    """四诊问卷条目（规则外置：来自规则库证型 keywords）。"""
    from api.patient import _require
    _require(request, "assessment:view")
    from api.main import get_repo
    return {"items": get_repo(request.app).get_pattern_keywords()}


@router.get("/assessments/{patient_id}")
def list_assessments(patient_id: int, request: Request):
    """评估历史。"""
    from api.patient import _require
    _require(request, "assessment:view")
    from api.main import get_repo
    return get_repo(request.app).list_assessments(patient_id)


@router.post("/assessments", status_code=201)
def create_assessment(body: AssessmentCreate, request: Request):
    """创建评估：保存 → 自动证型判定 → 自动分层 → 返回判定结果。"""
    from api.patient import _require
    _require(request, "assessment:create")
    from api.main import get_repo
    repo = get_repo(request.app)

    if not repo.get_patient(body.patient_id):
        raise HTTPException(status_code=404, detail="患者不存在")
    err = _validate(body)
    if err:
        raise HTTPException(status_code=422, detail=err)

    patient = repo.get_patient(body.patient_id)
    dc = patient.get("disease_category") or "CAD_PCI"
    assess_date = body.assess_date or date.today().isoformat()

    # 1. 保存评估
    data = {"patient_id": body.patient_id, "disease_category": dc,
            "assessment_type": body.assessment_type, "assess_date": assess_date}
    for k in _CLINICAL_KEYS:
        v = getattr(body, k)
        if v is not None:
            data[k] = v
    aid = repo.insert_assessment(data)

    # 2. 自动证型判定（引擎纯函数）
    main_pattern, secondary_pattern = None, None
    if body.pattern_items:
        main_pattern, secondary_pattern, _ = judge_pattern(
            repo.get_patterns(), body.pattern_items)
    if main_pattern:
        repo.insert_tcm_pattern({
            "patient_id": body.patient_id, "assess_date": assess_date,
            "main_pattern": main_pattern,
            "secondary_pattern": secondary_pattern, "physician_confirm": 1,
        })

    # 3. 自动分层（引擎纯函数；数据不足保守判高危）
    clinical = {k: getattr(body, k) for k in _CLINICAL_KEYS if getattr(body, k) is not None}
    risk_level, triggered = stratify(repo.get_strat_config(dc), clinical)
    repo.insert_risk_stratification({
        "patient_id": body.patient_id, "disease_category": dc,
        "assess_date": assess_date, "risk_level": risk_level, "physician_confirm": 1,
    })

    # 4. 自动预警评估（B-T6：评估后联动触发，insert_alert 持久化）
    from engine.alerts import evaluate_alerts
    alert_ctx = dict(clinical)
    alert_ctx["pattern"] = main_pattern or ""
    alert_ctx["risk_level"] = risk_level
    # 规则条件键别名映射（评估字段 → 预警规则 metric）
    if alert_ctx.get("BP_sys") is not None:
        alert_ctx["SBP"] = alert_ctx["BP_sys"]
    if alert_ctx.get("BP_dia") is not None:
        alert_ctx["DBP"] = alert_ctx["BP_dia"]
    phq9 = alert_ctx.get("PHQ9") or 0
    gad7 = alert_ctx.get("GAD7") or 0
    if phq9 or gad7:
        alert_ctx["phq9_or_gad7"] = max(phq9, gad7)
    alert_trig = evaluate_alerts(repo.get_alert_rules(), dc,
                                 main_pattern or "", risk_level, alert_ctx)
    alert_ids = []
    for item in alert_trig:
        alert_ids.append(repo.insert_alert(body.patient_id, item))

    return {
        "assessment_id": aid,
        "patient_id": body.patient_id,
        "assess_date": assess_date,
        "main_pattern": main_pattern,
        "secondary_pattern": secondary_pattern,
        "risk_level": risk_level,
        "risk_triggered": triggered,
        "alerts": alert_ids,
    }
