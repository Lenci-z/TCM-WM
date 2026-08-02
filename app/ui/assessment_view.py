# -*- coding: utf-8 -*-
"""评估录入 视图（占位）"""
import tkinter as tk
from tkinter import ttk


class AssessmentView(ttk.Frame):
    """评估录入。"""

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        tk.Label(self, text="评估录入", font=("微软雅黑", 16, "bold")).pack(pady=20)
        tk.Label(self, text="结构化评估 + 四诊问卷（3.3 建设中）", fg="#666666").pack(pady=10)

    def refresh(self):
        pass
