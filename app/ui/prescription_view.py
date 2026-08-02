# -*- coding: utf-8 -*-
"""处方管理 视图（占位）"""
import tkinter as tk
from tkinter import ttk


class PrescriptionView(ttk.Frame):
    """处方管理。"""

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        tk.Label(self, text="处方管理", font=("微软雅黑", 16, "bold")).pack(pady=20)
        tk.Label(self, text="处方生成/签发/打印（3.4 建设中）", fg="#666666").pack(pady=10)

    def refresh(self):
        pass
