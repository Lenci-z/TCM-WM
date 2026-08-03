# -*- coding: utf-8 -*-
"""
依从性打卡视图（阶段7-1）：患者日常任务打卡（八段锦/运动/服药/测量）+ 历史与统计。
数据表：adherence_log（task_type/is_done/actual_duration/self_rpe/symptom_json/remark）
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tkinter as tk
from tkinter import ttk, messagebox

from log import get_logger

_logger = get_logger("view.adherence")

TASK_TYPES = ["八段锦", "运动", "服药", "测量"]
SYMPTOMS = ["无", "胸闷", "心悸", "气短", "头晕", "乏力", "胸痛"]


class AdherenceView(ttk.Frame):
    """依从性打卡：左侧患者列表，右侧打卡表单 + 历史 + 统计。"""

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.current_pid = None

        paned = ttk.PanedWindow(self, orient="horizontal")
        paned.pack(fill="both", expand=True, padx=8, pady=8)

        # ---- 左侧：患者列表 ----
        left = ttk.Frame(paned)
        ttk.Label(left, text="患者列表", font=("微软雅黑", 11, "bold")).pack(anchor="w", padx=6, pady=(4, 2))
        self.patient_tree = ttk.Treeview(left, columns=("name", "dc"), show="headings", height=22)
        self.patient_tree.heading("name", text="姓名")
        self.patient_tree.heading("dc", text="病种")
        self.patient_tree.column("name", width=90, anchor="center")
        self.patient_tree.column("dc", width=80, anchor="center")
        self.patient_tree.pack(fill="both", expand=True, padx=6, pady=4)
        self.patient_tree.bind("<<TreeviewSelect>>", self._on_patient_select)
        paned.add(left, weight=1)

        # ---- 右侧：打卡表单 + 历史 ----
        right = ttk.Frame(paned)
        ttk.Label(right, text="依从性打卡（每日任务记录）", font=("微软雅黑", 11, "bold")).pack(anchor="w", padx=6, pady=(4, 4))
        form = ttk.LabelFrame(right, text="新增打卡", padding=8)
        form.pack(fill="x", padx=6, pady=(0, 6))

        self.vars = {}
        row = 0
        ttk.Label(form, text="日期：").grid(row=row, column=0, sticky="e", padx=4, pady=3)
        self.vars["log_date"] = tk.StringVar(value=self._today())
        ttk.Entry(form, textvariable=self.vars["log_date"], width=12).grid(row=row, column=1, sticky="w", padx=4, pady=3)
        ttk.Label(form, text="任务类型：").grid(row=row, column=2, sticky="e", padx=4, pady=3)
        self.vars["task_type"] = tk.StringVar(value="八段锦")
        ttk.Combobox(form, textvariable=self.vars["task_type"], values=TASK_TYPES,
                     width=8, state="readonly").grid(row=row, column=3, sticky="w", padx=4, pady=3)
        row += 1
        ttk.Label(form, text="是否完成：").grid(row=row, column=0, sticky="e", padx=4, pady=3)
        self.vars["is_done"] = tk.StringVar(value="是")
        ttk.Combobox(form, textvariable=self.vars["is_done"], values=["是", "否"],
                     width=8, state="readonly").grid(row=row, column=1, sticky="w", padx=4, pady=3)
        ttk.Label(form, text="时长(分钟)：").grid(row=row, column=2, sticky="e", padx=4, pady=3)
        self.vars["actual_duration"] = tk.StringVar(value="")
        ttk.Entry(form, textvariable=self.vars["actual_duration"], width=8).grid(row=row, column=3, sticky="w", padx=4, pady=3)
        row += 1
        ttk.Label(form, text="自评RPE(6-20)：").grid(row=row, column=0, sticky="e", padx=4, pady=3)
        self.vars["self_rpe"] = tk.StringVar(value="")
        ttk.Entry(form, textvariable=self.vars["self_rpe"], width=8).grid(row=row, column=1, sticky="w", padx=4, pady=3)
        ttk.Label(form, text="症状：").grid(row=row, column=2, sticky="e", padx=4, pady=3)
        sym_frame = ttk.Frame(form)
        sym_frame.grid(row=row, column=3, sticky="w", padx=4, pady=3)
        self.symptom_checks = {}
        for i, s in enumerate(SYMPTOMS):
            self.symptom_checks[s] = tk.BooleanVar()
            ttk.Checkbutton(sym_frame, text=s, variable=self.symptom_checks[s]).grid(row=0, column=i, padx=2)
        row += 1
        ttk.Label(form, text="备注：").grid(row=row, column=0, sticky="e", padx=4, pady=3)
        self.vars["remark"] = tk.StringVar(value="")
        ttk.Entry(form, textvariable=self.vars["remark"], width=38).grid(row=row, column=1, columnspan=3, sticky="w", padx=4, pady=3)
        row += 1
        self.btn_save = ttk.Button(form, text="保存打卡", command=self._save)
        self.btn_save.grid(row=row, column=3, sticky="e", padx=4, pady=6)

        # 统计
        self.stat_var = tk.StringVar(value="— 选择患者查看打卡统计 —")
        tk.Label(right, textvariable=self.stat_var, fg="#8B2F2F", font=("微软雅黑", 10)).pack(anchor="w", padx=8, pady=(0, 4))

        # 历史
        ttk.Label(right, text="打卡历史", font=("微软雅黑", 10, "bold")).pack(anchor="w", padx=6)
        cols = ("date", "type", "done", "duration", "rpe", "symptom", "remark")
        self.history = ttk.Treeview(right, columns=cols, show="headings", height=12)
        heads = {"date": "日期", "type": "任务", "done": "完成", "duration": "时长(分)",
                 "rpe": "RPE", "symptom": "症状", "remark": "备注"}
        widths = {"date": 90, "type": 70, "done": 50, "duration": 70, "rpe": 50,
                  "symptom": 110, "remark": 150}
        for c in cols:
            self.history.heading(c, text=heads[c])
            self.history.column(c, width=widths[c], anchor="center")
        self.history.column("remark", anchor="w")
        self.history.pack(fill="both", expand=True, padx=6, pady=4)
        paned.add(right, weight=3)

        self.refresh()
        self._apply_permissions()

    # ---------- 数据 ----------
    def _today(self):
        from datetime import date
        return date.today().isoformat()

    def refresh(self):
        for item in self.patient_tree.get_children():
            self.patient_tree.delete(item)
        for p in self.app.repo.list_patients():
            self.patient_tree.insert("", "end", iid=str(p["patient_id"]),
                                     values=(p["name"], p.get("disease_category", "")))
        self._load_history()

    def _on_patient_select(self, event):
        sel = self.patient_tree.selection()
        if not sel:
            return
        self.current_pid = int(sel[0])
        self._load_history()
        self._load_stats()

    def _load_history(self):
        for item in self.history.get_children():
            self.history.delete(item)
        if not self.current_pid:
            return
        for r in self.app.repo.list_adherences(self.current_pid):
            symptoms = json.loads(r["symptom_json"]) if r.get("symptom_json") else []
            self.history.insert("", "end", values=(
                r["log_date"], r["task_type"], "✓" if r["is_done"] else "✗",
                r["actual_duration"] or "", r["self_rpe"] or "",
                "/".join(symptoms), r["remark"] or ""))

    def _load_stats(self):
        s = self.app.repo.list_adherence_stats(self.current_pid)
        self.stat_var.set(
            f"打卡 {s['days']} 天 ｜ 完成率 {s['completion_rate']}%（{s['done_cnt']}/{s['total_cnt']}）"
            f" ｜ 运动累计 {s['exercise_min']} 分钟 ｜ 八段锦完成 {s['baduanjin_done']} 次")

    def _save(self):
        if self.current_pid is None:
            messagebox.showwarning("提示", "请先在左侧选择患者")
            return
        log_date = self.vars["log_date"].get().strip()
        if not log_date:
            messagebox.showwarning("输入校验", "日期不能为空")
            return
        duration = self.vars["actual_duration"].get().strip()
        if duration:
            try:
                duration = int(duration)
                if not (0 <= duration <= 600):
                    messagebox.showwarning("输入校验", "时长超出合理范围（0-600 分钟）")
                    return
            except ValueError:
                messagebox.showwarning("输入校验", "时长必须为整数分钟")
                return
        else:
            duration = None
        rpe = self.vars["self_rpe"].get().strip()
        if rpe:
            try:
                rpe = int(rpe)
                if not (6 <= rpe <= 20):
                    messagebox.showwarning("输入校验", "RPE 超出合理范围（6-20）")
                    return
            except ValueError:
                messagebox.showwarning("输入校验", "RPE 必须为 6-20 的整数")
                return
        else:
            rpe = None
        symptoms = [s for s, v in self.symptom_checks.items() if v.get()]
        data = {
            "patient_id": self.current_pid,
            "log_date": log_date,
            "task_type": self.vars["task_type"].get(),
            "is_done": 1 if self.vars["is_done"].get() == "是" else 0,
            "actual_duration": duration,
            "self_rpe": rpe,
            "symptom_json": json.dumps(symptoms, ensure_ascii=False) if symptoms else None,
            "remark": self.vars["remark"].get().strip() or None,
        }
        self.app.repo.insert_adherence(data)
        _logger.info("打卡记录: patient=%s task=%s date=%s", self.current_pid,
                     data["task_type"], log_date)
        # 重置表单（保留日期与患者）
        self.vars["actual_duration"].set("")
        self.vars["self_rpe"].set("")
        self.vars["remark"].set("")
        for v in self.symptom_checks.values():
            v.set(False)
        self._load_history()
        self._load_stats()
        messagebox.showinfo("保存成功", "打卡记录已保存")

    def _apply_permissions(self):
        # 打卡属随访健康管理（followup:complete 全员可用），仅未登录时禁用
        state = tk.NORMAL if self.app.check_perm("followup:complete") else tk.DISABLED
        self.btn_save.config(state=state)
