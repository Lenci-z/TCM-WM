# -*- coding: utf-8 -*-
"""
主窗口（3.1）：五区导航 + 状态栏
中西医结合心血管康复全程管理系统 V0.1（MVP）
"""
import sys
import os
import traceback
import tkinter as tk
from tkinter import ttk, messagebox

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db import DB_PATH, get_conn, init_db, import_seed, SEED_DIR
from log import setup_logging, get_logger
from repo import Repository
from auth import AuthManager
from security import get_security

_logger = get_logger("main")


def _install_excepthook():
    """全局未处理异常兜底：写崩溃日志 + 提示用户（步骤 1.3）。"""
    def hook(etype, value, tb):
        _logger.critical("未处理异常: %s: %s\n%s", etype.__name__, value,
                         "".join(traceback.format_exception(etype, value, tb)))
        try:
            messagebox.showerror("程序错误",
                                 f"发生未处理错误：{etype.__name__}: {value}\n"
                                 f"详细信息已写入日志 data/logs/rehab.log")
        except Exception:
            pass
    sys.excepthook = hook


class MainApp(tk.Tk):
    """主窗口：Notebook 五 Tab（患者管理/评估录入/处方管理/随访管理/规则库维护）。"""

    def __init__(self, auth=None, token=None, require_login=False):
        super().__init__()
        setup_logging()
        _install_excepthook()
        _logger.info("系统启动")
        self.title("中西医结合心血管康复全程管理系统 V0.1（MVP）")
        self.geometry("1280x800")
        self.minsize(1100, 700)

        # 数据库初始化（首次启动建库 + 导入种子；后续直接打开）
        self._init_database()

        # 认证（P3-T2）：auth 可注入（测试）；token 可预置（开发/测试跳过登录）
        self.auth = auth if auth is not None else AuthManager(self.repo, get_security())
        self.current_token = token
        self._require_login = require_login

        # 顶部标题栏
        header = tk.Frame(self, bg="#8B2F2F", height=56)
        header.pack(fill="x")
        header.pack_propagate(False)
        tk.Label(header, text="中西医结合心血管康复全程管理系统",
                 bg="#8B2F2F", fg="white", font=("微软雅黑", 18, "bold")).pack(side="left", padx=16)
        self.user_var = tk.StringVar(value="")
        tk.Label(header, textvariable=self.user_var,
                 bg="#8B2F2F", fg="#F5E6C8", font=("微软雅黑", 10)).pack(side="right", padx=16)
        # 并行第一批线③：手动备份按钮（仅管理员可见，_apply_permissions 控制）
        self.btn_backup = tk.Button(header, text="备份数据", command=self._backup_now,
                                    bg="#A0522D", fg="white", relief="flat",
                                    font=("微软雅黑", 10))
        self.btn_backup.pack(side="right", padx=4)

        # 主体：Notebook 五区导航
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True, padx=8, pady=8)

        # 延迟导入各视图，避免循环依赖
        from ui.patient_view import PatientView
        from ui.assessment_view import AssessmentView
        from ui.prescription_view import PrescriptionView
        from ui.followup_view import FollowupView
        from ui.rules_view import RulesView
        from ui.adherence_view import AdherenceView
        from ui.dashboard_view import DashboardView

        self.tab_patient = PatientView(self.notebook, self)
        self.tab_assess = AssessmentView(self.notebook, self)
        self.tab_rx = PrescriptionView(self.notebook, self)
        self.tab_followup = FollowupView(self.notebook, self)
        self.tab_dashboard = DashboardView(self.notebook, self)
        self.tab_adherence = AdherenceView(self.notebook, self)
        self.tab_rules = RulesView(self.notebook, self)

        self.notebook.add(self.tab_patient, text="  患者管理  ")
        self.notebook.add(self.tab_assess, text="  评估录入  ")
        self.notebook.add(self.tab_rx, text="  处方管理  ")
        self.notebook.add(self.tab_followup, text="  随访管理  ")
        self.notebook.add(self.tab_dashboard, text="  数据看板  ")
        self.notebook.add(self.tab_adherence, text="  依从性打卡  ")
        self.notebook.add(self.tab_rules, text="  规则库维护  ")

        self.notebook.bind("<<NotebookTabChanged>>", self._on_tab_change)

        # 状态栏
        self.status_var = tk.StringVar(value="就绪")
        status = tk.Label(self, textvariable=self.status_var, anchor="w",
                          relief="sunken", bg="#F0F0F0", font=("微软雅黑", 9))
        status.pack(fill="x", side="bottom")

        # 登录流（P3-T2）：require_login 时弹登录/初始化管理员窗口
        if self._require_login:
            self._start_login()
        else:
            self._refresh_user_bar()
        self._apply_permissions()

    # ---------- 认证（P3-T2） ----------
    def _start_login(self):
        """启动登录流程：无用户 → 初始化管理员；有用户 → 登录。"""
        from ui.login_view import LoginView
        if not self.repo.list_users():
            LoginView(self, self.auth, mode="init", on_success=self._on_login_success)
        else:
            LoginView(self, self.auth, mode="login", on_success=self._on_login_success)

    def _on_login_success(self, token: str) -> None:
        """登录成功回调：保存 token + 刷新用户栏 + 按角色应用权限。"""
        self.current_token = token
        self._refresh_user_bar()
        self._apply_permissions()
        user = self.auth.get_current_user(token)
        if user:
            self.status_var.set(f"已登录：{user.get('display_name') or user.get('username')}（{user.get('role')}）")

    def _apply_permissions(self):
        """RBAC 界面显隐（P3-T3）：按钮 state + 规则库 Tab 隐藏（仅管理员）。"""
        for view in (self.tab_patient, self.tab_assess, self.tab_rx,
                     self.tab_followup, self.tab_dashboard, self.tab_adherence,
                     self.tab_rules):
            fn = getattr(view, "_apply_permissions", None)
            if callable(fn):
                fn()
        # 规则库 Tab：仅管理员可见（rules:edit）
        can_edit_rules = self.check_perm("rules:edit")
        self.notebook.tab(self.tab_rules, state="normal" if can_edit_rules else "hidden")
        # 并行第一批线③：备份按钮仅管理员可见（管理员权限矩阵含 * 全通）
        self.btn_backup.pack_forget()
        if self.check_perm("data:backup"):
            self.btn_backup.pack(side="right", padx=4)

    def _refresh_user_bar(self):
        """标题栏右侧显示当前用户（未登录则提示）。"""
        if self.current_token:
            user = self.auth.get_current_user(self.current_token)
            if user:
                self.user_var.set(f"{user.get('display_name') or user.get('username')} ｜ {user.get('role')}")
                return
        self.user_var.set("未登录")

    def check_perm(self, permission: str) -> bool:
        """RBAC 权限检查（P3-T3）：未登录一律拒绝。"""
        if not self.current_token:
            return False
        return self.auth.check_permission(self.current_token, permission)

    # ---------- 数据库 ----------
    def _init_database(self):
        # 并行第一批线②（PRD P2 功能 6）：启动健康检查，损坏时提示而非崩溃
        from db import check_db_health
        ok, msg = check_db_health()
        if not ok:
            # 文件不存在 = 首次启动，init_db 将建库，属正常路径，不打扰
            if os.path.exists(DB_PATH):
                proceed = messagebox.askyesno(
                    "数据库异常",
                    f"数据库健康检查未通过：\n{msg}\n\n是否仍尝试启动？（建议先备份数据）")
                if not proceed:
                    sys.exit(1)
        init_db()
        conn = get_conn()
        try:
            has_rules = conn.execute("SELECT COUNT(*) FROM rule_alert").fetchone()[0]
        except Exception:
            has_rules = 0
        conn.close()
        if not has_rules:
            import_seed()
        self.conn = get_conn()
        self.repo = Repository(self.conn)

    # ---------- 事件 ----------
    def _on_tab_change(self, event):
        """切换 Tab 时刷新对应视图。"""
        try:
            idx = self.notebook.index(self.notebook.select())
            name = self.notebook.tab(idx, "text").strip()
            self.status_var.set(f"当前模块：{name}")
            refresh = {
                "患者管理": lambda: getattr(self.tab_patient, "refresh", lambda: None)(),
                "评估录入": lambda: getattr(self.tab_assess, "refresh", lambda: None)(),
                "处方管理": lambda: getattr(self.tab_rx, "refresh", lambda: None)(),
                "随访管理": lambda: getattr(self.tab_followup, "refresh", lambda: None)(),
                "规则库维护": lambda: getattr(self.tab_rules, "refresh", lambda: None)(),
            }
            refresh.get(name, lambda: None)()
        except Exception as e:
            self.status_var.set(f"刷新失败: {e}")

    def set_status(self, text: str):
        self.status_var.set(text)

    # ---------- 备份（并行第一批线③：PRD P4 功能 6 单机版） ----------
    def _backup_now(self):
        """手动备份：调 backup.backup_db，结果弹窗提示。"""
        try:
            from backup import backup_db
            path = backup_db(DB_PATH)
            self.set_status(f"备份完成：{os.path.basename(path)}")
            messagebox.showinfo("备份完成", f"数据已备份到：\n{path}")
        except Exception as e:
            _logger.error("备份失败: %s", e)
            messagebox.showerror("备份失败", str(e))


def main():
    # P3-T2：生产入口强制登录（无用户先初始化管理员）
    app = MainApp(require_login=True)
    app.mainloop()


if __name__ == "__main__":
    main()
