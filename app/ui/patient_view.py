# -*- coding: utf-8 -*-
"""
患者管理视图（3.2）：建档（patient + procedure 全字段）+ 列表 + 编辑
姓名/联系方式加密存储，界面显示明文。
"""
import sys
import os
import tkinter as tk
from tkinter import ttk, messagebox

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from log import get_logger


_logger = get_logger("view.patient")
class PatientView(ttk.Frame):
    """患者建档：左侧列表 + 右侧表单。"""

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.current_pid = None  # 当前编辑的患者 id（None=新建）

        # 左右分栏
        left = ttk.Frame(self)
        left.pack(side="left", fill="y", padx=(8, 4), pady=8)
        right = ttk.Frame(self)
        right.pack(side="left", fill="both", expand=True, padx=(4, 8), pady=8)

        # ---- 左侧：患者列表 ----
        ttk.Label(left, text="患者列表", font=("微软雅黑", 11, "bold")).pack(anchor="w")
        cols = ("id", "name", "gender", "birth", "disease", "status", "physician")
        self.tree = ttk.Treeview(left, columns=cols, show="headings", height=24)
        headers = {"id": ("ID", 50), "name": ("姓名", 90), "gender": ("性别", 50),
                   "birth": ("出生日期", 90), "disease": ("病种", 100),
                   "status": ("状态", 70), "physician": ("责任医师", 90)}
        for c, (t, w) in headers.items():
            self.tree.heading(c, text=t)
            self.tree.column(c, width=w, anchor="center")
        self.tree.pack(fill="both", expand=True)
        sb = ttk.Scrollbar(left, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        self.tree.bind("<Double-1>", lambda e: self._load_form())

        btns = ttk.Frame(left)
        btns.pack(fill="x", pady=6)
        ttk.Button(btns, text="新建", command=self._new).pack(side="left", padx=2)
        ttk.Button(btns, text="载入选中", command=self._load_form).pack(side="left", padx=2)
        self.btn_delete = ttk.Button(btns, text="删除选中", command=self._delete)
        self.btn_delete.pack(side="left", padx=2)
        self.btn_export = ttk.Button(btns, text="导出患者 CSV", command=self._export_csv)
        self.btn_export.pack(side="left", padx=2)

        # ---- 右侧：建档表单 ----
        self._build_form(right)
        self.refresh()
        self._apply_permissions()

    # ---------- 表单构建 ----------
    def _build_form(self, parent):
        frm = ttk.LabelFrame(parent, text="患者建档（姓名/联系方式加密存储）", padding=10)
        frm.pack(fill="both", expand=True)

        # 基本信息
        base = ttk.LabelFrame(frm, text="基本信息（patient）", padding=8)
        base.pack(fill="x", pady=4)
        self.vars = {}
        fields = [
            ("name", "姓名*"), ("gender", "性别"), ("birth_date", "出生日期(YYYY-MM-DD)"),
            ("contact", "联系方式"), ("inpatient_no", "住院号"), ("physician", "责任医师"),
            ("register_date", "建档日期*"), ("status", "状态"), ("disease_category", "病种"),
        ]
        for i, (key, label) in enumerate(fields):
            r, c = divmod(i, 3)
            ttk.Label(base, text=label).grid(row=r, column=c * 2, sticky="e", padx=4, pady=3)
            if key in ("gender", "status", "disease_category"):
                var = ttk.Combobox(base, width=16, state="readonly")
                var.grid(row=r, column=c * 2 + 1, sticky="w", padx=4, pady=3)
            else:
                var = ttk.Entry(base, width=18)
                var.grid(row=r, column=c * 2 + 1, sticky="w", padx=4, pady=3)
            self.vars[key] = var
        self.vars["gender"]["values"] = ["男", "女"]
        self.vars["status"]["values"] = ["建档", "在组", "随访中", "完成", "失访", "退出"]
        self.vars["disease_category"]["values"] = self._enabled_diseases()
        self.vars["register_date"].insert(0, tk.StringVar(value="").get() or self._today())

        # 手术信息
        proc = ttk.LabelFrame(frm, text="手术信息（procedure）", padding=8)
        proc.pack(fill="x", pady=4)
        self.pvars = {}
        pfields = [
            ("proc_date", "手术日期(Day 0)"), ("proc_type", "手术类型"),
            ("stent_count", "支架数"), ("lesion_vessel_count", "病变支数"),
            ("incision_type", "切口类型"), ("anticoagulation", "抗凝状态"),
        ]
        for i, (key, label) in enumerate(pfields):
            r, c = divmod(i, 3)
            ttk.Label(proc, text=label).grid(row=r, column=c * 2, sticky="e", padx=4, pady=3)
            if key in ("proc_type", "incision_type", "anticoagulation"):
                var = ttk.Combobox(proc, width=16, state="readonly")
                var.grid(row=r, column=c * 2 + 1, sticky="w", padx=4, pady=3)
            else:
                var = ttk.Entry(proc, width=18)
                var.grid(row=r, column=c * 2 + 1, sticky="w", padx=4, pady=3)
            self.pvars[key] = var
        self.pvars["proc_type"]["values"] = ["PCI", "CABG", "瓣膜", "起搏器", "ICD", "无手术"]
        self.pvars["incision_type"]["values"] = ["经皮", "胸骨正中", "微创"]
        self.pvars["anticoagulation"]["values"] = ["无", "单抗", "DAPT", "华法林", "NOAC"]

        flags = ttk.Frame(frm)
        flags.pack(fill="x", pady=4)
        self.flag_complete = tk.BooleanVar()
        self.flag_emergency = tk.BooleanVar()
        ttk.Checkbutton(flags, text="完全血运重建", variable=self.flag_complete).pack(side="left", padx=10)
        ttk.Checkbutton(flags, text="急诊手术", variable=self.flag_emergency).pack(side="left", padx=10)

        # 操作按钮
        ops = ttk.Frame(frm)
        ops.pack(fill="x", pady=8)
        ttk.Button(ops, text="保存建档", command=self._save).pack(side="left", padx=6)
        ttk.Button(ops, text="清空表单", command=self._new).pack(side="left", padx=6)
        self.saved_var = tk.StringVar(value="")
        tk.Label(ops, textvariable=self.saved_var, fg="green").pack(side="left", padx=10)

    def _apply_permissions(self):
        """RBAC 按钮显隐（P3-T3）：删除按钮仅 patient:delete 权限可用。"""
        state = tk.NORMAL if self.app.check_perm("patient:delete") else tk.DISABLED
        self.btn_delete.config(state=state)

    def _export_csv(self):
        """导出患者列表 CSV（阶段7-3）。"""
        from tkinter import filedialog, messagebox
        from csv_export import export_csv, patient_csv_rows
        path = filedialog.asksaveasfilename(
            defaultextension=".csv", filetypes=[("CSV 文件", "*.csv")],
            initialfile="患者列表.csv")
        if not path:
            return
        patients = self.app.repo.list_patients()
        headers = ["patient_id", "name", "gender", "birth_date", "disease_category",
                   "register_date", "status", "contact", "inpatient_no"]
        n = export_csv(path, headers, patient_csv_rows(patients))
        _logger.info("导出患者 CSV: %s (%d 条)", path, n)
        messagebox.showinfo("导出成功", f"已导出 {n} 条患者记录")

    # ---------- 数据 ----------
    def _today(self):
        from datetime import date
        return date.today().isoformat()

    def _enabled_diseases(self):
        return self.app.repo.get_enabled_diseases() or ["CAD_PCI"]

    def refresh(self):
        """刷新患者列表（repo 解密返回明文）。"""
        for item in self.tree.get_children():
            self.tree.delete(item)
        for p in self.app.repo.list_patients():
            self.tree.insert("", "end", iid=str(p["patient_id"]), values=(
                p["patient_id"], p["name"], p["gender"] or "",
                p["birth_date"] or "", p["disease_category"], p["status"], p["physician"] or ""))

    def _on_select(self, event):
        sel = self.tree.selection()
        if sel:
            self.current_pid = int(sel[0])

    def _load_form(self):
        """载入选中患者到表单（编辑模式）。"""
        if not self.tree.selection():
            messagebox.showinfo("提示", "请先在列表中选择患者")
            return
        pid = int(self.tree.selection()[0])
        p = self.app.repo.get_patient(pid)
        if not p:
            return
        self.current_pid = pid
        self.vars["name"].delete(0, "end"); self.vars["name"].insert(0, p["name"] or "")
        self.vars["gender"].set(p["gender"] or "")
        self.vars["birth_date"].delete(0, "end"); self.vars["birth_date"].insert(0, p["birth_date"] or "")
        self.vars["contact"].delete(0, "end"); self.vars["contact"].insert(0, p["contact"] or "")
        self.vars["inpatient_no"].delete(0, "end"); self.vars["inpatient_no"].insert(0, p["inpatient_no"] or "")
        self.vars["physician"].delete(0, "end"); self.vars["physician"].insert(0, p["physician"] or "")
        self.vars["register_date"].delete(0, "end"); self.vars["register_date"].insert(0, p["register_date"] or "")
        self.vars["status"].set(p["status"] or "建档")
        self.vars["disease_category"].set(p["disease_category"] or "CAD_PCI")
        # procedure（取最新一条）
        proc = self.app.repo.get_procedure(pid)
        for var in self.pvars.values():
            if isinstance(var, ttk.Combobox):
                var.set("")
            else:
                var.delete(0, "end")
        if proc:
            self.pvars["proc_date"].insert(0, proc["proc_date"] or "")
            self.pvars["proc_type"].set(proc["proc_type"] or "")
            self.pvars["stent_count"].insert(0, proc["stent_count"] if proc["stent_count"] is not None else "")
            self.pvars["lesion_vessel_count"].insert(0,
                proc["lesion_vessel_count"] if proc["lesion_vessel_count"] is not None else "")
            self.pvars["incision_type"].set(proc["incision_type"] or "")
            self.pvars["anticoagulation"].set(proc["anticoagulation"] or "")
            self.flag_complete.set(bool(proc["complete_revascularization"]))
            self.flag_emergency.set(bool(proc["is_emergency"]))
        self.saved_var.set(f"已载入患者 #{pid}（编辑模式）")

    def _new(self):
        """新建：清空表单。"""
        self.current_pid = None
        for var in self.vars.values():
            if isinstance(var, ttk.Combobox):
                var.set("")
            else:
                var.delete(0, "end")
        for var in self.pvars.values():
            if isinstance(var, ttk.Combobox):
                var.set("")
            else:
                var.delete(0, "end")
        self.flag_complete.set(False)
        self.flag_emergency.set(False)
        self.vars["register_date"].insert(0, self._today())
        self.vars["status"].set("建档")
        self.vars["disease_category"].set(self._enabled_diseases()[0])
        self.saved_var.set("新建模式")

    def _save(self):
        """保存建档（新建或更新）。"""
        name = self.vars["name"].get().strip()
        if not name:
            messagebox.showwarning("必填项", "姓名不能为空")
            return
        reg = self.vars["register_date"].get().strip() or self._today()
        patient_data = {
            "name": name,
            "gender": self.vars["gender"].get() or None,
            "birth_date": self.vars["birth_date"].get().strip() or None,
            "contact": self.vars["contact"].get().strip() or None,
            "inpatient_no": self.vars["inpatient_no"].get().strip() or None,
            "register_date": reg,
            "physician": self.vars["physician"].get().strip() or None,
            "status": self.vars["status"].get() or "建档",
            "disease_category": self.vars["disease_category"].get() or "CAD_PCI",
        }
        try:
            if self.current_pid is None:
                pid = self.app.repo.insert_patient(patient_data)
                self.current_pid = pid
                # 同步建档 → 创建 procedure
                self._save_procedure(pid)
                msg = f"已建档 #{pid}"
            else:
                self.app.repo.update_patient(self.current_pid, patient_data)
                self._save_procedure(self.current_pid)
                msg = f"已更新 #{self.current_pid}"
            self.refresh()
            self.saved_var.set(msg)
            self.app.set_status(msg)
        except Exception as e:
            _logger.error("患者保存失败: %s", e)
            messagebox.showerror("保存失败", str(e))

    def _save_procedure(self, pid):
        """保存/更新手术信息（procedure）。"""
        def _int(v):
            try:
                return int(v)
            except (TypeError, ValueError):
                return None
        data = {
            "patient_id": pid,
            "proc_date": self.pvars["proc_date"].get().strip() or None,
            "proc_type": self.pvars["proc_type"].get() or None,
            "stent_count": _int(self.pvars["stent_count"].get()),
            "lesion_vessel_count": _int(self.pvars["lesion_vessel_count"].get()),
            "complete_revascularization": 1 if self.flag_complete.get() else 0,
            "is_emergency": 1 if self.flag_emergency.get() else 0,
            "incision_type": self.pvars["incision_type"].get() or None,
            "anticoagulation": self.pvars["anticoagulation"].get() or None,
        }
        existing = self.app.repo.get_procedure_id(pid)
        if existing:
            self.app.repo.update_procedure(existing, data)
        else:
            self.app.repo.insert_procedure(data)

    def _delete(self):
        """删除选中患者（仅无业务记录可删；有评估/处方等业务记录显式拒绝，日志留痕）。
        RBAC（P3-T3）：patient:delete（治疗师/护士无权限）。"""
        if not self.app.check_perm("patient:delete"):
            messagebox.showwarning("无权限", "当前角色无删除患者权限（需医师或管理员）")
            return
        if not self.tree.selection():
            return
        pid = int(self.tree.selection()[0])
        if not messagebox.askyesno(
                "确认删除",
                f"确定删除患者 #{pid} 及其手术信息？\n"
                "（若存在评估/证型/分层/处方/随访/预警等业务记录，将拒绝删除——医疗数据保护）"):
            return
        try:
            self.app.repo.delete_patient(pid)
            _logger.warning("患者 #%s 已删除（无业务记录）", pid)
            self.refresh()
            self.saved_var.set(f"已删除 #{pid}")
        except ValueError as e:
            _logger.warning("患者 #%s 删除被拒绝（业务记录保护）: %s", pid, e)
            messagebox.showwarning("无法删除", f"{e}\n（医疗数据保护：有业务记录的患者不可删除）")
        except Exception as e:
            _logger.error("患者删除失败: %s", e)
            messagebox.showerror("删除失败", str(e))


if __name__ == "__main__":
    from ui.main import MainApp
    app = MainApp()
    app.after(1500, app.destroy)
    app.mainloop()
    print("患者管理视图启动测试通过")
