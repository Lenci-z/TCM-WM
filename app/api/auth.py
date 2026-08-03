# -*- coding: utf-8 -*-
"""认证 API（B-T1）：登录换取 token / 当前用户。复用 P3 AuthManager。"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

router = APIRouter()


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    token: str
    username: str
    display_name: str
    role: str


@router.post("/login", response_model=LoginResponse)
def login(req: LoginRequest, request: Request):
    """登录：成功返回 token（P3 AuthManager，失败计数/锁定逻辑内置）。"""
    from api.main import get_auth
    auth = get_auth(request.app)
    token = auth.login(req.username, req.password)
    if not token:
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    user = auth.get_current_user(token)
    return LoginResponse(
        token=token,
        username=user["username"],
        display_name=user.get("display_name") or user["username"],
        role=user["role"],
    )


@router.get("/me")
def me(request: Request):
    """当前登录用户信息。"""
    from api.main import get_auth
    auth = get_auth(request.app)
    token = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
    user = auth.get_current_user(token) if token else None
    if not user:
        raise HTTPException(status_code=401, detail="未认证")
    return user
