# -*- coding: utf-8 -*-
"""规则库维护 视图（占位）"""
import tkinter as tk
from tkinter import ttk


class RulesView(ttk.Frame):
    """规则库维护。"""

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        tk.Label(self, text="规则库维护", font=("微软雅黑", 16, "bold")).pack(pady=20)
        tk.Label(self, text="分层阈值/模板/预警可视化编辑（3.6 建设中）", fg="#666666").pack(pady=10)

    def refresh(self):
        pass
