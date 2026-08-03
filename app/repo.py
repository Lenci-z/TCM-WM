# -*- coding: utf-8 -*-
"""
中西医结合心血管康复系统 — Repository 层
集中全部数据访问，引擎不碰 conn。
加密/解密在此层透明处理（调用方传明文/收明文）。
设计来源：docs/分阶段开发设计与任务列表.md §3.4.1 + docs/P2-T1执行指令_Repository层创建.md
"""
import json

from db import encrypt_text, decrypt_text, insert_row, update_row, now_str


class Repository:
    """集中全部数据访问。引擎不碰 conn。加密/解密在此层透明处理。"""

    def __init__(self, conn=None):
        """conn 可注入（测试用），默认从 db.get_conn() 获取。"""
        if conn is None:
            from db import get_conn
            conn = get_conn()
        self.conn = conn

    # ================= 规则数据读取（只读） =================

    def get_strat_config(self, disease_category: str) -> dict:
        """读取病种危险分层参数集（解析 JSON）。
        对应旧引擎函数：stratification.load_strat_config(conn, disease_category)
        """
        row = self.conn.execute(
            "SELECT strat_threshold_json FROM disease_config WHERE disease_category=?",
            (disease_category,)
        ).fetchone()
        if not row or not row["strat_threshold_json"]:
            return {}
        return json.loads(row["strat_threshold_json"])

    def get_patterns(self) -> list:
        """读取全部启用证型特征库（已解析 features_json）。
        对应旧引擎函数：pattern.load_patterns(conn)
        """
        rows = self.conn.execute(
            "SELECT pattern_name, features_json, comorbidity_json FROM rule_tcm_pattern WHERE enabled=1"
        ).fetchall()
        result = []
        for r in rows:
            item = {"pattern_name": r["pattern_name"]}
            feat = json.loads(r["features_json"]) if r["features_json"] else {}
            item["keywords"] = feat.get("keywords", [])
            item["symptoms"] = feat.get("symptoms", [])
            item["tongue"] = feat.get("tongue", "")
            item["pulse"] = feat.get("pulse", "")
            if r["comorbidity_json"]:
                item["comorbidity"] = json.loads(r["comorbidity_json"])
            result.append(item)
        return result

    def get_pattern_names(self) -> list:
        """读取全部证型名列表。"""
        rows = self.conn.execute(
            "SELECT pattern_name FROM rule_tcm_pattern WHERE enabled=1"
        ).fetchall()
        return [r["pattern_name"] for r in rows]

    def get_pattern_keywords(self) -> list:
        """读取全部证型 keywords（去重保序，用于生成四诊问卷）。"""
        patterns = self.get_patterns()
        seen = set()
        result = []
        for p in patterns:
            for kw in p.get("keywords", []):
                if kw not in seen:
                    seen.add(kw)
                    result.append(kw)
        return result

    def get_rx_template(self, disease_category: str, matrix_code: str) -> dict:
        """调取处方模板（解析 output_json）。
        对应旧引擎函数：prescription.load_template(conn, disease_category, matrix)
        注意：兼容完整矩阵编码（CAD_PCI-A2）与格子编码（A2）——与旧 load_template 行为一致。
        """
        m = matrix_code.rsplit("-", 1)[-1]  # CAD_PCI-A2 → A2
        row = self.conn.execute(
            "SELECT output_json FROM rule_rx_template "
            "WHERE disease_category=? AND matrix_code=? AND phase='II' AND enabled=1",
            (disease_category, m)
        ).fetchone()
        if not row:
            return {}
        return json.loads(row["output_json"])

    def get_baduanjin_cfg(self, disease_category: str) -> dict:
        """读取八段锦参数集（解析 baduanjin_start_json）。
        对应旧引擎函数：prescription.load_baduanjin_cfg(conn, disease_category)
        """
        row = self.conn.execute(
            "SELECT baduanjin_start_json FROM disease_config WHERE disease_category=?",
            (disease_category,)
        ).fetchone()
        if not row or not row["baduanjin_start_json"]:
            return {}
        return json.loads(row["baduanjin_start_json"])

    def get_safety_rules(self) -> list:
        """读取全部启用禁忌规则（rule_contraindication 表）。
        对应旧引擎函数：safety.check_safety 内部的 SQL 查询
        """
        rows = self.conn.execute(
            "SELECT disease_category, pattern, risk_level, name, rule_json "
            "FROM rule_contraindication WHERE enabled=1"
        ).fetchall()
        result = []
        for r in rows:
            item = {
                "disease_category": r["disease_category"],
                "pattern": r["pattern"],
                "risk_level": r["risk_level"],
                "name": r["name"],
            }
            if r["rule_json"]:
                item["rule"] = json.loads(r["rule_json"])
            result.append(item)
        return result

    def get_disease_contraindication(self, disease_category: str) -> dict:
        """读取病种特异禁忌（disease_config.contraindication_json）。
        对应旧引擎函数：safety.check_safety 内部的 SQL 查询
        """
        row = self.conn.execute(
            "SELECT contraindication_json FROM disease_config WHERE disease_category=?",
            (disease_category,)
        ).fetchone()
        if not row or not row["contraindication_json"]:
            return {}
        return json.loads(row["contraindication_json"])

    def get_alert_rules(self) -> list:
        """读取全部启用预警规则（rule_alert 表）。
        对应旧引擎函数：alerts.load_alert_rules(conn)
        """
        rows = self.conn.execute(
            "SELECT rule_code, level, name, condition_json, applicable_json, actions_json "
            "FROM rule_alert WHERE enabled=1"
        ).fetchall()
        result = []
        for r in rows:
            item = {
                "rule_code": r["rule_code"],
                "level": r["level"],
                "name": r["name"],
                "condition": json.loads(r["condition_json"]) if r["condition_json"] else {},
                "applicable": json.loads(r["applicable_json"]) if r["applicable_json"] else {},
                "actions": json.loads(r["actions_json"]) if r["actions_json"] else {},
            }
            result.append(item)
        return result

    def get_followup_template(self, disease_category: str) -> list:
        """读取随访节点模板（disease_config.followup_template_json）。
        对应旧 GUI 代码：followup_view._followup_template 中的 SQL
        """
        row = self.conn.execute(
            "SELECT followup_template_json FROM disease_config WHERE disease_category=?",
            (disease_category,)
        ).fetchone()
        if not row or not row["followup_template_json"]:
            return []
        return json.loads(row["followup_template_json"])

    def get_enabled_diseases(self) -> list:
        """读取启用的病种列表。
        对应旧 GUI 代码：patient_view._enabled_diseases 中的 SQL
        """
        rows = self.conn.execute(
            "SELECT disease_category FROM disease_config WHERE enabled=1"
        ).fetchall()
        return [r["disease_category"] for r in rows]

    # ================= Patient CRUD（加密透明处理） =================

    def list_patients(self) -> list:
        """患者列表（解密后返回 name/contact 明文）。
        对应旧 GUI 代码：patient_view.refresh 中的 SQL + decrypt_text
        """
        rows = self.conn.execute(
            "SELECT patient_id, name_enc, gender, birth_date, contact_enc, "
            "inpatient_no, register_date, physician, status, disease_category "
            "FROM patient ORDER BY register_date DESC"
        ).fetchall()
        result = []
        for r in rows:
            result.append({
                "patient_id": r["patient_id"],
                "name": decrypt_text(r["name_enc"]),
                "gender": r["gender"],
                "birth_date": r["birth_date"],
                "contact": decrypt_text(r["contact_enc"]),
                "inpatient_no": r["inpatient_no"],
                "register_date": r["register_date"],
                "physician": r["physician"],
                "status": r["status"],
                "disease_category": r["disease_category"],
            })
        return result

    def get_patient(self, patient_id: int) -> dict | None:
        """读取单个患者（解密 name/contact）。
        对应旧 GUI 代码：patient_view._load_form 中的 SQL
        """
        row = self.conn.execute(
            "SELECT * FROM patient WHERE patient_id=?", (patient_id,)
        ).fetchone()
        if not row:
            return None
        return {
            "patient_id": row["patient_id"],
            "name": decrypt_text(row["name_enc"]),
            "gender": row["gender"],
            "birth_date": row["birth_date"],
            "contact": decrypt_text(row["contact_enc"]),
            "inpatient_no": row["inpatient_no"],
            "register_date": row["register_date"],
            "physician": row["physician"],
            "status": row["status"],
            "disease_category": row["disease_category"],
            "created_at": row["created_at"],
        }

    def get_patient_disease_category(self, patient_id: int) -> str:
        """读取患者病种（分层/处方用）。"""
        row = self.conn.execute(
            "SELECT disease_category FROM patient WHERE patient_id=?", (patient_id,)
        ).fetchone()
        return row["disease_category"] if row else "CAD_PCI"

    def get_patient_for_pdf(self, patient_id: int) -> dict:
        """读取患者信息（PDF 导出用，解密 name）。
        对应旧引擎函数：pdf_export.export_rx_pdf 内部的 SQL
        """
        row = self.conn.execute(
            "SELECT name_enc, gender, birth_date FROM patient WHERE patient_id=?",
            (patient_id,)
        ).fetchone()
        if not row:
            return {}
        return {
            "name": decrypt_text(row["name_enc"]),
            "gender": row["gender"],
            "birth_date": row["birth_date"],
        }

    def insert_patient(self, data: dict) -> int:
        """新建患者（自动加密 name/contact）。
        data 含 name/contact 明文。
        对应旧 GUI 代码：patient_view._save 中的 encrypt_text + insert_row
        """
        enc_data = dict(data)
        if "name" in enc_data:
            enc_data["name_enc"] = encrypt_text(enc_data.pop("name"))
        if "contact" in enc_data:
            enc_data["contact_enc"] = encrypt_text(enc_data.pop("contact"))
        return insert_row(self.conn, "patient", enc_data)

    def update_patient(self, patient_id: int, data: dict) -> None:
        """更新患者（自动加密 name/contact）。"""
        enc_data = dict(data)
        if "name" in enc_data:
            enc_data["name_enc"] = encrypt_text(enc_data.pop("name"))
        if "contact" in enc_data:
            enc_data["contact_enc"] = encrypt_text(enc_data.pop("contact"))
        update_row(self.conn, "patient", enc_data,
                   "patient_id=?", (patient_id,))

    def delete_patient(self, patient_id: int) -> None:
        """删除患者（含手术信息）。
        注意：patient 表无 ON DELETE CASCADE，需手动删 procedure。
        """
        self.conn.execute("DELETE FROM procedure WHERE patient_id=?", (patient_id,))
        self.conn.execute("DELETE FROM patient WHERE patient_id=?", (patient_id,))
        self.conn.commit()

    # ================= Procedure =================

    def get_procedure(self, patient_id: int) -> dict | None:
        """读取最新手术信息。"""
        row = self.conn.execute(
            "SELECT * FROM procedure WHERE patient_id=? "
            "ORDER BY procedure_id DESC LIMIT 1",
            (patient_id,)
        ).fetchone()
        return dict(row) if row else None

    def get_procedure_complete_revasc(self, patient_id: int) -> bool:
        """读取完全血运重建标志（分层用）。
        对应旧 GUI 代码：assessment_view._build_clinical 中的 SQL
        """
        row = self.conn.execute(
            "SELECT complete_revascularization FROM procedure "
            "WHERE patient_id=? ORDER BY procedure_id DESC LIMIT 1",
            (patient_id,)
        ).fetchone()
        return bool(row["complete_revascularization"]) if row else False

    def get_procedure_id(self, patient_id: int) -> int | None:
        """读取最新 procedure_id（更新用）。"""
        row = self.conn.execute(
            "SELECT procedure_id FROM procedure WHERE patient_id=? "
            "ORDER BY procedure_id DESC LIMIT 1",
            (patient_id,)
        ).fetchone()
        return row["procedure_id"] if row else None

    def insert_procedure(self, data: dict) -> int:
        """新建手术记录。"""
        return insert_row(self.conn, "procedure", data)

    def update_procedure(self, procedure_id: int, data: dict) -> None:
        """更新手术记录。"""
        update_row(self.conn, "procedure", data,
                   "procedure_id=?", (procedure_id,))

    # ================= Assessment =================

    def list_assessments(self, patient_id: int) -> list:
        """评估历史列表。"""
        rows = self.conn.execute(
            "SELECT * FROM assessment WHERE patient_id=? ORDER BY assess_date DESC",
            (patient_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    def get_assessment(self, assessment_id: int) -> dict | None:
        """读取单条评估。"""
        row = self.conn.execute(
            "SELECT * FROM assessment WHERE assessment_id=?", (assessment_id,)
        ).fetchone()
        return dict(row) if row else None

    def get_latest_phq9(self, patient_id: int) -> int | None:
        """读取最新 PHQ-9（处方预览用）。
        对应旧 GUI 代码：prescription_view._render_detail 中的 SQL
        """
        row = self.conn.execute(
            "SELECT PHQ9 FROM assessment WHERE patient_id=? "
            "ORDER BY assess_date DESC LIMIT 1",
            (patient_id,)
        ).fetchone()
        return row["PHQ9"] if row else None

    def insert_assessment(self, data: dict) -> int:
        """新建评估记录。"""
        return insert_row(self.conn, "assessment", data)

    # ================= TCM Pattern =================

    def get_latest_confirmed_pattern(self, patient_id: int) -> str | None:
        """读取最新医师确认的证型。"""
        row = self.conn.execute(
            "SELECT main_pattern FROM tcm_pattern "
            "WHERE patient_id=? AND physician_confirm=1 "
            "ORDER BY assess_date DESC LIMIT 1",
            (patient_id,)
        ).fetchone()
        return row["main_pattern"] if row else None

    def get_tcm_pattern_by_date(self, patient_id: int, assess_date: str) -> dict | None:
        """按日期读取证型记录。"""
        row = self.conn.execute(
            "SELECT * FROM tcm_pattern WHERE patient_id=? AND assess_date=?",
            (patient_id, assess_date)
        ).fetchone()
        return dict(row) if row else None

    def insert_tcm_pattern(self, data: dict) -> int:
        """新建证型记录。"""
        return insert_row(self.conn, "tcm_pattern", data)

    # ================= Risk Stratification =================

    def get_latest_risk_level(self, patient_id: int) -> str | None:
        """读取最新分层结果。"""
        row = self.conn.execute(
            "SELECT risk_level FROM risk_stratification "
            "WHERE patient_id=? ORDER BY assess_date DESC LIMIT 1",
            (patient_id,)
        ).fetchone()
        return row["risk_level"] if row else None

    def insert_risk_stratification(self, data: dict) -> int:
        """新建分层记录。"""
        return insert_row(self.conn, "risk_stratification", data)

    # ================= Prescription =================

    def list_prescriptions(self, patient_id: int) -> list:
        """处方历史列表。"""
        rows = self.conn.execute(
            "SELECT * FROM prescription WHERE patient_id=? ORDER BY gen_date DESC",
            (patient_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    def get_prescription(self, rx_id: int) -> dict | None:
        """读取单条处方。"""
        row = self.conn.execute(
            "SELECT * FROM prescription WHERE rx_id=?", (rx_id,)
        ).fetchone()
        return dict(row) if row else None

    def insert_prescription(self, data: dict) -> int:
        """新建处方（草稿）。"""
        return insert_row(self.conn, "prescription", data)

    def update_prescription(self, rx_id: int, data: dict) -> None:
        """更新处方（全字段）。"""
        update_row(self.conn, "prescription", data,
                   "rx_id=?", (rx_id,))

    # ================= Follow-up =================

    def list_followups(self, patient_id: int) -> list:
        """随访计划列表。"""
        rows = self.conn.execute(
            "SELECT * FROM follow_up WHERE patient_id=? ORDER BY plan_date",
            (patient_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    def list_due_followups(self) -> list:
        """到期提醒列表（待随访状态）。"""
        rows = self.conn.execute(
            "SELECT f.*, p.name_enc FROM follow_up f "
            "JOIN patient p ON f.patient_id=p.patient_id "
            "WHERE f.status='待随访' AND f.plan_date <= date('now','localtime') "
            "ORDER BY f.plan_date"
        ).fetchall()
        result = []
        for r in rows:
            item = dict(r)
            item["patient_name"] = decrypt_text(r["name_enc"])
            result.append(item)
        return result

    def get_followup(self, fu_id: int) -> dict | None:
        """读取单条随访。"""
        row = self.conn.execute(
            "SELECT * FROM follow_up WHERE fu_id=?", (fu_id,)
        ).fetchone()
        return dict(row) if row else None

    def list_existing_fu_types(self, patient_id: int) -> list:
        """读取已有随访类型（避免重复生成）。"""
        rows = self.conn.execute(
            "SELECT fu_type FROM follow_up WHERE patient_id=?", (patient_id,)
        ).fetchall()
        return [r["fu_type"] for r in rows]

    def insert_followup(self, data: dict) -> int:
        """新建随访计划。"""
        return insert_row(self.conn, "follow_up", data)

    def update_followup_status(self, fu_id: int, actual_date: str,
                              handler: str, record_json: str) -> None:
        """标记随访完成。"""
        self.conn.execute(
            "UPDATE follow_up SET actual_date=?, status='已完成', "
            "handler=?, record_json=? WHERE fu_id=?",
            (actual_date, handler, record_json, fu_id)
        )
        self.conn.commit()

    def get_day0(self, patient_id: int) -> str | None:
        """Day 0：手术日期优先，其次建档日期。
        对应旧 GUI 代码：followup_view._day0 中的两段 SQL
        """
        row = self.conn.execute(
            "SELECT proc_date FROM procedure WHERE patient_id=? "
            "ORDER BY procedure_id DESC LIMIT 1",
            (patient_id,)
        ).fetchone()
        if row and row["proc_date"]:
            return row["proc_date"]
        row = self.conn.execute(
            "SELECT register_date FROM patient WHERE patient_id=?",
            (patient_id,)
        ).fetchone()
        return row["register_date"] if row else None

    # ================= Alert =================

    def insert_alert(self, patient_id: int, item: dict) -> int:
        """写入预警记录（状态=待处置）。
        对应旧引擎函数：alerts.insert_alert(conn, patient_id, item)
        """
        data = {
            "patient_id": patient_id,
            "trigger_time": now_str(),
            "level": item.get("level", ""),
            "rule_code": item.get("rule_code", ""),
            "trigger_data_json": json.dumps(item.get("trigger_data", {}),
                                            ensure_ascii=False),
            "notify_target": item.get("notify_target", ""),
            "status": "待处置",
        }
        return insert_row(self.conn, "alert", data)

    def list_pending_alerts(self, level: str = None) -> list:
        """待处置预警列表。
        对应旧引擎函数：alerts.pending_alerts(conn, level)
        """
        if level:
            rows = self.conn.execute(
                "SELECT a.*, p.name_enc FROM alert a "
                "JOIN patient p ON a.patient_id=p.patient_id "
                "WHERE a.status='待处置' AND a.level=? "
                "ORDER BY a.trigger_time DESC",
                (level,)
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT a.*, p.name_enc FROM alert a "
                "JOIN patient p ON a.patient_id=p.patient_id "
                "WHERE a.status='待处置' "
                "ORDER BY a.trigger_time DESC"
            ).fetchall()
        result = []
        for r in rows:
            item = dict(r)
            item["patient_name"] = decrypt_text(r["name_enc"])
            result.append(item)
        return result

    def close_alert(self, alert_id: int, handler: str, handle_content: str) -> None:
        """处置并关闭预警（闭环留痕）。
        对应旧引擎函数：alerts.close_alert(conn, alert_id, handler, content)
        """
        self.conn.execute(
            "UPDATE alert SET handler=?, handle_time=?, "
            "handle_content=?, status='已关闭' WHERE alert_id=?",
            (handler, now_str(), handle_content, alert_id)
        )
        self.conn.commit()

    # ================= 通用 DAO =================

    def query_all(self, sql: str, params: tuple = ()) -> list:
        """通用查询（返回 dict 列表）。供 rules_view.py 使用。"""
        rows = self.conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def query_one(self, sql: str, params: tuple = ()) -> dict | None:
        """通用单行查询。"""
        row = self.conn.execute(sql, params).fetchone()
        return dict(row) if row else None

    def insert_row(self, table: str, data: dict) -> int:
        """通用插入。复用 db.insert_row。"""
        from db import insert_row as _insert_row
        return _insert_row(self.conn, table, data)

    def update_row(self, table: str, data: dict, where: str, params: tuple) -> None:
        """通用更新。复用 db.update_row。"""
        from db import update_row as _update_row
        _update_row(self.conn, table, data, where, params)
