# -*- coding: utf-8 -*-
"""
认证与权限（P3-T2）：登录认证 + RBAC 权限控制 + 审计留痕。
设计来源：docs/分阶段开发设计与任务列表.md §4.3.4 / §4.3.5 / §4.5

权限矩阵（设计文档 4.3.5）：管理员 * 全权限；医师/治疗师/护士按表。
登录流程：失败计数 → 5 次锁定 15 分钟 → 成功生成内存 token（关闭即失效）。
关键操作（登录/登出）自动写 audit_log。
"""
from datetime import datetime, timedelta

_MAX_FAIL = 5
_LOCK_MINUTES = 15


class AuthManager:
    """登录认证 + RBAC 权限控制。依赖 Repository（数据）与 SecurityManager（哈希/token）。"""

    PERMISSION_MATRIX = {
        "医师": [
            "patient:view", "patient:create", "patient:edit", "patient:delete",
            "assessment:view", "assessment:create", "assessment:edit",
            "prescription:view", "prescription:create", "prescription:sign",
            "followup:view", "followup:complete",
            "alert:view", "alert:handle",
            "pdf:export",
        ],
        "治疗师": [
            "patient:view", "patient:create", "patient:edit",
            "assessment:view", "assessment:create", "assessment:edit",
            "prescription:view",
            "followup:view", "followup:complete",
            "alert:view",
        ],
        "护士": [
            "patient:view", "patient:create",
            "assessment:view", "assessment:create",
            "followup:view", "followup:complete",
            "alert:view",
        ],
        "管理员": ["*", "rules:edit", "user:manage", "audit:view"],
    }

    def __init__(self, repo, security=None):
        self.repo = repo
        if security is None:
            from security import get_security
            security = get_security()
        self.sec = security

    # ---------- 登录 / 登出 ----------

    def login(self, username: str, password: str) -> str | None:
        """登录验证：成功返回 token，失败返回 None（审计失败原因）。"""
        user = self.repo.get_user_by_username(username)
        if not user:
            self.repo.record_audit(None, "LOGIN", "user", None, None, None,
                                   f"登录失败：用户名不存在 {username}")
            return None
        if not user.get("enabled", 1):
            self.repo.record_audit(user["user_id"], "LOGIN", "user", user["user_id"],
                                   None, None, "登录失败：账号已禁用")
            return None
        locked = user.get("locked_until")
        if locked and locked > datetime.now().strftime("%Y-%m-%d %H:%M:%S"):
            self.repo.record_audit(user["user_id"], "LOGIN", "user", user["user_id"],
                                   None, None, f"登录失败：账号锁定至 {locked}")
            return None
        if not self.sec.verify_password(password, user["password_hash"]):
            n = self.repo.update_login_fail(user["user_id"])
            self.repo.record_audit(user["user_id"], "LOGIN", "user", user["user_id"],
                                   None, None, f"登录失败：密码错误（第 {n} 次）")
            return None
        # 成功
        self.repo.update_login_success(user["user_id"])
        token = self.sec.generate_token(user["user_id"])
        self.repo.record_audit(user["user_id"], "LOGIN", "user", user["user_id"],
                               None, None, f"登录成功：{username}（{user.get('role')}）")
        return token

    def logout(self, token: str) -> None:
        """登出：清除会话 + 审计。"""
        uid = self.sec.verify_token(token)
        self.sec.revoke_token(token)
        if uid:
            self.repo.record_audit(uid, "LOGOUT", "user", uid, None, None, "登出")

    # ---------- RBAC ----------

    def _role_permissions(self, role: str) -> list:
        return self.PERMISSION_MATRIX.get(role, [])

    def check_permission(self, token: str, permission: str) -> bool:
        """检查当前用户是否有指定权限（管理员 * 全通）。"""
        role = self.get_role(token)
        if not role:
            return False
        perms = self._role_permissions(role)
        return "*" in perms or permission in perms

    def get_current_user(self, token: str) -> dict | None:
        """获取当前登录用户信息（不含密码哈希）。"""
        uid = self.sec.verify_token(token)
        if uid is None:
            return None
        rows = self.repo.query_one("SELECT * FROM user WHERE user_id=?", (uid,))
        if not rows:
            return None
        return {k: v for k, v in rows.items() if k != "password_hash"}

    def get_role(self, token: str) -> str | None:
        """获取当前用户角色。"""
        user = self.get_current_user(token)
        return user["role"] if user else None
