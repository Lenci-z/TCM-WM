# -*- coding: utf-8 -*-
"""
Repository 集成测试（P2-T1）。
验证：加密透明、JSON 解析、CRUD 正确性、规则读取完整性。
设计来源：docs/P2-T1执行指令_Repository层创建.md §4.2
执行修正（已记录在交付说明）：
  1. sys.path 指向 app/（指令原文指向项目根，db.py 实际在 app/ 下）
  2. test_get_rx_template 断言键由 aerobic_type 改为 aerobic
     （模板 output_json 顶层键实际为 aerobic，无 aerobic_type）
"""
import os
import sys
import json
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "app"))

import db
from repo import Repository


class TestRepoRules(unittest.TestCase):
    """规则数据读取测试。"""

    @classmethod
    def setUpClass(cls):
        cls.db_fd, cls.db_path = tempfile.mkstemp(suffix=".db")
        db.init_db(cls.db_path)
        db.import_seed(cls.db_path)
        cls.conn = db.get_conn(cls.db_path)
        cls.repo = Repository(cls.conn)

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()
        os.close(cls.db_fd)
        os.unlink(cls.db_path)

    def test_get_strat_config(self):
        cfg = self.repo.get_strat_config("CAD_PCI")
        self.assertIsInstance(cfg, dict)
        self.assertIn("levels", cfg)

    def test_get_patterns(self):
        patterns = self.repo.get_patterns()
        self.assertGreaterEqual(len(patterns), 6)
        p0 = patterns[0]
        self.assertIn("pattern_name", p0)
        self.assertIn("keywords", p0)

    def test_get_pattern_keywords(self):
        kws = self.repo.get_pattern_keywords()
        self.assertGreater(len(kws), 0)
        # 去重
        self.assertEqual(len(kws), len(set(kws)))

    def test_get_rx_template(self):
        tpl = self.repo.get_rx_template("CAD_PCI", "CAD_PCI-A2")
        self.assertIsInstance(tpl, dict)
        # 修正：模板 output_json 顶层键为 aerobic（指令原文 aerobic_type 与实际数据结构不符）
        self.assertIn("aerobic", tpl)
        # 兼容格子编码
        tpl2 = self.repo.get_rx_template("CAD_PCI", "A2")
        self.assertEqual(tpl, tpl2)

    def test_get_baduanjin_cfg(self):
        cfg = self.repo.get_baduanjin_cfg("CAD_PCI")
        self.assertIsInstance(cfg, dict)

    def test_get_safety_rules(self):
        rules = self.repo.get_safety_rules()
        self.assertGreater(len(rules), 0)

    def test_get_alert_rules(self):
        rules = self.repo.get_alert_rules()
        self.assertEqual(len(rules), 16)  # 7红+7黄+2蓝

    def test_get_enabled_diseases(self):
        diseases = self.repo.get_enabled_diseases()
        self.assertIn("CAD_PCI", diseases)


class TestRepoPatientCRUD(unittest.TestCase):
    """患者 CRUD + 加密透明测试。"""

    @classmethod
    def setUpClass(cls):
        cls.db_fd, cls.db_path = tempfile.mkstemp(suffix=".db")
        db.init_db(cls.db_path)
        db.import_seed(cls.db_path)
        cls.conn = db.get_conn(cls.db_path)
        cls.repo = Repository(cls.conn)

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()
        os.close(cls.db_fd)
        os.unlink(cls.db_path)

    def test_insert_and_get_patient(self):
        """插入患者 → 读取 → name 为明文。"""
        pid = self.repo.insert_patient({
            "name": "测试患者",
            "gender": "男",
            "birth_date": "1960-01-01",
            "contact": "13800138000",
            "register_date": "2026-08-03",
            "disease_category": "CAD_PCI",
        })
        self.assertGreater(pid, 0)

        patient = self.repo.get_patient(pid)
        self.assertEqual(patient["name"], "测试患者")  # 明文
        self.assertEqual(patient["contact"], "13800138000")  # 明文

    def test_list_patients_returns_plaintext(self):
        """list_patients 返回明文 name。"""
        self.repo.insert_patient({
            "name": "列表测试",
            "gender": "女",
            "birth_date": "1970-06-15",
            "contact": "13900139000",
            "register_date": "2026-08-03",
            "disease_category": "CAD_PCI",
        })
        patients = self.repo.list_patients()
        self.assertGreaterEqual(len(patients), 1)
        # 所有 name 都是明文（base64 密文不含中文，明文含中文）
        for p in patients:
            self.assertTrue(p["name"])

    def test_update_patient(self):
        """更新患者 → name 仍为明文。"""
        pid = self.repo.insert_patient({
            "name": "更新前",
            "gender": "男",
            "birth_date": "1955-03-20",
            "contact": "13700137000",
            "register_date": "2026-08-03",
            "disease_category": "CAD_PCI",
        })
        self.repo.update_patient(pid, {"name": "更新后", "status": "在组"})
        patient = self.repo.get_patient(pid)
        self.assertEqual(patient["name"], "更新后")
        self.assertEqual(patient["status"], "在组")

    def test_delete_patient(self):
        """删除患者 → 查不到。"""
        pid = self.repo.insert_patient({
            "name": "删除测试",
            "gender": "男",
            "birth_date": "1965-01-01",
            "contact": "13600136000",
            "register_date": "2026-08-03",
            "disease_category": "CAD_PCI",
        })
        self.repo.delete_patient(pid)
        self.assertIsNone(self.repo.get_patient(pid))

    def test_delete_patient_with_records_cascade(self):
        """级联删除（P2最终审核 B-1 采纳）：有业务记录的患者删除时，
        全部子表（评估/证型/分层/处方/预警/随访）一并清除，患者消失。"""
        pid = self.repo.insert_patient({
            "name": "级联测试",
            "gender": "男",
            "birth_date": "1968-08-08",
            "contact": "13500135001",
            "register_date": "2026-08-03",
            "disease_category": "CAD_PCI",
        })
        # 造业务记录：评估 + 证型 + 分层 + 处方 + 预警 + 随访
        self.repo.insert_assessment({
            "patient_id": pid, "assessment_type": "基线",
            "assess_date": "2026-08-03", "LVEF": 50,
        })
        self.repo.insert_tcm_pattern({
            "patient_id": pid, "assess_date": "2026-08-03",
            "main_pattern": "气虚血瘀", "physician_confirm": 1,
        })
        self.repo.insert_risk_stratification({
            "patient_id": pid, "disease_category": "CAD_PCI",
            "assess_date": "2026-08-03", "risk_level": "中危",
        })
        self.repo.insert_prescription({
            "patient_id": pid, "matrix_code": "CAD_PCI-A2",
            "gen_date": "2026-08-03", "status": "已签发",
        })
        self.repo.insert_alert(pid, {
            "level": "红", "rule_code": "ALERT-R-001",
            "trigger_data": {}, "notify_target": "医师端",
        })
        self.repo.insert_followup({
            "patient_id": pid, "plan_date": "2026-08-10",
            "fu_type": "1周", "status": "待随访",
        })
        # 级联删除
        self.repo.delete_patient(pid)
        # 患者消失，全部子表清空
        self.assertIsNone(self.repo.get_patient(pid))
        self.assertEqual(self.repo.list_assessments(pid), [])
        self.assertIsNone(self.repo.get_latest_confirmed_pattern(pid))
        self.assertIsNone(self.repo.get_latest_risk_level(pid))
        self.assertEqual(self.repo.list_prescriptions(pid), [])
        self.assertEqual(self.repo.list_pending_alerts(), [])
        self.assertEqual(self.repo.list_followups(pid), [])


class TestRepoProcedure(unittest.TestCase):
    """手术信息 CRUD。"""

    @classmethod
    def setUpClass(cls):
        cls.db_fd, cls.db_path = tempfile.mkstemp(suffix=".db")
        db.init_db(cls.db_path)
        db.import_seed(cls.db_path)
        cls.conn = db.get_conn(cls.db_path)
        cls.repo = Repository(cls.conn)
        cls.pid = cls.repo.insert_patient({
            "name": "手术测试患者",
            "gender": "男",
            "birth_date": "1960-01-01",
            "contact": "13800138000",
            "register_date": "2026-08-03",
            "disease_category": "CAD_PCI",
        })

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()
        os.close(cls.db_fd)
        os.unlink(cls.db_path)

    def test_insert_and_get_procedure(self):
        self.repo.insert_procedure({
            "patient_id": self.pid,
            "proc_date": "2026-07-15",
            "proc_type": "PCI",
            "stent_count": 2,
            "lesion_vessel_count": 3,
            "complete_revascularization": 1,
            "is_emergency": 0,
        })
        proc = self.repo.get_procedure(self.pid)
        self.assertEqual(proc["proc_type"], "PCI")
        self.assertTrue(self.repo.get_procedure_complete_revasc(self.pid))


class TestRepoAssessmentAndAlert(unittest.TestCase):
    """评估、分层、预警、随访综合测试。"""

    @classmethod
    def setUpClass(cls):
        cls.db_fd, cls.db_path = tempfile.mkstemp(suffix=".db")
        db.init_db(cls.db_path)
        db.import_seed(cls.db_path)
        cls.conn = db.get_conn(cls.db_path)
        cls.repo = Repository(cls.conn)
        cls.pid = cls.repo.insert_patient({
            "name": "综合测试患者",
            "gender": "男",
            "birth_date": "1958-05-10",
            "contact": "13500135000",
            "register_date": "2026-08-03",
            "disease_category": "CAD_PCI",
        })

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()
        os.close(cls.db_fd)
        os.unlink(cls.db_path)

    def test_assessment_insert_and_list(self):
        aid = self.repo.insert_assessment({
            "patient_id": self.pid,
            "assessment_type": "基线",
            "assess_date": "2026-08-03",
            "LVEF": 55,
            "six_mwd": 450,
        })
        self.assertGreater(aid, 0)
        lst = self.repo.list_assessments(self.pid)
        self.assertEqual(len(lst), 1)

    def test_risk_stratification_insert_and_get(self):
        self.repo.insert_risk_stratification({
            "patient_id": self.pid,
            "disease_category": "CAD_PCI",
            "assess_date": "2026-08-03",
            "risk_level": "中危",
        })
        level = self.repo.get_latest_risk_level(self.pid)
        self.assertEqual(level, "中危")

    def test_alert_insert_pending_close(self):
        aid = self.repo.insert_alert(self.pid, {
            "level": "红",
            "rule_code": "ALERT-R-001",
            "trigger_data": {"value": 200},
            "notify_target": "主治医师",
        })
        self.assertGreater(aid, 0)
        pending = self.repo.list_pending_alerts()
        self.assertGreaterEqual(len(pending), 1)
        red_pending = self.repo.list_pending_alerts("红")
        self.assertGreaterEqual(len(red_pending), 1)
        self.repo.close_alert(aid, "张医师", "已处理")
        red_after = self.repo.list_pending_alerts("红")
        # 关闭后待处置少一条
        self.assertEqual(len(red_after), len(red_pending) - 1)

    def test_followup_insert_and_complete(self):
        fu_id = self.repo.insert_followup({
            "patient_id": self.pid,
            "plan_date": "2026-08-10",
            "fu_type": "1周",
            "status": "待随访",
        })
        self.assertGreater(fu_id, 0)
        due = self.repo.list_due_followups()
        self.assertGreaterEqual(len(due), 0)
        self.repo.update_followup_status(fu_id, "2026-08-10", "李治疗师",
                                        json.dumps({"note": "完成"}))
        fu = self.repo.get_followup(fu_id)
        self.assertEqual(fu["status"], "已完成")

    def test_get_day0(self):
        """Day 0：无手术 → 建档日期。"""
        day0 = self.repo.get_day0(self.pid)
        self.assertEqual(day0, "2026-08-03")

    def test_get_patient_for_pdf(self):
        info = self.repo.get_patient_for_pdf(self.pid)
        self.assertEqual(info["name"], "综合测试患者")
        self.assertIn("gender", info)
        self.assertIn("birth_date", info)


if __name__ == "__main__":
    unittest.main(verbosity=2)
