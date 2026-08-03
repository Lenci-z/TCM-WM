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

    def __init__(self):
        super().__init__()
        setup_logging()
        _install_excepthook()
        _logger.info("系统启动")
        self.title("中西医结合心血管康复全程管理系统 V0.1（MVP）")
        self.geometry("1280x800")
        self.minsize(1100, 700)

        # 数据库初始化（首次启动建库 + 导入种子；后续直接打开）
        self._init_database()

        # 顶部标题栏
        header = tk.Frame(self, bg="#8B2F2F", height=56)
        header.pack(fill="x")
        header.pack_propagate(False)
        tk.Label(header, text="中西医结合心血管康复全程管理系统",
                 bg="#8B2F2F", fg="white", font=("微软雅黑", 18, "bold")).pack(side="left", padx=16)
        tk.Label(header, text="中医证型 × 心血管危险分层 双轴驱动 ｜ 第一版：CAD_PCI",
                 bg="#8B2F2F", fg="#F5E6C8", font=("微软雅黑", 10)).pack(side="right", padx=16)

        # 主体：Notebook 五区导航
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True, padx=8, pady=8)

        # 延迟导入各视图，避免循环依赖
        from ui.patient_view import PatientView
        from ui.assessment_view import AssessmentView
        from ui.prescription_view import PrescriptionView
        from ui.followup_view import FollowupView
        from ui.rules_view import RulesView

        self.tab_patient = PatientView(self.notebook, self)
        self.tab_assess = AssessmentView(self.notebook, self)
        self.tab_rx = PrescriptionView(self.notebook, self)
        self.tab_followup = FollowupView(self.notebook, self)
        self.tab_rules = RulesView(self.notebook, self)

        self.notebook.add(self.tab_patient, text="  患者管理  ")
        self.notebook.add(self.tab_assess, text="  评估录入  ")
        self.notebook.add(self.tab_rx, text="  处方管理  ")
        self.notebook.add(self.tab_followup, text="  随访管理  ")
        self.notebook.add(self.tab_rules, text="  规则库维护  ")

        self.notebook.bind("<<NotebookTabChanged>>", self._on_tab_change)

        # 状态栏
        self.status_var = tk.StringVar(value="就绪")
        status = tk.Label(self, textvariable=self.status_var, anchor="w",
                          relief="sunken", bg="#F0F0F0", font=("微软雅黑", 9))
        status.pack(fill="x", side="bottom")

    # ---------- 数据库 ----------
    def _init_database(self):
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


def main():
    app = MainApp()
    app.mainloop()


if __name__ == "__main__":
    main()
