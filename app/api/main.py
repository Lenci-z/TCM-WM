# -*- coding: utf-8 -*-
"""
FastAPI 应用工厂（B-T1）：接入现有 Repository（SQLite 先行）+ P3 AuthManager。
设计依据：docs/P4开发设计文档.md §3.1/§3.3（C/S 分层，引擎经 repo 调用不碰 conn）
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api import auth, patient

__all__ = ["create_app"]


def create_app(repo=None, auth_manager=None) -> FastAPI:
    """应用工厂：repo/auth_manager 可注入（测试/生产）。

    - repo：Repository 实例（默认懒加载自主库）
    - auth_manager：AuthManager 实例（默认懒加载）
    """
    app = FastAPI(title="中西医结合心血管康复系统 API", version="0.1.0")

    # 依赖注入（应用状态）
    app.state.repo = repo
    app.state.auth_manager = auth_manager

    # CORS（开发阶段允许本地前端；生产由 Nginx 同源代理，见 B-T9）
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 路由
    app.include_router(auth.router, prefix="/api/auth", tags=["认证"])
    app.include_router(patient.router, prefix="/api", tags=["患者"])

    @app.get("/api/health", tags=["系统"])
    def health():
        return {"status": "ok", "service": "rehab-api"}

    return app


def get_repo(app: FastAPI):
    """从应用状态取 Repository（懒加载主库连接）。"""
    if app.state.repo is None:
        from db import get_conn
        from repo import Repository
        app.state.repo = Repository(get_conn())
    return app.state.repo


def get_auth(app: FastAPI):
    """从应用状态取 AuthManager（懒加载）。"""
    if app.state.auth_manager is None:
        from auth import AuthManager
        from security import get_security
        app.state.auth_manager = AuthManager(get_repo(app), get_security())
    return app.state.auth_manager
