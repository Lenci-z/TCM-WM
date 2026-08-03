# -*- coding: utf-8 -*-
"""
规则库维护视图（3.6）：可视化编辑全部规则（不藏代码里），保存即时生效（引擎读库）
覆盖：危险分层阈值（病种参数集）/ 证型特征 / 处方模板 / 八段锦分级 / 预警规则 / 禁忌规则 / 病种参数集
"""
import sys
import os
import json
import tkinter as tk
from tkinter import ttk, messagebox

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db import get_conn, update_row


class RulesView(ttk.Frame):
    """规则库维护：左侧规则类型 → 中间表格 → 右侧编辑器。"""

    # 规则类型配置：(表名, 主键, 表格列[(字段, 标题, 宽度)], JSON字段列表, 普通可编辑字段)
    RULE_TYPES = {
        "危险分层阈值（CAD_PCI参数集）": {
            "table": "disease_config", "pk": "config_id",
            "columns": [("disease_category", "病种", 100), ("enabled", "启用", 50), ("version", "版本", 60)],
            "json_fields": [("strat_threshold_json", "分层阈值JSON")],
            "plain_fields": ["name", "version", "effective_date"],
            "filter": "disease_category='CAD_PCI'",
        },
        "证型特征库": {
            "table": "rule_tcm_pattern", "pk": "pattern_id",
            "columns": [("pattern_name", "证型", 100), ("enabled", "启用", 50)],
            "json_fields": [("features_json", "特征JSON"), ("comorbidity_json", "合并JSON")],
            "plain_fields": ["pattern_name"],
        },
        "处方模板（双轴矩阵）": {
            "table": "rule_rx_template", "pk": "template_id",
            "columns": [("matrix_code", "矩阵", 60), ("pattern", "证型", 80), ("risk_level", "分层", 60),
                        ("phase", "阶段", 50), ("enabled", "启用", 50)],
            "json_fields": [("output_json", "FITT-VP模板JSON"), ("week_range_json", "周次JSON")],
            "plain_fields": ["disease_category", "matrix_code", "pattern", "risk_level", "phase"],
        },
        "八段锦分级": {
            "table": "rule_baduanjin", "pk": "level_id",
            "columns": [("level_code", "级别", 60), ("posture", "体位", 90), ("met_est", "METs", 60)],
            "json_fields": [("moves_json", "招式JSON")],
            "plain_fields": ["level_code", "posture", "met_est", "applicable"],
        },
        "预警规则": {
            "table": "rule_alert", "pk": "alert_rule_id",
            "columns": [("rule_code", "编码", 100), ("level", "级别", 55), ("name", "名称", 160),
                        ("enabled", "启用", 50)],
            "json_fields": [("condition_json", "触发条件JSON"), ("applicable_json", "适用范围JSON"),
                            ("actions_json", "处置动作JSON")],
            "plain_fields": ["rule_code", "level", "name"],
        },
        "禁忌规则": {
            "table": "rule_contraindication", "pk": "con_id",
            "columns": [("disease_category", "病种", 100), ("pattern", "证型", 80),
                        ("risk_level", "分层", 60), ("name", "名称", 160)],
            "json_fields": [("rule_json", "禁忌内容JSON")],
            "plain_fields": ["disease_category", "pattern", "risk_level", "name"],
        },
        "病种参数集": {
            "table": "disease_config", "pk": "config_id",
            "columns": [("disease_category", "病种", 110), ("name", "名称", 180), ("enabled", "启用", 50)],
            "json_fields": [("strat_threshold_json", "分层阈值"), ("contraindication_json", "运动禁忌"),
                            ("baduanjin_start_json", "八段锦起始映射"), ("followup_template_json", "随访模板"),
                            ("alert_special_json", "特有预警")],
            "plain_fields": ["disease_category", "name", "version", "effective_date"],
            "filter": None,
        },
    }

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.conn = app.conn
        self.current_type = None
        self.current_pk = None

        left = ttk.Frame(self)
        left.pack(side="left", fill="y", padx=(8, 4), pady=8)
        mid = ttk.Frame(self)
        mid.pack(side="left", fill="both", expand=True, padx=(4, 4), pady=8)
        right = ttk.Frame(self)
        right.pack(side="left", fill="y", padx=(4, 8), pady=8)

        # ---- 左：规则类型 ----
        ttk.Label(left, text="规则类型", font=("微软雅黑", 11, "bold")).pack(anchor="w")
        self.type_list = tk.Listbox(left, width=22, height=18, font=("微软雅黑", 10))
        for name in self.RULE_TYPES:
            self.type_list.insert("end", name)
        self.type_list.pack(fill="both", expand=True)
        self.type_list.bind("<<ListboxSelect>>", self._on_type_select)
        tk.Label(left, text="编辑保存后即时生效\n（引擎直接读库）", fg="#8B2F2F").pack(anchor="w", pady=6)

        # ---- 中：规则表格 ----
        self.tree = ttk.Treeview(mid, show="headings")
        self.tree.pack(fill="both", expand=True)
        sb = ttk.Scrollbar(mid, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", self._on_row_select)
        self.enable_var = tk.BooleanVar()
        ttk.Checkbutton(mid, text="仅显示启用", variable=self.enable_var,
                        command=self._load_table).pack(anchor="w", pady=2)

        # ---- 右：编辑器 ----
        editor = ttk.LabelFrame(right, text="规则编辑器", padding=8)
        editor.pack(fill="y", expand=True)
        self.plain_widgets = {}
        self.json_widgets = {}
        self.editor_container = ttk.Frame(editor)
        self.editor_container.pack(fill="both", expand=True)
        ttk.Button(editor, text="保存修改（校验JSON）", command=self._save_edit).pack(pady=6)
        self.edit_status = tk.StringVar(value="")
        tk.Label(editor, textvariable=self.edit_status, fg="green").pack(anchor="w")

        self.refresh()

    # ---------- 类型切换 ----------
    def _on_type_select(self, event):
        sel = self.type_list.curselection()
        if not sel:
            return
        self.current_type = self.type_list.get(sel[0])
        self.current_pk = None
        self._build_editor()
        self._load_table()

    def _cfg(self):
        return self.RULE_TYPES[self.current_type]

    def _load_table(self):
        if not self.current_type:
            return
        cfg = self._cfg()
        for item in self.tree.get_children():
            self.tree.delete(item)
        self.tree["columns"] = [f for f, _, _ in cfg["columns"]]
        for c, (f, t, w) in enumerate(cfg["columns"]):
            self.tree.heading(f, text=t)
            self.tree.column(f, width=w, anchor="center")
        sql = f"SELECT * FROM {cfg['table']}"
        params = []
        if cfg.get("filter"):
            sql += f" WHERE {cfg['filter']}"
            if self.enable_var.get():
                sql += " AND enabled=1"
        else:
            if self.enable_var.get():
                sql += " WHERE enabled=1"
        rows = self.conn.execute(sql, params).fetchall()
        for r in rows:
            self.tree.insert("", "end", iid=str(r[cfg["pk"]]), values=[
                r[f] if f != "enabled" else ("✓" if r[f] else "") for f, _, _ in cfg["columns"]])

    def _build_editor(self):
        """构建编辑器：普通字段 Entry + JSON 字段 Text。"""
        for w in self.editor_container.winfo_children():
            w.destroy()
        self.plain_widgets = {}
        self.json_widgets = {}
        cfg = self._cfg()
        row = 0
        for f in cfg["plain_fields"]:
            ttk.Label(self.editor_container, text=f"{f}:").grid(row=row, column=0, sticky="e", padx=3, pady=2)
            var = ttk.Entry(self.editor_container, width=26)
            var.grid(row=row, column=1, sticky="w", padx=3, pady=2)
            self.plain_widgets[f] = var
            row += 1
        for f, title in cfg["json_fields"]:
            ttk.Label(self.editor_container, text=f"{title} (JSON):").grid(row=row, column=0, columnspan=2,
                                                                          sticky="w", padx=3, pady=(6, 0))
            row += 1
            txt = tk.Text(self.editor_container, width=36, height=6, font=("Consolas", 9))
            txt.grid(row=row, column=0, columnspan=2, sticky="w", padx=3, pady=2)
            self.json_widgets[f] = txt
            row += 1
        self.edit_status.set("请选择规则行编辑")

    def _on_row_select(self, event):
        sel = self.tree.selection()
        if not sel:
            return
        self.current_pk = int(sel[0])
        cfg = self._cfg()
        row = self.conn.execute(f"SELECT * FROM {cfg['table']} WHERE {cfg['pk']}=?", (self.current_pk,)).fetchone()
        if not row:
            return
        for f, var in self.plain_widgets.items():
            if isinstance(var, ttk.Entry):
                var.delete(0, "end")
                var.insert(0, "" if row[f] is None else str(row[f]))
        for f, txt in self.json_widgets.items():
            txt.delete("1.0", "end")
            if row[f]:
                try:
                    txt.insert("1.0", json.dumps(json.loads(row[f]), ensure_ascii=False, indent=2))
                except (ValueError, TypeError):
                    txt.insert("1.0", row[f])
        self.edit_status.set(f"编辑 {cfg['table']} #{self.current_pk}")

    def _save_edit(self):
        if self.current_type is None or self.current_pk is None:
            messagebox.showwarning("提示", "请先选择规则行")
            return
        cfg = self._cfg()
        data = {}
        for f, var in self.plain_widgets.items():
            v = var.get().strip()
            data[f] = v if v else None
        for f, txt in self.json_widgets.items():
            raw = txt.get("1.0", "end").strip()
            if not raw:
                data[f] = None
                continue
            try:
                parsed = json.loads(raw)
            except ValueError as e:
                messagebox.showerror("JSON 错误", f"字段 {f} 不是合法 JSON：\n{e}")
                return
            data[f] = json.dumps(parsed, ensure_ascii=False)
        try:
            update_row(self.conn, cfg["table"], data, f"{cfg['pk']}=?", (self.current_pk,))
        except Exception as e:
            messagebox.showerror("保存失败", str(e))
            return
        self._load_table()
        self.edit_status.set("已保存，规则即时生效（重新生成处方可见变化）")
        self.app.set_status(f"规则已更新：{cfg['table']} #{self.current_pk}")

    def refresh(self):
        pass


if __name__ == "__main__":
    from ui.main import MainApp
    app = MainApp()
    app.after(1500, app.destroy)
    app.mainloop()
    print("规则库维护视图启动测试通过")
