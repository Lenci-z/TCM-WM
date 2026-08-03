# -*- coding: utf-8 -*-
"""
阶段7 临床功能测试：依从性打卡 + 数据看板 + CSV 导出。
"""
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "app"))

import db  # noqa: E402
from repo import Repository  # noqa: E402


class Stage7Base(unittest.TestCase):
    """共享测试库（患者 + 评估 + 分层 + 打卡 + 预警）。"""

    @classmethod
    def setUpClass(cls):
        fd, cls.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        db.init_db(cls.db_path)
        db.import_seed(cls.db_path)
        cls.conn = db.get_conn(cls.db_path)
        cls.repo = Repository(cls.conn)
        cls.pid = cls.repo.insert_patient({
            "name": "打卡患者", "gender": "男", "birth_date": "1960-01-01",
            "contact": "13800138000", "register_date": "2026-08-01",
            "disease_category": "CAD_PCI", "status": "在组",
        })
        cls.repo.insert_assessment({
            "patient_id": cls.pid, "disease_category": "CAD_PCI",
            "assessment_type": "基线", "assess_date": "2026-08-01",
            "LVEF": 52, "six_mwd": 600,
        })
        cls.repo.insert_tcm_pattern({
            "patient_id": cls.pid, "assess_date": "2026-08-01",
            "main_pattern": "气虚血瘀", "physician_confirm": 1,
        })
        cls.repo.insert_risk_stratification({
            "patient_id": cls.pid, "disease_category": "CAD_PCI",
            "assess_date": "2026-08-01", "risk_level": "中危", "physician_confirm": 1,
        })
        cls.repo.insert_alert(cls.pid, {
            "rule_code": "ALERT-R-001", "level": "红色",
            "rule_name": "静息心率过快",
            "trigger_data": {"resting_hr": 110}, "detail": "测试预警",
        })

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()
        os.unlink(cls.db_path)


class TestAdherence(Stage7Base):
    """依从性打卡。"""

    def test_insert_and_list(self):
        lid = self.repo.insert_adherence({
            "patient_id": self.pid, "log_date": "2026-08-02",
            "task_type": "八段锦", "is_done": 1, "actual_duration": 20,
            "self_rpe": 12, "symptom_json": '["无"]', "remark": "晨练",
        })
        self.assertGreater(lid, 0)
        rows = self.repo.list_adherences(self.pid)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["task_type"], "八段锦")
        self.assertEqual(rows[0]["is_done"], 1)

    def test_stats(self):
        # 清空本类共享库的打卡数据，保证统计独立
        self.conn.execute("DELETE FROM adherence_log")
        self.conn.commit()
        self.repo.insert_adherence({
            "patient_id": self.pid, "log_date": "2026-08-02",
            "task_type": "运动", "is_done": 1, "actual_duration": 30,
        })
        self.repo.insert_adherence({
            "patient_id": self.pid, "log_date": "2026-08-03",
            "task_type": "服药", "is_done": 0,
        })
        s = self.repo.list_adherence_stats(self.pid)
        self.assertEqual(s["days"], 2)
        self.assertEqual(s["done_cnt"], 1)
        self.assertEqual(s["total_cnt"], 2)
        self.assertEqual(s["exercise_min"], 30)
        self.assertAlmostEqual(s["completion_rate"], 50.0)


class TestDashboard(Stage7Base):
    """数据看板统计。"""

    def test_stats_summary(self):
        s = self.repo.stats_summary()
        self.assertEqual(s["total_patients"], 1)
        self.assertEqual(s["in_group"], 1)
        self.assertEqual(s["risk_medium"], 1)
        self.assertEqual(s["risk_high"], 0)
        self.assertEqual(s["open_alerts"], 1)

    def test_pattern_distribution(self):
        rows = self.repo.pattern_distribution()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["main_pattern"], "气虚血瘀")
        self.assertEqual(rows[0]["cnt"], 1)

    def test_open_alerts_with_name(self):
        rows = self.repo.list_open_alerts(5)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["patient_name"], "打卡患者")
        self.assertEqual(rows[0]["level"], "红色")
        self.assertTrue(rows[0]["rule_name"])  # JOIN rule_alert 取规则名
        self.assertTrue(rows[0]["alert_date"])  # trigger_time


class TestCsvExport(Stage7Base):
    """CSV 导出。"""

    def test_export_patients(self):
        from csv_export import export_csv, patient_csv_rows
        fd, path = tempfile.mkstemp(suffix=".csv")
        os.close(fd)
        patients = self.repo.list_patients()
        headers = ["patient_id", "name", "gender", "birth_date",
                   "disease_category", "register_date", "status", "contact"]
        n = export_csv(path, headers, patient_csv_rows(patients))
        self.assertEqual(n, 1)
        content = open(path, encoding="utf-8-sig").read()
        self.assertIn("打卡患者", content)
        self.assertIn("13800138000", content)
        os.unlink(path)

    def test_export_followups(self):
        from csv_export import export_csv, followup_csv_rows
        self.repo.insert_followup({
            "patient_id": self.pid,
            "fu_type": "1周随访", "plan_date": "2026-08-08",
            "status": "待随访",
        })
        fd, path = tempfile.mkstemp(suffix=".csv")
        os.close(fd)
        rows = followup_csv_rows(self.repo.list_followups_all())
        headers = ["fu_id", "patient_id", "patient_name", "fu_type",
                   "plan_date", "actual_date", "status", "handler"]
        n = export_csv(path, headers, rows)
        self.assertEqual(n, 1)
        content = open(path, encoding="utf-8-sig").read()
        self.assertIn("打卡患者", content)
        self.assertIn("1周随访", content)
        os.unlink(path)

    def test_export_audit(self):
        from csv_export import export_csv, audit_csv_rows
        self.repo.record_audit(1, "LOGIN", "user", 1, None, None, "测试登录")
        fd, path = tempfile.mkstemp(suffix=".csv")
        os.close(fd)
        rows = audit_csv_rows(self.repo.list_audit_logs(100))
        headers = ["log_id", "username", "action_time", "action_type",
                   "table_name", "record_id", "detail"]
        n = export_csv(path, headers, rows)
        self.assertEqual(n, 1)
        content = open(path, encoding="utf-8-sig").read()
        self.assertIn("LOGIN", content)
        os.unlink(path)

    def test_csv_bom_for_excel(self):
        """UTF-8 BOM：Excel 直接打开中文不乱码。"""
        from csv_export import export_csv
        fd, path = tempfile.mkstemp(suffix=".csv")
        os.close(fd)
        export_csv(path, ["姓名"], [["张三"]])
        raw = open(path, "rb").read()
        self.assertTrue(raw.startswith(b"\xef\xbb\xbf"))  # BOM
        os.unlink(path)


if __name__ == "__main__":
    unittest.main(verbosity=2)
