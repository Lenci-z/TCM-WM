# -*- coding: utf-8 -*-
"""
全流程联调测试（4.1）：虚构患者全链路
建档 → 评估（分层+证型）→ 处方生成 → 安全校验 → 签发 → PDF → 随访计划 → 复评
独立测试库 data/test_rehab.db。运行：python test/test_e2e.py
"""
import os
import sys
import json
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "app"))

TEST_DB = os.path.join(ROOT, "data", "test_rehab.db")
TEST_PDF = os.path.join(ROOT, "data", "_e2e_rx.pdf")

from db import init_db, get_conn, import_seed, insert_row, encrypt_text  # noqa: E402
from engine.stratification import stratify  # noqa: E402
from engine.pattern import judge_pattern  # noqa: E402
from engine.prescription import build_prescription  # noqa: E402
from engine.safety import check_safety, apply_safety  # noqa: E402
from engine.alerts import evaluate_alerts  # noqa: E402
from engine.pdf_export import export_rx_pdf  # noqa: E402


class TestE2EFlow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.path.exists(TEST_DB):
            os.remove(TEST_DB)
        init_db(TEST_DB)
        import_seed(TEST_DB)
        cls.conn = get_conn(TEST_DB)

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()
        for p in (TEST_DB, TEST_PDF):
            if os.path.exists(p):
                os.remove(p)

    def test_full_flow(self):
        conn = self.conn

        # 1. 建档（patient + procedure）
        pid = insert_row(conn, "patient", {
            "name_enc": encrypt_text("王五"),
            "gender": "男", "birth_date": "1958-11-02",
            "contact_enc": encrypt_text("13900001111"),
            "inpatient_no": "ZY20268888", "register_date": "2026-07-28",
            "physician": "李医师", "status": "在组", "disease_category": "CAD_PCI",
        })
        insert_row(conn, "procedure", {
            "patient_id": pid, "proc_date": "2026-07-28", "proc_type": "PCI",
            "stent_count": 2, "lesion_vessel_count": 1,
            "complete_revascularization": 1, "is_emergency": 0,
            "incision_type": "经皮", "anticoagulation": "DAPT",
        })
        p = conn.execute("SELECT name_enc FROM patient WHERE patient_id=?", (pid,)).fetchone()
        self.assertEqual(p["name_enc"], encrypt_text("王五"))  # 加密存储

        # 2. 评估（基线：痰浊闭阻 + 中危）
        aid = insert_row(conn, "assessment", {
            "patient_id": pid, "disease_category": "CAD_PCI", "assessment_type": "基线",
            "assess_date": "2026-07-30", "LVEF": 46, "NT_proBNP": 780, "LDL_C": 2.1,
            "HbA1c": 6.8, "BP_sys": 136, "BP_dia": 82, "BMI": 27.5, "six_mwd": 550,
            "PHQ9": 5, "GAD7": 4, "smoking": "每日", "drinking": "偶尔",
        })
        self.assertGreater(aid, 0)
        main, sec, _ = judge_pattern(conn, ["胸闷如窒", "体胖", "痰多", "苔厚腻", "脉滑"])
        self.assertEqual(main, "痰浊闭阻")
        insert_row(conn, "tcm_pattern", {
            "patient_id": pid, "assess_date": "2026-07-30", "main_pattern": main,
            "secondary_pattern": sec, "four_diag_json": json.dumps(
                {"selected": ["胸闷如窒", "体胖", "痰多", "苔厚腻", "脉滑"]}, ensure_ascii=False),
            "judge_method": "医师", "physician_confirm": 1,
        })
        level, trig = stratify(conn, "CAD_PCI", {"LVEF": 46, "six_mwd": 550,
                                                 "complete_revascularization": True})
        self.assertEqual(level, "中危")
        insert_row(conn, "risk_stratification", {
            "patient_id": pid, "disease_category": "CAD_PCI", "assess_date": "2026-07-30",
            "risk_level": level, "param_version": "0.1",
            "trigger_json": json.dumps(trig, ensure_ascii=False), "physician_confirm": 1,
        })

        # 3. 处方生成（B2 痰浊闭阻×中危）→ 安全校验 → 签发
        rx = build_prescription(conn, "CAD_PCI", "痰浊闭阻", "中危", phase="II", week_no=2,
                                resting_hr=68, age=68, on_beta_blocker=False)
        self.assertEqual(rx["matrix_code"], "CAD_PCI-B2")
        safety = check_safety(conn, "CAD_PCI", "痰浊闭阻", "中危")
        rx = apply_safety(rx, safety)
        rx["patient_id"] = pid
        rx["status"] = "草稿"
        rx.pop("safety", None)
        rid = insert_row(conn, "prescription", rx)
        # 签发（不可跳过：签名必填）
        update = conn.execute(
            "UPDATE prescription SET status='已签发', physician_sign='李医师' WHERE rx_id=?",
            (rid,)).rowcount
        self.assertEqual(update, 1)
        signed = conn.execute(
            "SELECT status, physician_sign FROM prescription WHERE rx_id=?", (rid,)).fetchone()
        self.assertEqual(signed["status"], "已签发")
        self.assertEqual(signed["physician_sign"], "李医师")

        # 4. PDF 导出
        rx_row = dict(conn.execute("SELECT * FROM prescription WHERE rx_id=?", (rid,)).fetchone())
        export_rx_pdf(conn, rx_row, TEST_PDF)
        self.assertTrue(os.path.exists(TEST_PDF))
        self.assertGreater(os.path.getsize(TEST_PDF), 10000)

        # 5. 随访计划（手术日 07-28 起算 5 条）→ 完成 1 条
        nodes = json.loads(conn.execute(
            "SELECT followup_template_json FROM disease_config WHERE disease_category='CAD_PCI'"
        ).fetchone()["followup_template_json"])["nodes"]
        from datetime import date, timedelta
        day0 = date(2026, 7, 28)
        for node in nodes:
            conn.execute(
                "INSERT INTO follow_up (patient_id, plan_date, fu_type, status) VALUES (?,?,?,'待随访')",
                (pid, (day0 + timedelta(days=node["offset_days"])).isoformat(), node["code"]))
        conn.commit()
        fus = conn.execute("SELECT fu_type FROM follow_up WHERE patient_id=?", (pid,)).fetchall()
        self.assertEqual(len(fus), 5)
        conn.execute(
            "UPDATE follow_up SET actual_date='2026-08-04', status='已完成', handler='李医师', "
            "record_json=? WHERE fu_type='1周' AND patient_id=?",
            (json.dumps({"note": "伤口愈合良好，血压 132/80"}, ensure_ascii=False), pid))
        conn.commit()
        done = conn.execute(
            "SELECT status FROM follow_up WHERE fu_type='1周' AND patient_id=?", (pid,)).fetchone()
        self.assertEqual(done["status"], "已完成")

        # 6. 预警联动（复评数据 → 黄色预警触发并留痕）
        trig2 = evaluate_alerts(conn, "CAD_PCI", "痰浊闭阻", "中危",
                                {"completion_rate": 45.0}, patient_id=pid, persist=True)
        codes = [t["rule_code"] for t in trig2]
        self.assertIn("ALERT-Y-006", codes)
        alert = conn.execute(
            "SELECT level, status FROM alert WHERE patient_id=? ORDER BY alert_id DESC LIMIT 1",
            (pid,)).fetchone()
        self.assertEqual(alert["level"], "黄色")
        self.assertEqual(alert["status"], "待处置")

        print(f"✅ 全流程联调通过：患者#{pid} 建档→评估(B2/中危)→处方签发→PDF({os.path.getsize(TEST_PDF)}B)"
              f"→随访5条→复评→预警留痕")


if __name__ == "__main__":
    unittest.main(verbosity=2)
