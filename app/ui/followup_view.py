# -*- coding: utf-8 -*-
"""
随访管理视图（3.5）：随访计划自动生成（1周/1月/3月/6月/12月）+ 到期提醒 + 复评录入
依据：设计方案 v0.2 第 2.2 节（随访复评表）、2.7 节（分期路径）
计划起算：手术日(Day 0) → 无则建档日期；节点模板取 disease_config.followup_template_json
"""
import sys
import os
import json
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class FollowupView(ttk.Frame):
    """随访管理：计划生成/到期提醒/复评录入。"""

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.current_pid = None

        left = ttk.Frame(self)
        left.pack(side="left", fill="y", padx=(8, 4), pady=8)
        right = ttk.Frame(self)
        right.pack(side="left", fill="both", expand=True, padx=(4, 8), pady=8)

        # ---- 左侧：患者 ----
        ttk.Label(left, text="选择患者", font=("微软雅黑", 11, "bold")).pack(anchor="w")
        self.patient_tree = ttk.Treeview(left, columns=("id", "name", "disease"), show="headings", height=14)
        for c, (t, w) in {"id": ("ID", 50), "name": ("姓名", 90), "disease": ("病种", 100)}.items():
            self.patient_tree.heading(c, text=t)
            self.patient_tree.column(c, width=w, anchor="center")
        self.patient_tree.pack(fill="both", expand=True)
        self.patient_tree.bind("<<TreeviewSelect>>", self._on_patient_select)

        ttk.Label(left, text="到期提醒（7天内/逾期）", font=("微软雅黑", 11, "bold")).pack(anchor="w", pady=(10, 2))
        self.due_tree = ttk.Treeview(left, columns=("fid", "type", "plan", "status"), show="headings", height=10)
        for c, (t, w) in {"fid": ("ID", 40), "type": ("类型", 55), "plan": ("计划日期", 95), "status": ("状态", 60)}.items():
            self.due_tree.heading(c, text=t)
            self.due_tree.column(c, width=w, anchor="center")
        self.due_tree.pack(fill="both", expand=True)
        self.due_tree.bind("<<TreeviewSelect>>", lambda e: self._select_from_due())

        # ---- 右侧：计划管理 ----
        top = ttk.LabelFrame(right, text="随访计划", padding=8)
        top.pack(fill="both", expand=True, pady=4)
        toolbar = ttk.Frame(top)
        toolbar.pack(fill="x", pady=4)
        ttk.Button(toolbar, text="生成随访计划", command=self._generate_plan).pack(side="left", padx=4)
        self.btn_export = ttk.Button(toolbar, text="导出随访 CSV", command=self._export_csv)
        self.btn_export.pack(side="left", padx=4)
        ttk.Button(toolbar, text="标记完成（复评录入）", command=self._complete_fu).pack(side="left", padx=4)
        ttk.Button(toolbar, text="查看必查项", command=self._show_required).pack(side="left", padx=4)
        self.fu_status = tk.StringVar(value="")
        tk.Label(toolbar, textvariable=self.fu_status, fg="green").pack(side="left", padx=8)

        cols = ("fid", "type", "plan", "actual", "status", "handler")
        self.fu_tree = ttk.Treeview(top, columns=cols, show="headings")
        heads = {"fid": ("ID", 45), "type": ("随访类型", 70), "plan": ("计划日期", 100),
                 "actual": ("实际日期", 100), "status": ("状态", 80), "handler": ("完成人", 90)}
        for c, (t, w) in heads.items():
            self.fu_tree.heading(c, text=t)
            self.fu_tree.column(c, width=w, anchor="center")
        self.fu_tree.pack(fill="both", expand=True)
        sb = ttk.Scrollbar(top, orient="vertical", command=self.fu_tree.yview)
        self.fu_tree.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.fu_tree.bind("<<TreeviewSelect>>", self._on_fu_select)

        # 复评记录
        rec = ttk.LabelFrame(right, text="复评记录（选中计划后显示）", padding=8)
        rec.pack(fill="both", expand=True, pady=4)
        self.rec_text = tk.Text(rec, height=8, font=("微软雅黑", 10))
        self.rec_text.pack(fill="both", expand=True)

        # 下方提示
        tk.Label(right, text="提示：完整复评（量表/检查/证型复评）请到『评估录入』Tab 按随访类型录入；"
                              "复评后如需调整处方请到『处方管理』Tab。",
                  fg="#666666").pack(anchor="w", pady=4)
        self.refresh()

    def _export_csv(self):
        """导出随访记录 CSV（阶段7-3）。"""
        from tkinter import filedialog, messagebox
        from csv_export import export_csv, followup_csv_rows
        path = filedialog.asksaveasfilename(
            defaultextension=".csv", filetypes=[("CSV 文件", "*.csv")],
            initialfile="随访记录.csv")
        if not path:
            return
        rows = followup_csv_rows(self.app.repo.list_followups_all())
        headers = ["followup_id", "patient_id", "patient_name", "fu_type",
                   "plan_date", "actual_date", "fu_status", "handler"]
        n = export_csv(path, headers, rows)
        _logger.info("导出随访 CSV: %s (%d 条)", path, n)
        messagebox.showinfo("导出成功", f"已导出 {n} 条随访记录")

    # ---------- 数据 ----------
    def refresh(self):
        for item in self.patient_tree.get_children():
            self.patient_tree.delete(item)
        for p in self.app.repo.list_patients():
            self.patient_tree.insert("", "end", iid=str(p["patient_id"]), values=(
                p["patient_id"], p["name"], p["disease_category"]))

    def _on_patient_select(self, event):
        sel = self.patient_tree.selection()
        if not sel:
            return
        self.current_pid = int(sel[0])
        self._load_plan()
        self._load_due()

    def _followup_template(self):
        cfg = self.app.repo.get_followup_template("CAD_PCI")
        if not cfg:
            return []
        return cfg.get("nodes", [])

    def _day0(self, pid):
        """Day 0：手术日期优先，其次建档日期（repo.get_day0）。"""
        day0_str = self.app.repo.get_day0(pid)
        if day0_str:
            try:
                return date.fromisoformat(day0_str[:10])
            except ValueError:
                pass
        return date.today()

    def _generate_plan(self):
        """按模板生成随访计划（已存在同类型则不重复生成）。"""
        if self.current_pid is None:
            messagebox.showwarning("提示", "请先在左侧选择患者")
            return
        day0 = self._day0(self.current_pid)
        nodes = self._followup_template()
        if not nodes:
            messagebox.showwarning("提示", "病种未配置随访模板")
            return
        existing = set(self.app.repo.list_existing_fu_types(self.current_pid))
        n = 0
        for node in nodes:
            if node["code"] in existing:
                continue
            plan_date = day0 + timedelta(days=node["offset_days"])
            self.app.repo.insert_followup({
                "patient_id": self.current_pid,
                "plan_date": plan_date.isoformat(),
                "fu_type": node["code"],
                "status": "待随访",
            })
            n += 1
        self._load_plan()
        self._load_due()
        msg = f"已生成 {n} 条随访计划（起算日 {day0}）" if n else "随访计划已齐全，无新增"
        self.fu_status.set(msg)
        self.app.set_status(msg)

    def _load_plan(self):
        for item in self.fu_tree.get_children():
            self.fu_tree.delete(item)
        if self.current_pid is None:
            return
        rows = self.app.repo.list_followups(self.current_pid)
        for r in rows:
            self.fu_tree.insert("", "end", iid=str(r["fu_id"]), values=(
                r["fu_id"], r["fu_type"], r["plan_date"], r["actual_date"] or "",
                r["status"], r["handler"] or ""))

    def _load_due(self):
        """到期提醒：逾期（红）与 7 天内（黄）。"""
        for item in self.due_tree.get_children():
            self.due_tree.delete(item)
        today = date.today()
        rows = self.app.repo.query_all(
            "SELECT fu_id, fu_type, plan_date, status FROM follow_up "
            "WHERE status='待随访' ORDER BY plan_date"
        )
        for r in rows:
            try:
                delta = (date.fromisoformat(r["plan_date"]) - today).days
            except ValueError:
                continue
            if delta <= 7:
                tag = "overdue" if delta < 0 else "soon"
                self.due_tree.insert("", "end", iid=f"due_{r['fu_id']}", tags=(tag,), values=(
                    r["fu_id"], r["fu_type"], r["plan_date"], "逾期" if delta < 0 else f"{delta}天后"))
        self.due_tree.tag_configure("overdue", background="#FFD6D6")
        self.due_tree.tag_configure("soon", background="#FFF3CD")

    def _on_fu_select(self, event):
        sel = self.fu_tree.selection()
        if not sel:
            return
        fu = self.app.repo.get_followup(int(sel[0]))
        if not fu:
            return
        self.rec_text.delete("1.0", "end")
        if fu["record_json"]:
            try:
                rec = json.loads(fu["record_json"])
                self.rec_text.insert("1.0", json.dumps(rec, ensure_ascii=False, indent=2))
            except ValueError:
                self.rec_text.insert("1.0", fu["record_json"])
        else:
            self.rec_text.insert("1.0", f"（暂无复评记录）\n必查项：{self._required_text(fu['fu_type'])}")

    def _select_from_due(self):
        sel = self.due_tree.selection()
        if not sel:
            return
        fid = int(sel[0].replace("due_", ""))
        self.fu_tree.selection_set(str(fid))
        self.fu_tree.see(str(fid))
        self._on_fu_select(None)

    def _required_text(self, fu_type):
        for node in self._followup_template():
            if node["code"] == fu_type:
                req = "、".join(node["required"])
                opt = "、".join(node["optional"])
                return f"{req}" + (f"；选查：{opt}" if opt else "")
        return ""

    def _show_required(self):
        sel = self.fu_tree.selection()
        if not sel:
            messagebox.showinfo("随访必查项", "请先选中一条随访计划")
            return
        fu = self.app.repo.get_followup(int(sel[0]))
        messagebox.showinfo(f"{fu['fu_type']} 必查项", self._required_text(fu["fu_type"]))

    def _complete_fu(self):
        """复评录入：标记完成。"""
        sel = self.fu_tree.selection()
        if not sel:
            messagebox.showwarning("提示", "请先选中一条随访计划")
            return
        fid = int(sel[0])
        fu = self.app.repo.get_followup(fid)
        record = simpledialog.askstring(
            "复评录入", f"随访类型：{fu['fu_type']}\n必查项：{self._required_text(fu['fu_type'])}\n\n复评记录（可留空）：")
        if record is None:
            return
        handler = simpledialog.askstring("完成人", "完成人（医师）：") or ""
        today = date.today().isoformat()
        self.app.repo.update_followup_status(
            fid, today, handler,
            json.dumps({"note": record, "done_at": today}, ensure_ascii=False))
        self._load_plan()
        self._load_due()
        self.fu_status.set(f"随访 #{fid}（{fu['fu_type']}）已完成")
        self.app.set_status(f"随访 #{fid} 已完成，请到评估/处方 Tab 做完整复评与调整")


if __name__ == "__main__":
    from ui.main import MainApp
    app = MainApp()
    app.after(1500, app.destroy)
    app.mainloop()
    print("随访管理视图启动测试通过")
