# -*- coding: utf-8 -*-
"""
评估录入视图（3.3）：结构化评估全字段 + 四诊问卷（自动证型判定）+ 自动危险分层 + 舌象图片
保存联动：assessment + tcm_pattern + risk_stratification（医师确认环节）
"""
import sys
import os
import json
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from log import get_logger
from engine.pattern import judge_pattern
from engine.stratification import stratify


_logger = get_logger("view.assessment")
class AssessmentView(ttk.Frame):
    """评估录入：左侧患者选择 + 右侧评估表单（滚动）。"""

    ASSESS_TYPES = ["基线", "1周", "1月", "3月", "6月", "12月"]

    # 评估字段：key, 标签, 类型（e=entry, c=combobox）
    FIELD_GROUPS = [
        ("心功能", [("LVEF", "LVEF(%)", "e"), ("NT_proBNP", "NT-proBNP(pg/mL)", "e"),
                    ("ecg", "心电图(选查)", "e")]),
        ("代谢（全人群纳入）", [("LDL_C", "LDL-C(mmol/L)", "e"), ("HbA1c", "HbA1c(%)", "e"),
                           ("uric_acid", "尿酸(μmol/L)", "e"), ("eGFR", "eGFR", "e"),
                           ("UACR", "UACR(mg/g)", "e"), ("BMI", "BMI", "e"),
                           ("waist", "腰围(cm)", "e"), ("BP_sys", "收缩压(mmHg)", "e"),
                           ("BP_dia", "舒张压(mmHg)", "e")]),
        ("运动能力与肌力", [("six_mwd", "6MWD(m)", "e"), ("grip", "握力(kg)", "e"),
                         ("sit_stand", "30秒坐立(次)", "e")]),
        ("心理与依从性", [("PHQ9", "PHQ-9", "e"), ("GAD7", "GAD-7", "e"),
                        ("adherence_score", "Morisky依从性", "e")]),
        ("行为", [("smoking", "吸烟", "c"), ("drinking", "饮酒", "c"),
                ("diet", "膳食频率", "c"), ("activity", "活动量", "c")]),
        ("其他", [("echo", "心超(选查)", "e"), ("remark", "备注", "e")]),
    ]
    COMBO_VALUES = {
        "smoking": ["从不", "已戒烟", "偶尔", "每日"],
        "drinking": ["从不", "偶尔", "每周", "每日"],
        "diet": ["均衡", "偏油腻", "偏咸", "高糖"],
        "activity": ["久坐", "轻度", "中度", "活跃"],
    }

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.current_pid = None
        self.vars = {}
        self.tongue_var = None
        self.tcm_checks = {}
        self.saved_var = tk.StringVar(value="")
        self.main_pattern = None
        self.secondary_pattern = None

        # 左右分栏
        left = ttk.Frame(self)
        left.pack(side="left", fill="y", padx=(8, 4), pady=8)
        right = ttk.Frame(self)
        right.pack(side="left", fill="both", expand=True, padx=(4, 8), pady=8)

        # ---- 左侧：患者选择 ----
        ttk.Label(left, text="选择患者", font=("微软雅黑", 11, "bold")).pack(anchor="w")
        self.patient_tree = ttk.Treeview(left, columns=("id", "name", "disease"), show="headings", height=22)
        for c, (t, w) in {"id": ("ID", 50), "name": ("姓名", 90), "disease": ("病种", 100)}.items():
            self.patient_tree.heading(c, text=t)
            self.patient_tree.column(c, width=w, anchor="center")
        self.patient_tree.pack(fill="both", expand=True)
        self.patient_tree.bind("<<TreeviewSelect>>", self._on_patient_select)

        # 已有评估列表
        ttk.Label(left, text="历史评估", font=("微软雅黑", 11, "bold")).pack(anchor="w", pady=(10, 2))
        self.history = ttk.Treeview(left, columns=("aid", "type", "date", "risk"), show="headings", height=8)
        for c, (t, w) in {"aid": ("ID", 40), "type": ("类型", 55), "date": ("日期", 95), "risk": ("分层", 60)}.items():
            self.history.heading(c, text=t)
            self.history.column(c, width=w, anchor="center")
        self.history.pack(fill="both", expand=True)
        self.history.bind("<<TreeviewSelect>>", self._on_history_select)

        # ---- 右侧：滚动表单 ----
        canvas = tk.Canvas(right, highlightthickness=0)
        sb = ttk.Scrollbar(right, orient="vertical", command=canvas.yview)
        self.form = ttk.Frame(canvas)
        _win_id = canvas.create_window((0, 0), window=self.form, anchor="nw")
        # 滚动区域随内容高度自动扩展；表单宽度跟随画布可视宽度（防右缘裁剪）
        self.form.bind("<Configure>",
                       lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>",
                    lambda e: canvas.itemconfigure(_win_id, width=e.width))

        def _on_mousewheel(event):
            # Windows 滚轮：delta 为 ±120 的倍数 → 滚动行数
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        # 鼠标移入表单区绑定滚轮，移出解绑（不影响其他区域）
        canvas.bind("<Enter>", lambda e: canvas.bind_all("<MouseWheel>", _on_mousewheel))
        canvas.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))
        # Linux 滚轮兼容（Button-4/5）
        canvas.bind("<Button-4>", lambda e: canvas.yview_scroll(-1, "units"))
        canvas.bind("<Button-5>", lambda e: canvas.yview_scroll(1, "units"))

        canvas.configure(yscrollcommand=sb.set)
        canvas.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        self._build_form()
        self.refresh()

    # ---------- 表单 ----------
    def _build_form(self):
        # 评估头
        head = ttk.LabelFrame(self.form, text="评估头", padding=8)
        head.pack(fill="x", pady=4)
        self.head_var = {}
        ttk.Label(head, text="评估类型").grid(row=0, column=0, sticky="e", padx=4)
        self.head_var["type"] = ttk.Combobox(head, values=self.ASSESS_TYPES, state="readonly", width=12)
        self.head_var["type"].grid(row=0, column=1, sticky="w", padx=4)
        ttk.Label(head, text="评估日期").grid(row=0, column=2, sticky="e", padx=4)
        self.head_var["date"] = ttk.Entry(head, width=14)
        self.head_var["date"].grid(row=0, column=3, sticky="w", padx=4)
        self.head_var["date"].insert(0, date.today().isoformat())
        self.head_var["type"].set("基线")
        tk.Label(head, textvariable=self.saved_var, fg="green").grid(row=0, column=4, padx=8)

        # 各分组字段
        for group, fields in self.FIELD_GROUPS:
            frm = ttk.LabelFrame(self.form, text=group, padding=8)
            frm.pack(fill="x", pady=4)
            for i, (key, label, typ) in enumerate(fields):
                r, c = divmod(i, 3)
                ttk.Label(frm, text=label).grid(row=r, column=c * 2, sticky="e", padx=4, pady=3)
                if typ == "c":
                    var = ttk.Combobox(frm, values=self.COMBO_VALUES.get(key, []), state="readonly", width=16)
                    var.grid(row=r, column=c * 2 + 1, sticky="w", padx=4, pady=3)
                else:
                    var = ttk.Entry(frm, width=18)
                    var.grid(row=r, column=c * 2 + 1, sticky="w", padx=4, pady=3)
                self.vars[key] = var

        # 舌象图片
        tongue = ttk.LabelFrame(self.form, text="舌象图片", padding=8)
        tongue.pack(fill="x", pady=4)
        self.tongue_var = ttk.Entry(tongue, width=50)
        self.tongue_var.pack(side="left", padx=4)
        ttk.Button(tongue, text="浏览…", command=self._browse_tongue).pack(side="left")

        # 分层判定输入（选查）
        strat = ttk.LabelFrame(self.form, text="危险分层判定输入（选查，用于自动分层）", padding=8)
        strat.pack(fill="x", pady=4)
        self.svars = {}
        sfields = [
            ("exercise_test", "运动试验结论", ["未做", "无缺血", "有缺血"]),
            ("arrhythmia", "复杂室性心律失常", ["否", "是"]),
            ("bp_response", "运动中收缩压反应", ["未做", "正常", "不升或下降"]),
            ("hf_acute", "心衰急性期", ["否", "是"]),
            ("residual_ischemia", "残余缺血(未完全血运重建且有)", ["否", "是"]),
            ("mild_symptom", "中等强度下轻度症状", ["否", "是"]),
        ]
        for i, (key, label, values) in enumerate(sfields):
            r, c = divmod(i, 3)
            ttk.Label(strat, text=label).grid(row=r, column=c * 2, sticky="e", padx=4, pady=3)
            var = ttk.Combobox(strat, values=values, state="readonly", width=14)
            var.set("未做" if "未做" in values else "否")
            var.grid(row=r, column=c * 2 + 1, sticky="w", padx=4, pady=3)
            self.svars[key] = var

        # 四诊问卷（自动生成自规则库）
        tcm = ttk.LabelFrame(self.form, text="四诊结构化问卷（勾选 → 自动证型判定）", padding=8)
        tcm.pack(fill="x", pady=4)
        self._build_tcm_questionnaire(tcm)
        self.tcm_result_var = tk.StringVar(value="证型：未判定")
        tk.Label(tcm, textvariable=self.tcm_result_var, fg="#8B2F2F", font=("微软雅黑", 11, "bold")).pack(anchor="w", pady=4)
        tk.Button(tcm, text="重新判定证型", command=self._judge_tcm).pack(anchor="w")

        # 医师确认 + 保存
        confirm = ttk.LabelFrame(self.form, text="医师确认", padding=8)
        confirm.pack(fill="x", pady=4)
        self.pattern_var = ttk.Combobox(confirm, state="readonly", width=14)
        self.pattern_var.pack(side="left", padx=4)
        self.confirm_flag = tk.BooleanVar()
        ttk.Checkbutton(confirm, text="医师确认判定", variable=self.confirm_flag).pack(side="left", padx=8)
        ttk.Button(confirm, text="保存评估（含分层/证型）", command=self._save).pack(side="left", padx=8)

    def _build_tcm_questionnaire(self, parent):
        """从规则库证型 keywords 生成勾选问卷。"""
        items = self.app.repo.get_pattern_keywords()
        items = list(dict.fromkeys(items))  # 去重保序
        box = ttk.Frame(parent)
        box.pack(fill="x")
        row_frame = None
        for i, item in enumerate(items):
            if i % 4 == 0:
                row_frame = ttk.Frame(box)
                row_frame.pack(fill="x", pady=1)
            var = tk.BooleanVar()
            ttk.Checkbutton(row_frame, text=item, variable=var).pack(side="left", padx=4)
            self.tcm_checks[item] = var

    def _judge_tcm(self):
        """四诊勾选 → 证型判定。"""
        selected = [k for k, v in self.tcm_checks.items() if v.get()]
        main, sec, scores = judge_pattern(self.app.repo.get_patterns(), selected)
        self.main_pattern = main
        self.secondary_pattern = sec
        if main:
            self.tcm_result_var.set(f"证型：{main}" + (f" ｜ 兼证：{sec}" if sec else ""))
            self.pattern_var["values"] = self._pattern_names()
            self.pattern_var.set(main)
        else:
            self.tcm_result_var.set("证型：未判定（勾选四诊条目后重新判定）")
            self.pattern_var.set("")

    def _pattern_names(self):
        return self.app.repo.get_pattern_names()

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
        self._load_history()

    def _load_history(self):
        for item in self.history.get_children():
            self.history.delete(item)
        # 每个评估取最新一条分层（LEFT JOIN 子查询，避免一对多重复行）
        rows = self.app.repo.query_all(
            "SELECT a.assessment_id, a.assessment_type, a.assess_date, r.risk_level "
            "FROM assessment a "
            "LEFT JOIN risk_stratification r ON r.strat_id = ("
            "  SELECT s.strat_id FROM risk_stratification s "
            "  WHERE s.patient_id=a.patient_id AND s.assess_date=a.assess_date "
            "  ORDER BY s.strat_id DESC LIMIT 1) "
            "WHERE a.patient_id=? ORDER BY a.assess_date DESC, a.assessment_id DESC",
            (self.current_pid,)
        )
        for r in rows:
            self.history.insert("", "end", iid=str(r["assessment_id"]), values=(
                r["assessment_id"], r["assessment_type"], r["assess_date"], r["risk_level"] or ""))

    def _on_history_select(self, event):
        sel = self.history.selection()
        if not sel:
            return
        aid = int(sel[0])
        a = self.app.repo.get_assessment(aid)
        if not a:
            return
        for key, var in self.vars.items():
            if isinstance(var, ttk.Combobox):
                var.set(a[key] or "")
            else:
                var.delete(0, "end")
                var.insert(0, "" if a[key] is None else str(a[key]))
        self.head_var["type"].set(a["assessment_type"])
        self.head_var["date"].delete(0, "end")
        self.head_var["date"].insert(0, a["assess_date"])
        # 四诊与证型
        t = self.app.repo.get_tcm_pattern_by_date(self.current_pid, a["assess_date"])
        if t and t["four_diag_json"]:
            for k in self.tcm_checks:
                self.tcm_checks[k].set(False)
            four = json.loads(t["four_diag_json"])
            for k in four.get("selected", []):
                if k in self.tcm_checks:
                    self.tcm_checks[k].set(True)
            self.tcm_result_var.set(f"证型：{t['main_pattern']}" + (f" ｜ 兼证：{t['secondary_pattern']}" if t["secondary_pattern"] else ""))
            self.pattern_var.set(t["main_pattern"] or "")
            self.confirm_flag.set(bool(t["physician_confirm"]))
            if t["tongue_image_url"]:
                self.tongue_var.delete(0, "end")
                self.tongue_var.insert(0, t["tongue_image_url"])

    def _browse_tongue(self):
        path = filedialog.askopenfilename(title="选择舌象图片",
                                          filetypes=[("图片", "*.jpg *.jpeg *.png *.bmp")])
        if path:
            self.tongue_var.delete(0, "end")
            self.tongue_var.insert(0, path)

    def _disease_category(self):
        """从当前患者读取病种（第一版启用 CAD_PCI，多病种架构预留）。"""
        if self.current_pid is None:
            return "CAD_PCI"
        return self.app.repo.get_patient_disease_category(self.current_pid)

    def _get_assessment_data(self):
        data = {"patient_id": self.current_pid, "disease_category": self._disease_category(),
                "assessment_type": self.head_var["type"].get(),
                "assess_date": self.head_var["date"].get().strip() or date.today().isoformat()}
        for key, var in self.vars.items():
            if isinstance(var, ttk.Combobox):
                data[key] = var.get() or None
            else:
                v = var.get().strip()
                data[key] = _num(v) if v else None
        return data

    def _validate_inputs(self, data: dict) -> str | None:
        """数值范围校验（P3-T3）：越界返回错误信息，合法返回 None。"""
        ranges = [
            ("LVEF", 0, 100), ("six_mwd", 0, 1000), ("NT_proBNP", 0, 100000),
            ("LDL_C", 0.1, 20), ("HbA1c", 3, 20), ("PHQ9", 0, 27),
            ("GAD7", 0, 21), ("BMI", 10, 60), ("resting_hr", 30, 200),
            ("sys_bp", 60, 260), ("dia_bp", 30, 150),
        ]
        for key, lo, hi in ranges:
            v = data.get(key)
            if v is None or v == "":
                continue
            try:
                fv = float(v)
            except (TypeError, ValueError):
                return f"{key} 不是有效数值"
            if not (lo <= fv <= hi):
                return f"{key} 超出合理范围（{lo}-{hi}）"
        return None

    def _save(self):
        """保存评估。RBAC（P3-T3）：assessment:create（全员可创建）。"""
        if not self.app.check_perm("assessment:create"):
            messagebox.showwarning("无权限", "当前角色无评估录入权限")
            return
        if self.current_pid is None:
            messagebox.showwarning("提示", "请先在左侧选择患者")
            return
        data = self._get_assessment_data()
        err = self._validate_inputs(data)
        if err:
            messagebox.showwarning("输入校验", f"{err}，请修正后保存")
            return
        try:
            # 1. 保存评估
            aid = self.app.repo.insert_assessment(data)

            # 2. 证型：勾选 → 判定 → 医师可改判 → tcm_pattern
            selected = [k for k, v in self.tcm_checks.items() if v.get()]
            main = self.pattern_var.get() or (self.main_pattern if hasattr(self, "main_pattern") else None)
            if not main and selected:
                main, sec, _ = judge_pattern(self.app.repo.get_patterns(), selected)
                self.secondary_pattern = sec
            elif not main:
                main, self.secondary_pattern = None, None
            tcm_data = {
                "patient_id": self.current_pid,
                "assess_date": data["assess_date"],
                "main_pattern": main,
                "secondary_pattern": getattr(self, "secondary_pattern", None),
                "four_diag_json": json.dumps({"selected": selected}, ensure_ascii=False),
                "tongue_image_url": self.tongue_var.get().strip() or None,
                "judge_method": "医师" if self.confirm_flag.get() else "系统",
                "physician_confirm": 1 if self.confirm_flag.get() else 0,
            }
            self.app.repo.insert_tcm_pattern(tcm_data)

            # 3. 危险分层：临床指标 → stratify → risk_stratification
            dc = self._disease_category()
            clinical = self._build_clinical()
            level, triggered = stratify(self.app.repo.get_strat_config(dc), clinical)
            strat_data = {
                "patient_id": self.current_pid,
                "disease_category": dc,
                "assess_date": data["assess_date"],
                "risk_level": level,
                "param_version": "0.1",
                "trigger_json": json.dumps(triggered, ensure_ascii=False),
                "physician_confirm": 1 if self.confirm_flag.get() else 0,
            }
            self.app.repo.insert_risk_stratification(strat_data)

            self._load_history()
            self.app.set_status(f"评估已保存 #{aid} ｜ 分层：{level} ｜ 证型：{main}")
            messagebox.showinfo("保存成功", f"评估 #{aid} 已保存\n危险分层：{level}\n证型：{main or '未判定'}")
        except Exception as e:
            _logger.error("评估保存失败: %s", e)
            messagebox.showerror("保存失败", str(e))

    def _build_clinical(self) -> dict:
        """组装分层判定输入。"""
        proc_revasc = self.app.repo.get_procedure_complete_revasc(self.current_pid)
        clinical = {"LVEF": self.vars["LVEF"].get() or None,
                    "six_mwd": self.vars["six_mwd"].get() or None}
        try:
            if clinical["LVEF"] is not None:
                clinical["LVEF"] = float(clinical["LVEF"])
            if clinical["six_mwd"] is not None:
                clinical["six_mwd"] = float(clinical["six_mwd"])
        except ValueError:
            pass
        complete = bool(proc_revasc)
        clinical["complete_revascularization"] = complete
        clinical["arrhythmia"] = "complex_ventricular" if self.svars["arrhythmia"].get() == "是" else "no"
        clinical["exercise_test_clean"] = self.svars["exercise_test"].get() == "无缺血"
        clinical["exercise_symptom"] = "angina_or_st_dep" if self.svars["exercise_test"].get() == "有缺血" else "none"
        clinical["exercise_bp_response"] = "no_rise_or_fall" if self.svars["bp_response"].get() == "不升或下降" else "normal"
        clinical["heart_failure_acute"] = self.svars["hf_acute"].get() == "是"
        # 低危条件"无心衰症状"（P2-1：统一键名；急性期=否 视为无心衰症状，MVP 口径）
        clinical["heart_failure_symptom"] = self.svars["hf_acute"].get() != "是"
        clinical["residual_ischemia"] = self.svars["residual_ischemia"].get() == "是"
        clinical["mild_symptom_moderate"] = self.svars["mild_symptom"].get() == "是"
        clinical["revascularization_status"] = "incomplete_no_ischemia" if (not complete and self.svars["residual_ischemia"].get() != "是") else "complete"
        return clinical


def _num(v):
    """宽松数值转换。"""
    try:
        return float(v)
    except (ValueError, TypeError):
        return None


if __name__ == "__main__":
    from ui.main import MainApp
    app = MainApp()
    app.after(1500, app.destroy)
    app.mainloop()
    print("评估录入视图启动测试通过")
