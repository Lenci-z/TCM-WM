# -*- coding: utf-8 -*-
"""患者 API（B-T1）：/api/patients CRUD，Bearer token 认证 + RBAC 权限。
数据经 Repository（AES 透明加密），引擎纯逻辑不在此层。
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

router = APIRouter()


def _token(request: Request) -> str:
    """从 Authorization: Bearer xxx 提取 token。"""
    token = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(status_code=401, detail="缺少认证 token")
    return token


def _require(request: Request, permission: str):
    """认证 + RBAC 权限检查（未认证 401，无权限 403）。"""
    from api.main import get_auth
    auth = get_auth(request.app)
    token = _token(request)
    user = auth.get_current_user(token)
    if not user:
        raise HTTPException(status_code=401, detail="未认证或 token 失效")
    if not auth.check_permission(token, permission):
        raise HTTPException(status_code=403, detail=f"无权限：{permission}")
    return user


class PatientCreate(BaseModel):
    name: str
    gender: str = None
    birth_date: str = None
    contact: str = None
    inpatient_no: str = None
    register_date: str = None
    physician: str = None
    status: str = "在组"
    disease_category: str = "CAD_PCI"


class PatientUpdate(BaseModel):
    name: str = None
    gender: str = None
    birth_date: str = None
    contact: str = None
    inpatient_no: str = None
    register_date: str = None
    physician: str = None
    status: str = None
    disease_category: str = None


@router.get("/patients")
def list_patients(request: Request):
    """患者列表（明文姓名/联系方式）。"""
    _require(request, "patient:view")
    from api.main import get_repo
    return get_repo(request.app).list_patients()


@router.post("/patients", status_code=201)
def create_patient(body: PatientCreate, request: Request):
    """建档（repo 自动 AES 加密）。"""
    _require(request, "patient:create")
    from api.main import get_repo
    from datetime import date
    data = body.model_dump()
    data["name"] = body.name  # 必填
    if not data.get("register_date"):
        data["register_date"] = date.today().isoformat()  # 匹配 GUI 默认
    pid = get_repo(request.app).insert_patient({k: v for k, v in data.items() if v is not None})
    return {"patient_id": pid, **data}


@router.get("/patients/{patient_id}")
def get_patient(patient_id: int, request: Request):
    _require(request, "patient:view")
    from api.main import get_repo
    p = get_repo(request.app).get_patient(patient_id)
    if not p:
        raise HTTPException(status_code=404, detail="患者不存在")
    return p


@router.put("/patients/{patient_id}")
def update_patient(patient_id: int, body: PatientUpdate, request: Request):
    _require(request, "patient:edit")
    from api.main import get_repo
    repo = get_repo(request.app)
    if not repo.get_patient(patient_id):
        raise HTTPException(status_code=404, detail="患者不存在")
    data = {k: v for k, v in body.model_dump().items() if v is not None}
    repo.update_patient(patient_id, data)
    return repo.get_patient(patient_id)


@router.delete("/patients/{patient_id}", status_code=204)
def delete_patient(patient_id: int, request: Request):
    """删除（保护性设计：有业务记录抛 ValueError → 409）。"""
    _require(request, "patient:delete")
    from api.main import get_repo
    try:
        get_repo(request.app).delete_patient(patient_id)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return None
