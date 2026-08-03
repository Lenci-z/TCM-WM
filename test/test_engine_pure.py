# -*- coding: utf-8 -*-
"""
引擎纯逻辑单元测试（P2-T5 测试拆分）：构造 dict 输入，不碰 DB。
覆盖：stratify / judge_pattern / build_prescription / check_safety / evaluate_alerts
以及内部纯函数（matrix_code / calc_target_hr / phase_adjust / progression_decision / _eval_condition）。
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "app"))

from engine.stratification import stratify, _met_capacity_from_6mwd  # noqa: E402
from engine.pattern import judge_pattern  # noqa: E402
from engine.prescription import (matrix_code, calc_target_hr, phase_adjust,  # noqa: E402
                                 progression_decision, build_prescription)
from engine.safety import check_safety  # noqa: E402
from engine.alerts import evaluate_alerts  # noqa: E402


# ---------- 构造数据（不碰 DB） ----------

STRAT_CFG = {
    "version": "0.1",
    "levels": {
        "高危": [
            {"metric": "LVEF", "op": "lt", "value": 40, "desc": "LVEF<40%"},
            {"metric": "met_capacity", "op": "lt", "value": 5, "desc": "运动能力 <5 METs"},
        ],
        "中危": [
            {"metric": "met_capacity", "op": "range", "min": 5, "max": 7,
             "desc": "运动能力 5–7 METs"},
        ],
        "低危": [
            {"metric": "met_capacity", "op": "gte", "value": 7, "desc": "运动能力 ≥7 METs"},
            {"metric": "exercise_test_clean", "op": "eq", "value": True, "desc": "运动试验无缺血"},
        ],
    },
}

PATTERNS = [
    {"pattern_name": "气虚血瘀", "keywords": ["胸闷隐痛", "乏力", "气短", "舌暗", "瘀斑"]},
    {"pattern_name": "痰浊闭阻", "keywords": ["胸闷如窒", "体胖", "痰多", "苔厚腻"]},
    {"pattern_name": "气阴两虚", "keywords": ["心悸", "口干", "五心烦热", "少苔"]},
]

TEMPLATE = {
    "baduanjin_level": "L2",
    "aerobic": {"types": ["快走"], "duration_min": 30, "frequency_per_week": 5,
                "rpe_range": [11, 13], "k_range": [0.4, 0.6]},
    "resistance": {"type": "弹力带", "sets": 2, "reps": 12, "frequency_per_week": 2, "enabled": True},
    "tcm": {"method": "益气活血", "acupoints": ["内关", "足三里"],
            "diet_notes": "低盐低脂", "diet_tags": ["控盐"], "contraindications": ["辛辣"]},
}

BDJ_CFG = {"start_mapping": {"低危": "L2", "中危": "L1", "高危": "L0"}}

SAFETY_RULES = [
    {"disease_category": "*", "pattern": "肝阳上亢", "risk_level": "*", "name": "禁高强度抗阻",
     "rule": {"level": "block", "action": "block_resistance", "detail": "避免屏气用力"}},
    {"disease_category": "CAD_PCI", "pattern": "*", "risk_level": "高危", "name": "需监护",
     "rule": {"level": "block", "action": "supervision_required", "detail": "监护下运动"}},
]

ALERT_RULES = [
    {"rule_code": "ALERT-R-002", "level": "红色", "name": "心率过快",
     "condition": {"metric": "resting_hr", "op": "gte", "value": 100},
     "applicable": {"disease_category": ["CAD_PCI"], "pattern": ["*"], "risk_level": ["*"]},
     "actions": [{"type": "notify_physician"}]},
    {"rule_code": "ALERT-B-001", "level": "蓝色", "name": "连续达标激励",
     "condition": {"metric": "streak", "op": "consecutive_met", "count": 3},
     "applicable": {"disease_category": ["*"], "pattern": ["*"], "risk_level": ["*"]},
     "actions": []},
]


class TestStratifyPure(unittest.TestCase):
    def test_high_risk_lvef(self):
        level, trig = stratify(STRAT_CFG, {"LVEF": 35})
        self.assertEqual(level, "高危")
        self.assertTrue(any(t["metric"] == "LVEF" for t in trig))

    def test_mid_risk_met(self):
        level, _ = stratify(STRAT_CFG, {"met_capacity": 6})
        self.assertEqual(level, "中危")

    def test_low_risk_met(self):
        level, _ = stratify(STRAT_CFG, {"met_capacity": 8, "exercise_test_clean": True})
        self.assertEqual(level, "低危")

    def test_6mwd_derivation(self):
        """6MWD 推算 METs 后进入分层判定。"""
        met = _met_capacity_from_6mwd(550)
        self.assertGreater(met, 5)
        level, _ = stratify(STRAT_CFG, {"six_mwd": 550})
        self.assertEqual(level, "中危")

    def test_missing_config_conservative(self):
        """参数集缺失 → 保守判高危。"""
        level, _ = stratify({}, {"LVEF": 60})
        self.assertEqual(level, "高危")

    def test_no_data_conservative(self):
        level, _ = stratify(STRAT_CFG, {})
        self.assertEqual(level, "高危")


class TestJudgePatternPure(unittest.TestCase):
    def test_qixu(self):
        main, sec, _ = judge_pattern(PATTERNS, ["胸闷隐痛", "乏力", "气短", "舌暗"])
        self.assertEqual(main, "气虚血瘀")

    def test_tanzhuo(self):
        main, _, _ = judge_pattern(PATTERNS, ["胸闷如窒", "体胖", "痰多", "苔厚腻"])
        self.assertEqual(main, "痰浊闭阻")

    def test_empty(self):
        main, sec, scores = judge_pattern(PATTERNS, [])
        self.assertIsNone(main)
        self.assertIsNone(sec)
        self.assertEqual(scores, {})

    def test_name_key_compat(self):
        """兼容 name 键（旧结构）。"""
        old = [{"name": "气虚血瘀", "keywords": ["乏力"]}]
        main, _, _ = judge_pattern(old, ["乏力"])
        self.assertEqual(main, "气虚血瘀")


class TestPrescriptionPure(unittest.TestCase):
    def test_matrix_code(self):
        self.assertEqual(matrix_code("CAD_PCI", "气虚血瘀", "低危"), "CAD_PCI-A1")
        self.assertEqual(matrix_code("CAD_PCI", "阳虚水泛", "高危"), "CAD_PCI-E3")

    def test_calc_target_hr(self):
        hr_min, hr_max = calc_target_hr(60, None, 65, False, [0.4, 0.6])
        # HRmax=155, k=0.5 → 60+0.4*95=98, 60+0.6*95=117
        self.assertEqual(hr_min, 98)
        self.assertEqual(hr_max, 117)

    def test_calc_target_hr_beta_blocker(self):
        hr_min, hr_max = calc_target_hr(60, None, None, True, [0.4, 0.6])
        self.assertEqual((hr_min, hr_max), (80, 90))

    def test_phase_adjust_phase_i(self):
        out = phase_adjust(TEMPLATE, "I", "高危", BDJ_CFG)
        self.assertEqual(out["aerobic"]["rpe_range"], [9, 11])
        self.assertEqual(out["baduanjin_level"], "L0")  # 高危 → 起始 L0

    def test_build_prescription(self):
        rx = build_prescription(TEMPLATE, BDJ_CFG, "CAD_PCI", "气虚血瘀", "低危",
                                phase="II", week_no=2, resting_hr=60, age=65)
        self.assertEqual(rx["matrix_code"], "CAD_PCI-A1")
        self.assertEqual(rx["status"], "草稿")
        self.assertEqual(rx["baduanjin_level"], "L2")

    def test_progression_upgrade(self):
        dec = progression_decision({
            "completion_rate_2w": 85, "avg_rpe": 12, "target_rpe_max": 13,
            "red_alert": False, "yellow_alert": False, "new_symptom": False,
        })
        self.assertEqual(dec["decision"], "upgrade")

    def test_progression_downgrade(self):
        dec = progression_decision({
            "completion_rate_2w": 90, "avg_rpe": 15, "target_rpe_max": 13,
            "red_alert": True, "yellow_alert": False, "new_symptom": False,
        })
        self.assertEqual(dec["decision"], "downgrade")


class TestSafetyPure(unittest.TestCase):
    def test_block_resistance(self):
        s = check_safety(SAFETY_RULES, {}, "CAD_PCI", "肝阳上亢", "低危")
        actions = {b["action"] for b in s["blocked"]}
        self.assertIn("block_resistance", actions)

    def test_supervision_high_risk(self):
        s = check_safety(SAFETY_RULES, {}, "CAD_PCI", "气虚血瘀", "高危")
        actions = {b["action"] for b in s["blocked"]}
        self.assertIn("supervision_required", actions)

    def test_disease_specific(self):
        s = check_safety([], {"items": [{"name": "股动脉保护", "rule": "避免髋关节过度屈曲",
                                          "window": "术后24-72h", "level": "warning"}]},
                         "CAD_PCI", "气虚血瘀", "低危")
        self.assertEqual(len(s["warnings"]), 1)
        self.assertEqual(s["blocked"], [])


class TestAlertsPure(unittest.TestCase):
    def test_hr_trigger(self):
        trig = evaluate_alerts(ALERT_RULES, "CAD_PCI", "气虚血瘀", "中危", {"resting_hr": 105})
        codes = [t["rule_code"] for t in trig]
        self.assertIn("ALERT-R-002", codes)

    def test_streak_trigger(self):
        trig = evaluate_alerts(ALERT_RULES, "CAD_PCI", "气虚血瘀", "中危", {"streak": 3})
        codes = [t["rule_code"] for t in trig]
        self.assertIn("ALERT-B-001", codes)

    def test_no_trigger(self):
        trig = evaluate_alerts(ALERT_RULES, "CAD_PCI", "气虚血瘀", "中危", {"resting_hr": 72, "streak": 0})
        self.assertEqual(trig, [])

    def test_applicable_filter(self):
        """适用范围过滤：病种不符不触发。"""
        trig = evaluate_alerts(ALERT_RULES, "CAD_CABG", "气虚血瘀", "中危", {"resting_hr": 105})
        self.assertEqual(trig, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
