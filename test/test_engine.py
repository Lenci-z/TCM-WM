# -*- coding: utf-8 -*-
"""
规则引擎回归测试（4.2 回归测试之引擎部分）
独立测试库 data/test_rehab.db，不污染主库。0 FAIL 硬门槛。
运行：python -m unittest test.test_engine -v
"""
import os
import sys
import json
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "app"))

TEST_DB = os.path.join(ROOT, "data", "test_rehab.db")

from db import init_db, get_conn, import_seed  # noqa: E402
from engine.stratification import stratify  # noqa: E402
from engine.pattern import judge_pattern  # noqa: E402
from engine.prescription import (matrix_code, build_prescription,  # noqa: E402
                                 progression_decision)
from engine.safety import check_safety, apply_safety  # noqa: E402
from engine.alerts import evaluate_alerts, close_alert  # noqa: E402
from repo import Repository  # noqa: E402


class EngineTestBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.path.exists(TEST_DB):
            os.remove(TEST_DB)
        init_db(TEST_DB)
        import_seed(TEST_DB)
        cls.conn = get_conn(TEST_DB)
        cls.repo = Repository(cls.conn)
        cls.strat_cfg = cls.repo.get_strat_config("CAD_PCI")
        cls.patterns = cls.repo.get_patterns()

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()
        if os.path.exists(TEST_DB):
            os.remove(TEST_DB)


class TestStratification(EngineTestBase):
    def test_high_risk(self):
        level, trig = stratify(self.strat_cfg, {"LVEF": 35, "complete_revascularization": 0})
        self.assertEqual(level, "高危")
        self.assertTrue(trig)

    def test_mid_risk(self):
        level, _ = stratify(self.strat_cfg,
                            {"LVEF": 45, "met_capacity": 6,
                             "revascularization_status": "incomplete_no_ischemia"})
        self.assertEqual(level, "中危")

    def test_low_risk(self):
        level, _ = stratify(self.strat_cfg,
                            {"LVEF": 55, "complete_revascularization": True,
                             "exercise_test_clean": True, "met_capacity": 8})
        self.assertEqual(level, "低危")

    def test_6mwd_inference(self):
        """300m → METs≈3.06 <5 → 高危（6MWD 推算链路）。"""
        level, _ = stratify(self.strat_cfg, {"LVEF": 50, "six_mwd": 300})
        self.assertEqual(level, "高危")

    def test_missing_data_conservative(self):
        level, _ = stratify(self.strat_cfg, {})
        self.assertEqual(level, "高危")  # 缺数据保守判高危


class TestPattern(EngineTestBase):
    def test_qixu_xy(self):
        main, sec, _ = judge_pattern(self.patterns,
            ["胸闷隐痛", "乏力", "气短", "动则加重", "舌暗", "瘀斑", "脉细", "脉涩"])
        self.assertEqual(main, "气虚血瘀")

    def test_tanzhuo(self):
        main, _, _ = judge_pattern(self.patterns, ["胸闷如窒", "体胖", "痰多", "苔厚腻", "脉滑"])
        self.assertEqual(main, "痰浊闭阻")

    def test_qiyin(self):
        main, _, _ = judge_pattern(self.patterns,
            ["心悸", "乏力", "口干", "五心烦热", "舌红", "少苔", "脉细", "脉数"])
        self.assertEqual(main, "气阴两虚")

    def test_ganyang(self):
        main, _, _ = judge_pattern(self.patterns, ["头晕", "头痛", "烦躁", "易怒", "面红", "舌红", "脉弦"])
        self.assertEqual(main, "肝阳上亢")

    def test_empty(self):
        main, sec, _ = judge_pattern(self.patterns, [])
        self.assertIsNone(main)
        self.assertIsNone(sec)


class TestMatrixCode(EngineTestBase):
    def test_codes(self):
        self.assertEqual(matrix_code("CAD_PCI", "气虚血瘀", "中危"), "CAD_PCI-A2")
        self.assertEqual(matrix_code("CAD_PCI", "肝阳上亢", "低危"), "CAD_PCI-F1")
        self.assertEqual(matrix_code("CAD_PCI", "阳虚水泛", "高危"), "CAD_PCI-E3")


class TestPrescription(EngineTestBase):
    def test_rx_ii(self):
        rx = build_prescription(self.conn, "CAD_PCI", "气虚血瘀", "中危",
                                phase="II", week_no=3, resting_hr=60, age=65,
                                on_beta_blocker=False)
        self.assertEqual(rx["matrix_code"], "CAD_PCI-A2")
        self.assertEqual(rx["baduanjin_level"], "L1")
        self.assertEqual(rx["rpe_min"], 11)
        self.assertEqual(rx["rpe_max"], 13)
        # HR 区间手算复核：HRmax=155, k 0.5~0.6 → [108, 117]
        self.assertEqual(rx["hr_min"], 108)
        self.assertEqual(rx["hr_max"], 117)
        self.assertEqual(rx["status"], "草稿")

    def test_rx_phase_i_beta(self):
        rx = build_prescription(self.conn, "CAD_PCI", "阳虚水泛", "高危",
                                phase="I", week_no=1, resting_hr=70, age=70,
                                on_beta_blocker=True)
        self.assertEqual(rx["phase"], "I")
        self.assertEqual(rx["baduanjin_level"], "L0")
        self.assertEqual(rx["rpe_min"], 9)
        self.assertEqual(rx["hr_min"], 90)   # 静息+20
        self.assertEqual(rx["hr_max"], 100)  # 静息+30

    def test_rx_phase_iii(self):
        rx = build_prescription(self.conn, "CAD_PCI", "肝阳上亢", "低危",
                                phase="III", week_no=12, resting_hr=65, age=60)
        self.assertEqual(rx["phase"], "III")
        self.assertEqual(rx["baduanjin_level"], "L3")  # L2 升一档
        self.assertEqual(rx["aerobic_duration"], 40)   # 30+10 上限 40

    def test_progression_upgrade(self):
        d = progression_decision({"completion_rate_2w": 85, "avg_rpe": 12,
                                  "target_rpe_max": 14})
        self.assertEqual(d["decision"], "upgrade")

    def test_progression_downgrade(self):
        d = progression_decision({"completion_rate_2w": 90, "avg_rpe": 15,
                                  "target_rpe_max": 14, "rpe_ge15_count": True})
        self.assertEqual(d["decision"], "downgrade")

    def test_progression_maintain(self):
        d = progression_decision({"completion_rate_2w": 70, "avg_rpe": 13,
                                  "target_rpe_max": 14})
        self.assertEqual(d["decision"], "maintain")


class TestSafety(EngineTestBase):
    def test_ganyang_block(self):
        s = check_safety(self.conn, "CAD_PCI", "肝阳上亢", "低危")
        actions = {b["action"] for b in s["blocked"]}
        self.assertIn("block_resistance", actions)

    def test_apply_disables_resistance(self):
        rx = build_prescription(self.conn, "CAD_PCI", "肝阳上亢", "低危", phase="II", week_no=1)
        s = check_safety(self.conn, "CAD_PCI", "肝阳上亢", "低危")
        rx = apply_safety(rx, s)
        res = json.loads(rx["resistance_json"])
        self.assertFalse(res["enabled"])

    def test_cabg_window_rule_present(self):
        s = check_safety(self.conn, "CAD_CABG", "气虚血瘀", "低危")
        names = [b["name"] for b in s["blocked"]]
        self.assertTrue(any("胸骨" in n for n in names))


class TestAlerts(EngineTestBase):
    def test_red_hr(self):
        trig = evaluate_alerts(self.conn, "CAD_PCI", "气虚血瘀", "中危", {"resting_hr": 105})
        codes = [t["rule_code"] for t in trig]
        self.assertIn("ALERT-R-002", codes)

    def test_yellow_phq(self):
        trig = evaluate_alerts(self.conn, "CAD_PCI", "气虚血瘀", "中危", {"phq9_or_gad7": 12})
        codes = [t["rule_code"] for t in trig]
        self.assertIn("ALERT-Y-005", codes)

    def test_blue_followup(self):
        trig = evaluate_alerts(self.conn, "CAD_PCI", "气虚血瘀", "中危", {"followup_due": 2})
        codes = [t["rule_code"] for t in trig]
        self.assertIn("ALERT-B-002", codes)

    def test_no_trigger_normal(self):
        trig = evaluate_alerts(self.conn, "CAD_PCI", "气虚血瘀", "中危",
                               {"resting_hr": 72, "phq9_or_gad7": 6, "followup_due": 9})
        self.assertEqual(trig, [])

    def test_closure(self):
        pid = self.conn.execute(
            "INSERT INTO patient (name_enc, register_date) VALUES (?,?)",
            ("dGVzdA==", "2026-08-03")).lastrowid
        self.conn.commit()
        evaluate_alerts(self.conn, "CAD_PCI", "气虚血瘀", "中危",
                        {"resting_hr": 110}, patient_id=pid, persist=True)
        row = self.conn.execute("SELECT alert_id FROM alert WHERE patient_id=?", (pid,)).fetchone()
        self.assertIsNotNone(row)
        close_alert(self.conn, row["alert_id"], "测试医师", "处置完成")
        closed = self.conn.execute("SELECT status FROM alert WHERE alert_id=?", (row["alert_id"],)).fetchone()
        self.assertEqual(closed["status"], "已关闭")
        # 清理
        self.conn.execute("DELETE FROM alert WHERE patient_id=?", (pid,))
        self.conn.execute("DELETE FROM patient WHERE patient_id=?", (pid,))
        self.conn.commit()


if __name__ == "__main__":
    unittest.main(verbosity=2)
