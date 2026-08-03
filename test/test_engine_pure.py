# -*- coding: utf-8 -*-
"""
引擎纯逻辑单元测试（P2-T5 测试拆分）：构造 dict 输入，不碰 DB。
覆盖：stratify / judge_pattern / build_prescription / check_safety / evaluate_alerts
以及内部纯函数（matrix_code / calc_target_hr / phase_adjust / progression_decision / _eval_condition）。
"""
import json
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


class TestMatrixBoundary(unittest.TestCase):
    """18 格矩阵（6 证型 × 3 分层）边界遍历（并行第一批线⑤-1，纯逻辑不碰 DB）。"""

    PATTERNS_18 = ["气虚血瘀", "痰浊闭阻", "气阴两虚", "心血瘀阻", "阳虚水泛", "肝阳上亢"]
    RISKS_18 = ["低危", "中危", "高危"]

    def test_matrix_code_all_18_combinations(self):
        """6 证型 × 3 分层 → 18 个合法 matrix_code（CAD_PCI-A1 ... CAD_PCI-F3）。"""
        codes = []
        for pat in self.PATTERNS_18:
            for risk in self.RISKS_18:
                code = matrix_code("CAD_PCI", pat, risk)
                self.assertRegex(code, r"^CAD_PCI-[A-F][1-3]$")
                codes.append(code)
        self.assertEqual(len(codes), 18)
        self.assertEqual(len(set(codes)), 18, "18 格编码不应有重复")

    def test_matrix_code_unknown_pattern_raises(self):
        with self.assertRaises(ValueError):
            matrix_code("CAD_PCI", "不存在的证型", "低危")

    def test_matrix_code_unknown_risk_raises(self):
        with self.assertRaises(ValueError):
            matrix_code("CAD_PCI", "气虚血瘀", "超危")

    def test_build_prescription_all_templates_ok(self):
        """构造 18 个最小 template dict，每个过 build_prescription 不抛异常且含必填键。"""
        for pat in self.PATTERNS_18:
            for risk in self.RISKS_18:
                tpl = json.loads(json.dumps(TEMPLATE))  # 深拷贝
                # 按分层映射起始八段锦级别：低危 L2 / 中危 L1 / 高危 L0
                tpl["baduanjin_level"] = {"低危": "L2", "中危": "L1", "高危": "L0"}[risk]
                rx = build_prescription(tpl, BDJ_CFG, "CAD_PCI", pat, risk,
                                        phase="II", week_no=2, resting_hr=60, age=65)
                expected_code = matrix_code("CAD_PCI", pat, risk)
                self.assertEqual(rx["matrix_code"], expected_code)
                for key in ("baduanjin_level", "aerobic_type", "aerobic_duration",
                            "aerobic_freq", "rpe_min", "rpe_max", "hr_min", "hr_max",
                            "resistance_json", "tcm_json", "nutrition_json",
                            "risk_factor_json", "status"):
                    self.assertIn(key, rx)
                self.assertEqual(rx["status"], "草稿")
                self.assertEqual(rx["baduanjin_level"], tpl["baduanjin_level"])

    def test_build_prescription_phase_i_high_risk(self):
        """边界：I 期高危 → 起始 L0 + RPE 9-11（阶段适配）。"""
        tpl = json.loads(json.dumps(TEMPLATE))
        rx = build_prescription(tpl, BDJ_CFG, "CAD_PCI", "阳虚水泛", "高危",
                                phase="I", week_no=1, resting_hr=60, age=70)
        self.assertEqual(rx["baduanjin_level"], "L0")
        self.assertEqual((rx["rpe_min"], rx["rpe_max"]), (9, 11))


if __name__ == "__main__":
    unittest.main(verbosity=2)
