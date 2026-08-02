# -*- coding: utf-8 -*-
"""患者管理 视图（占位）"""
import tkinter as tk
from tkinter import ttk


class PatientView(ttk.Frame):
    """患者管理。"""

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        tk.Label(self, text="患者管理", font=("微软雅黑", 16, "bold")).pack(pady=20)
        tk.Label(self, text="患者建档 + 手术信息（3.2 建设中）", fg="#666666").pack(pady=10)

    def refresh(self):
        pass
