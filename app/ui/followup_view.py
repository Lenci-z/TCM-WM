# -*- coding: utf-8 -*-
"""随访管理 视图（占位）"""
import tkinter as tk
from tkinter import ttk


class FollowupView(ttk.Frame):
    """随访管理。"""

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        tk.Label(self, text="随访管理", font=("微软雅黑", 16, "bold")).pack(pady=20)
        tk.Label(self, text="随访计划 + 复评录入（3.5 建设中）", fg="#666666").pack(pady=10)

    def refresh(self):
        pass
