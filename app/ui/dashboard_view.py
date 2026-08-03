# -*- coding: utf-8 -*-
"""
数据看板视图（阶段7-2）：患者/分层/证型/随访/预警/处方统计概览。
数据来源：repo.stats_summary() / pattern_distribution() / list_open_alerts()
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tkinter as tk
from tkinter import ttk

from log import get_logger

_logger = get_logger("view.dashboard")


class DashboardView(ttk.Frame):
    """数据看板：统计卡片 + 分布表 + 未处理预警概览。"""

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self._build()
        self.refresh()

    def _build(self):
        # ---- 顶部：统计卡片 ----
        cards = ttk.Frame(self)
        cards.pack(fill="x", padx=8, pady=8)
        self.card_vars = {}
        labels = [
            ("total_patients", "患者总数"),
            ("in_group", "在组患者"),
            ("risk_high", "高危"),
            ("risk_medium", "中危"),
            ("risk_low", "低危"),
            ("pending_followups", "待随访"),
            ("open_alerts", "未处理预警"),
            ("signed_rx", "已签发处方"),
        ]
        for i, (key, text) in enumerate(labels):
            box = tk.LabelFrame(cards, text=text, font=("微软雅黑", 9),
                                fg="#8B2F2F", width=140, height=76)
            box.grid(row=i // 4, column=i % 4, padx=6, pady=6)
            box.grid_propagate(False)
            var = tk.StringVar(value="0")
            self.card_vars[key] = var
            tk.Label(box, textvariable=var, font=("微软雅黑", 20, "bold"),
                     fg="#333333").pack(expand=True)

        # ---- 下方：分布 + 预警 ----
        bottom = ttk.PanedWindow(self, orient="horizontal")
        bottom.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        # 左：危险分层分布 + 证型分布
        left = ttk.Frame(bottom)
        ttk.Label(left, text="危险分层分布（最新确认）", font=("微软雅黑", 10, "bold")).pack(anchor="w", padx=4, pady=(4, 2))
        self.risk_tree = ttk.Treeview(left, columns=("level", "cnt"), show="headings", height=4)
        self.risk_tree.heading("level", text="分层")
        self.risk_tree.heading("cnt", text="人数")
        self.risk_tree.column("level", width=120, anchor="center")
        self.risk_tree.column("cnt", width=80, anchor="center")
        self.risk_tree.pack(fill="x", padx=4, pady=2)

        ttk.Label(left, text="证型分布（最新确认）", font=("微软雅黑", 10, "bold")).pack(anchor="w", padx=4, pady=(10, 2))
        self.pattern_tree = ttk.Treeview(left, columns=("pattern", "cnt"), show="headings", height=8)
        self.pattern_tree.heading("pattern", text="证型")
        self.pattern_tree.heading("cnt", text="人数")
        self.pattern_tree.column("pattern", width=120, anchor="center")
        self.pattern_tree.column("cnt", width=80, anchor="center")
        self.pattern_tree.pack(fill="x", padx=4, pady=2)
        bottom.add(left, weight=1)

        # 右：未处理预警概览
        right = ttk.Frame(bottom)
        ttk.Label(right, text="未处理预警（最近 10 条）", font=("微软雅黑", 10, "bold")).pack(anchor="w", padx=4, pady=(4, 2))
        cols = ("level", "patient", "rule", "date", "detail")
        self.alert_tree = ttk.Treeview(right, columns=cols, show="headings", height=14)
        heads = {"level": "级别", "patient": "患者", "rule": "预警规则", "date": "日期", "detail": "内容"}
        widths = {"level": 50, "patient": 70, "rule": 140, "date": 90, "detail": 220}
        for c in cols:
            self.alert_tree.heading(c, text=heads[c])
            self.alert_tree.column(c, width=widths[c], anchor="center")
        self.alert_tree.column("detail", anchor="w")
        self.alert_tree.pack(fill="both", expand=True, padx=4, pady=2)
        bottom.add(right, weight=2)

        # 刷新按钮
        ttk.Button(self, text="刷新看板", command=self.refresh).pack(anchor="e", padx=10, pady=(0, 8))

    # ---------- 数据 ----------
    def refresh(self):
        try:
            s = self.app.repo.stats_summary()
            for key, var in self.card_vars.items():
                var.set(str(s.get(key, 0)))
            # 分层分布
            for item in self.risk_tree.get_children():
                self.risk_tree.delete(item)
            risk_map = {"高危": s.get("risk_high", 0), "中危": s.get("risk_medium", 0),
                        "低危": s.get("risk_low", 0)}
            for level in ("高危", "中危", "低危"):
                self.risk_tree.insert("", "end", values=(level, risk_map[level]))
            # 证型分布
            for item in self.pattern_tree.get_children():
                self.pattern_tree.delete(item)
            for r in self.app.repo.pattern_distribution():
                self.pattern_tree.insert("", "end", values=(r["main_pattern"], r["cnt"]))
            # 未处理预警
            for item in self.alert_tree.get_children():
                self.alert_tree.delete(item)
            for r in self.app.repo.list_open_alerts(10):
                self.alert_tree.insert("", "end", values=(
                    r["level"], r.get("patient_name", ""), r["rule_name"],
                    r["alert_date"], (r.get("detail") or "")[:60]))
        except Exception as e:
            _logger.error("看板刷新失败: %s", e)
