# -*- coding: utf-8 -*-
"""
处方管理视图（3.4）：一键生成 → 医师调整 → 签发（不可跳过）→ 打印 PDF
依据：设计方案 v0.2 第 2.6 节（五大处方整合输出）、3.4 节（医师审核签发为必经环节）
"""
import sys
import os
import json
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db import get_conn, insert_row, update_row, decrypt_text
from engine.prescription import build_prescription, matrix_code
from engine.safety import check_safety, apply_safety


class PrescriptionView(ttk.Frame):
    """处方管理：生成/调整/签发/打印。"""

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.conn = app.conn
        self.current_pid = None
        self.current_rx = None  # 当前预览处方 dict（未保存）

        left = ttk.Frame(self)
        left.pack(side="left", fill="y", padx=(8, 4), pady=8)
        right = ttk.Frame(self)
        right.pack(side="left", fill="both", expand=True, padx=(4, 8), pady=8)

        # ---- 左侧：患者 + 历史处方 ----
        ttk.Label(left, text="选择患者", font=("微软雅黑", 11, "bold")).pack(anchor="w")
        self.patient_tree = ttk.Treeview(left, columns=("id", "name", "disease"), show="headings", height=12)
        for c, (t, w) in {"id": ("ID", 50), "name": ("姓名", 90), "disease": ("病种", 100)}.items():
            self.patient_tree.heading(c, text=t)
            self.patient_tree.column(c, width=w, anchor="center")
        self.patient_tree.pack(fill="both", expand=True)
        self.patient_tree.bind("<<TreeviewSelect>>", self._on_patient_select)

        ttk.Label(left, text="历史处方", font=("微软雅黑", 11, "bold")).pack(anchor="w", pady=(10, 2))
        self.rx_tree = ttk.Treeview(left, columns=("rid", "matrix", "phase", "status"), show="headings", height=10)
        for c, (t, w) in {"rid": ("ID", 40), "matrix": ("矩阵", 95), "phase": ("阶段", 55), "status": ("状态", 70)}.items():
            self.rx_tree.heading(c, text=t)
            self.rx_tree.column(c, width=w, anchor="center")
        self.rx_tree.pack(fill="both", expand=True)
        self.rx_tree.bind("<<TreeviewSelect>>", self._on_rx_select)

        # ---- 右侧：生成参数 ----
        param = ttk.LabelFrame(right, text="处方生成参数", padding=8)
        param.pack(fill="x", pady=4)
        self.pvars = {}
        fields = [("phase", "阶段", ["I", "II", "III"]), ("week_no", "周次", None),
                  ("resting_hr", "静息心率", None), ("age", "年龄", None)]
        for i, (key, label, values) in enumerate(fields):
            ttk.Label(param, text=label).grid(row=0, column=i * 2, sticky="e", padx=4, pady=3)
            if values:
                var = ttk.Combobox(param, values=values, state="readonly", width=8)
                var.set("II")
            else:
                var = ttk.Entry(param, width=10)
            var.grid(row=0, column=i * 2 + 1, sticky="w", padx=4, pady=3)
            self.pvars[key] = var
        self.beta_var = tk.BooleanVar()
        ttk.Checkbutton(param, text="服β受体阻滞剂", variable=self.beta_var).grid(row=0, column=8, columnspan=2, padx=8)

        row2 = ttk.Frame(right)
        row2.pack(fill="x", pady=4)
        ttk.Label(row2, text="证型").pack(side="left")
        self.pattern_var = ttk.Combobox(row2, state="readonly", width=12)
        self.pattern_var.pack(side="left", padx=4)
        ttk.Label(row2, text="危险分层").pack(side="left")
        self.risk_var = ttk.Combobox(row2, values=["低危", "中危", "高危"], state="readonly", width=8)
        self.risk_var.pack(side="left", padx=4)
        ttk.Button(row2, text="自动读取最新评估", command=self._auto_fill).pack(side="left", padx=8)
        ttk.Button(row2, text="一键生成处方", command=self._generate).pack(side="left", padx=8)

        # ---- 处方详情 ----
        det = ttk.LabelFrame(right, text="处方预览（五大处方整合输出）", padding=8)
        det.pack(fill="both", expand=True, pady=4)
        self.detail_text = tk.Text(det, height=16, font=("Consolas", 10), wrap="none")
        sb = ttk.Scrollbar(det, orient="vertical", command=self.detail_text.yview)
        self.detail_text.configure(yscrollcommand=sb.set)
        self.detail_text.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        # ---- 医师调整 ----
        adj = ttk.LabelFrame(right, text="医师调整（签发前可修改）", padding=8)
        adj.pack(fill="x", pady=4)
        self.avars = {}
        afields = [("baduanjin_level", "八段锦级别", ["L0", "L1", "L2", "L3", "L3+"]),
                   ("aerobic_duration", "有氧时长(min)"), ("aerobic_freq", "频次(次/周)"),
                   ("rpe_min", "RPE下限"), ("rpe_max", "RPE上限")]
        for i, (key, label, *rest) in enumerate(afields):
            ttk.Label(adj, text=label).grid(row=0, column=i * 2, sticky="e", padx=4, pady=3)
            values = rest[0] if rest else None
            if values:
                var = ttk.Combobox(adj, values=values, state="readonly", width=8)
            else:
                var = ttk.Entry(adj, width=10)
            var.grid(row=0, column=i * 2 + 1, sticky="w", padx=4, pady=3)
            self.avars[key] = var
        ttk.Button(adj, text="应用到预览", command=self._apply_adjust).grid(row=1, column=0, columnspan=10, sticky="w", padx=4, pady=4)

        # ---- 操作 ----
        ops = ttk.Frame(right)
        ops.pack(fill="x", pady=6)
        ttk.Button(ops, text="保存处方(草稿)", command=self._save_draft).pack(side="left", padx=4)
        ttk.Button(ops, text="签发处方", command=self._sign).pack(side="left", padx=4)
        ttk.Button(ops, text="打印 PDF", command=self._print_pdf).pack(side="left", padx=4)
        self.saved_var = tk.StringVar(value="")
        tk.Label(ops, textvariable=self.saved_var, fg="green").pack(side="left", padx=10)
        self.refresh()

    # ---------- 数据 ----------
    def refresh(self):
        for item in self.patient_tree.get_children():
            self.patient_tree.delete(item)
        rows = self.conn.execute(
            "SELECT patient_id, name_enc, disease_category FROM patient ORDER BY patient_id DESC"
        ).fetchall()
        for r in rows:
            self.patient_tree.insert("", "end", iid=str(r["patient_id"]), values=(
                r["patient_id"], decrypt_text(r["name_enc"]), r["disease_category"]))

    def _pattern_names(self):
        rows = self.conn.execute("SELECT pattern_name FROM rule_tcm_pattern").fetchall()
        return [r["pattern_name"] for r in rows]

    def _on_patient_select(self, event):
        sel = self.patient_tree.selection()
        if not sel:
            return
        self.current_pid = int(sel[0])
        self._load_rx_history()
        self._auto_fill()

    def _load_rx_history(self):
        for item in self.rx_tree.get_children():
            self.rx_tree.delete(item)
        rows = self.conn.execute(
            "SELECT rx_id, matrix_code, phase, status FROM prescription "
            "WHERE patient_id=? ORDER BY rx_id DESC", (self.current_pid,)
        ).fetchall()
        for r in rows:
            self.rx_tree.insert("", "end", iid=str(r["rx_id"]), values=(
                r["rx_id"], r["matrix_code"], r["phase"], r["status"]))

    def _on_rx_select(self, event):
        sel = self.rx_tree.selection()
        if not sel:
            return
        rx = self.conn.execute("SELECT * FROM prescription WHERE rx_id=?", (int(sel[0]),)).fetchone()
        if not rx:
            return
        self.current_rx = dict(rx)
        self._render_detail(dict(rx), safety=None)
        # 回填调整框
        self.avars["baduanjin_level"].set(rx["baduanjin_level"] or "")
        self.avars["aerobic_duration"].delete(0, "end")
        self.avars["aerobic_duration"].insert(0, rx["aerobic_duration"] or "")
        self.avars["aerobic_freq"].delete(0, "end")
        self.avars["aerobic_freq"].insert(0, rx["aerobic_freq"] or "")
        self.avars["rpe_min"].delete(0, "end")
        self.avars["rpe_min"].insert(0, rx["rpe_min"] or "")
        self.avars["rpe_max"].delete(0, "end")
        self.avars["rpe_max"].insert(0, rx["rpe_max"] or "")
        self.saved_var.set(f"已载入处方 #{rx['rx_id']}（状态：{rx['status']}）")

    def _auto_fill(self):
        """从最新评估自动填充证型与分层。"""
        if self.current_pid is None:
            return
        t = self.conn.execute(
            "SELECT main_pattern FROM tcm_pattern WHERE patient_id=? AND physician_confirm=1 "
            "ORDER BY assess_date DESC LIMIT 1", (self.current_pid,)
        ).fetchone()
        r = self.conn.execute(
            "SELECT risk_level FROM risk_stratification WHERE patient_id=? "
            "ORDER BY assess_date DESC LIMIT 1", (self.current_pid,)
        ).fetchone()
        self.pattern_var["values"] = self._pattern_names()
        self.pattern_var.set(t["main_pattern"] if t else "")
        self.risk_var.set(r["risk_level"] if r else "低危")

    # ---------- 生成 ----------
    def _generate(self):
        if self.current_pid is None:
            messagebox.showwarning("提示", "请先在左侧选择患者")
            return
        pattern = self.pattern_var.get()
        risk = self.risk_var.get()
        if not pattern or not risk:
            messagebox.showwarning("提示", "请选择证型与危险分层（可点『自动读取最新评估』）")
            return
        try:
            rx = build_prescription(
                self.conn, "CAD_PCI", pattern, risk,
                phase=self.pvars["phase"].get() or "II",
                week_no=_int(self.pvars["week_no"].get(), 1),
                resting_hr=_float(self.pvars["resting_hr"].get()),
                age=_int(self.pvars["age"].get()),
                on_beta_blocker=self.beta_var.get(),
            )
            safety = check_safety(self.conn, "CAD_PCI", pattern, risk)
            rx = apply_safety(rx, safety)
            rx["patient_id"] = self.current_pid
            self.current_rx = rx
            self._render_detail(rx, safety)
            self._fill_adjust(rx)
            self.saved_var.set("已生成（草稿预览）——请审核调整后保存签发")
        except Exception as e:
            messagebox.showerror("生成失败", str(e))

    def _fill_adjust(self, rx):
        self.avars["baduanjin_level"].set(rx["baduanjin_level"] or "")
        for k in ("aerobic_duration", "aerobic_freq", "rpe_min", "rpe_max"):
            v = self.avars[k]
            if isinstance(v, ttk.Combobox):
                v.set(rx.get(k, ""))
            else:
                v.delete(0, "end")
                v.insert(0, rx.get(k, "") if rx.get(k) is not None else "")

    def _apply_adjust(self):
        """医师调整 → 更新预览。"""
        if not self.current_rx:
            messagebox.showwarning("提示", "请先生成处方")
            return
        rx = self.current_rx
        rx["baduanjin_level"] = self.avars["baduanjin_level"].get() or rx["baduanjin_level"]
        for k in ("aerobic_duration", "aerobic_freq", "rpe_min", "rpe_max"):
            v = _int(self.avars[k].get())
            if v is not None:
                rx[k] = v
        self._render_detail(rx, None)
        self.saved_var.set("已应用医师调整（未保存）")

    def _render_detail(self, rx, safety):
        """五大处方整合输出（文档 2.6 样式）。"""
        p = self.conn.execute("SELECT name_enc FROM patient WHERE patient_id=?", (rx["patient_id"],)).fetchone()
        name = decrypt_text(p["name_enc"]) if p else ""
        tcm = json.loads(rx.get("tcm_json") or "{}")
        res = json.loads(rx.get("resistance_json") or "{}")
        nutr = json.loads(rx.get("nutrition_json") or "{}")
        rf = json.loads(rx.get("risk_factor_json") or "{}")
        hr_txt = f"{rx.get('hr_min')}–{rx.get('hr_max')} 次/分" if rx.get("hr_min") else "以 RPE 为准（服β阻滞剂）"
        lines = []
        lines.append(f"患者：{name}（#{rx['patient_id']}）  编号：CR-2026-{str(rx.get('rx_id') or '____'):>04}")
        lines.append(f"分层：{rx.get('matrix_code')}  阶段：{'I期' if rx.get('phase')=='I' else 'II期' if rx.get('phase')=='II' else 'III期'} 第{rx.get('week_no')}周")
        lines.append("─" * 60)
        lines.append("① 运动处方")
        lines.append(f"   八段锦 {rx.get('baduanjin_level')} → 按级别完成")
        lines.append(f"   有氧 {rx.get('aerobic_type')} {rx.get('aerobic_duration')}分钟 × {rx.get('aerobic_freq')}次/周")
        lines.append(f"   目标 RPE {rx.get('rpe_min')}–{rx.get('rpe_max')}；心率 {hr_txt}")
        res_txt = "已禁用（禁忌命中）" if not res.get("enabled", True) else (
            f"{res.get('type')} {res.get('sets')}组×{res.get('reps')}次 × {res.get('frequency_per_week')}次/周")
        lines.append(f"   抗阻：{res_txt}")
        lines.append("② 中医处方（中医师签署）")
        lines.append(f"   {tcm.get('method', '')}")
        lines.append(f"   穴位：{'、'.join(tcm.get('acupoints', []))}")
        lines.append(f"   食疗：{tcm.get('diet_notes', '')}")
        lines.append("③ 营养处方")
        lines.append(f"   膳食建议：{nutr.get('diet_notes', '')}；忌：{'、'.join(tcm.get('contraindications', []))}")
        lines.append("④ 心理处方")
        a = self.conn.execute("SELECT PHQ9 FROM assessment WHERE patient_id=? ORDER BY assess_date DESC LIMIT 1",
                              (rx["patient_id"],)).fetchone()
        phq = a["PHQ9"] if a else None
        lines.append(f"   PHQ-9={phq if phq is not None else '—'}；正念呼吸 10分/日（按评估结果调整）")
        lines.append("⑤ 危险因素管理")
        lines.append(f"   LDL-C 目标 <{rf.get('LDL_C_target', '1.4')}；血压目标 <{rf.get('BP_target', '130/80')}")
        lines.append("─" * 60)
        if safety and safety.get("blocked"):
            lines.append("⚠ 安全禁忌（blocked）：")
            for b in safety["blocked"]:
                lines.append(f"   ⛔ {b['name']}：{b['detail']}")
        if safety and safety.get("warnings"):
            lines.append("⚠ 注意事项：")
            for w in safety["warnings"][:4]:
                lines.append(f"   · {w['name']}（{w.get('window', '')}）")
        if rx.get("status") == "已签发":
            lines.append(f"医师签名：{rx.get('physician_sign', '')}  签发日期：{rx.get('gen_date')}")
        self.detail_text.delete("1.0", "end")
        self.detail_text.insert("1.0", "\n".join(lines))

    # ---------- 保存 / 签发 / 打印 ----------
    def _save_draft(self):
        if not self.current_rx:
            messagebox.showwarning("提示", "请先生成处方")
            return
        rx = {k: v for k, v in self.current_rx.items() if k != "safety"}
        rx.setdefault("patient_id", self.current_pid)
        try:
            if rx.get("rx_id"):
                update_row(self.conn, "prescription", {k: rx[k] for k in
                         ("baduanjin_level", "aerobic_duration", "aerobic_freq", "rpe_min", "rpe_max")},
                         "rx_id=?", (rx["rx_id"],))
                rid = rx["rx_id"]
            else:
                rx["status"] = "草稿"
                rid = insert_row(self.conn, "prescription", rx)
                self.current_rx["rx_id"] = rid
            self._load_rx_history()
            self.saved_var.set(f"已保存处方 #{rid}（草稿）——需医师签发后方可打印")
        except Exception as e:
            messagebox.showerror("保存失败", str(e))

    def _sign(self):
        """签发：签名必填，不可跳过。"""
        if not self.current_rx:
            messagebox.showwarning("提示", "请先生成处方")
            return
        rid = self.current_rx.get("rx_id")
        if not rid:
            messagebox.showwarning("提示", "请先保存处方（草稿）再签发")
            return
        sign = tk.simpledialog.askstring("医师签发", "请输入医师签名（签发后处方生效）：")
        if not sign or not sign.strip():
            messagebox.showwarning("签发取消", "医师签名为必填项，不可跳过")
            return
        update_row(self.conn, "prescription",
                   {"status": "已签发", "physician_sign": sign.strip()}, "rx_id=?", (rid,))
        self.current_rx["status"] = "已签发"
        self.current_rx["physician_sign"] = sign.strip()
        self._load_rx_history()
        self._render_detail(self.current_rx, None)
        self.saved_var.set(f"处方 #{rid} 已签发（{sign}）——可打印")

    def _print_pdf(self):
        """打印：仅已签发处方。"""
        rx = self.current_rx
        if not rx:
            messagebox.showwarning("提示", "请先生成处方")
            return
        if rx.get("status") != "已签发":
            messagebox.showwarning("不可打印", "处方未签发。签发（医师签名）为必经环节，未签发不可打印。")
            return
        from engine.pdf_export import export_rx_pdf
        out = filedialog.asksaveasfilename(
            title="保存处方 PDF", defaultextension=".pdf",
            initialfile=f"处方单_{rx.get('matrix_code')}_{date.today().isoformat()}.pdf",
            filetypes=[("PDF", "*.pdf")])
        if not out:
            return
        try:
            path = export_rx_pdf(self.conn, rx, out)
            self.saved_var.set(f"已导出：{path}")
            messagebox.showinfo("导出成功", f"处方 PDF 已保存：\n{path}")
        except Exception as e:
            messagebox.showerror("导出失败", str(e))


def _int(v, default=None):
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


if __name__ == "__main__":
    from ui.main import MainApp
    app = MainApp()
    app.after(1500, app.destroy)
    app.mainloop()
    print("处方管理视图启动测试通过")
