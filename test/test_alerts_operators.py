# -*- coding: utf-8 -*-
"""
预警操作符全覆盖测试（并行第一批线⑤-2）。
覆盖 _eval_condition 已实现的全部操作符：eq / out_of_range / gte / lt /
delta_increase / delta_pct_increase / consecutive_gte / sustained_range /
any_not_met / consecutive_missed / days_before / consecutive_met。
每个操作符至少 1 个触发 + 1 个不触发用例。纯逻辑，不碰 DB。
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "app"))

from engine.alerts import evaluate_alerts  # noqa: E402


def _rule(condition, level="黄色", applicable=None):
    """构造最小预警规则 dict（结构对齐 ALERT_RULES）。"""
    return {
        "rule_code": "TEST-OP-001",
        "level": level,
        "name": "测试操作符",
        "condition": condition,
        "applicable": applicable or {"disease_category": ["*"], "pattern": ["*"],
                                     "risk_level": ["*"]},
        "actions": [],
    }


def _trig(condition, ctx):
    """执行单规则评估，返回触发列表。"""
    return evaluate_alerts([_rule(condition)], "CAD_PCI", "气虚血瘀", "中危", ctx)


class TestAlertOperators(unittest.TestCase):
    """12 操作符全覆盖：每操作符触发 + 不触发各一例。"""

    # ---------- 基础比较 ----------

    def test_eq_trigger_and_not(self):
        r = {"metric": "smoking", "op": "eq", "value": True}
        self.assertEqual(len(_trig(r, {"smoking": True})), 1)
        self.assertEqual(len(_trig(r, {"smoking": False})), 0)

    def test_out_of_range_trigger_and_not(self):
        r = {"metric": "bp_sys", "op": "out_of_range", "min": 90, "max": 180}
        self.assertEqual(len(_trig(r, {"bp_sys": 185})), 1)   # 超出上限
        self.assertEqual(len(_trig(r, {"bp_sys": 85})), 1)    # 低于下限
        self.assertEqual(len(_trig(r, {"bp_sys": 120})), 0)   # 区间内

    def test_gte_trigger_and_not(self):
        r = {"metric": "resting_hr", "op": "gte", "value": 100}
        self.assertEqual(len(_trig(r, {"resting_hr": 100})), 1)  # 等于边界触发
        self.assertEqual(len(_trig(r, {"resting_hr": 99})), 0)

    def test_lt_trigger_and_not(self):
        r = {"metric": "resting_hr", "op": "lt", "value": 50}
        self.assertEqual(len(_trig(r, {"resting_hr": 49})), 1)
        self.assertEqual(len(_trig(r, {"resting_hr": 50})), 0)   # 等于边界不触发

    # ---------- 差值/变化 ----------

    def test_delta_increase_trigger_and_not(self):
        r = {"metric": "weight", "op": "delta_increase", "threshold_kg": 2.0}
        self.assertEqual(len(_trig(r, {"weight_now": 64.5, "weight_prev": 62.0})), 1)
        self.assertEqual(len(_trig(r, {"weight_now": 63.0, "weight_prev": 62.0})), 0)
        self.assertEqual(len(_trig(r, {"weight_now": 63.0})), 0)  # 缺 prev 不触发

    def test_delta_pct_increase_trigger_and_not(self):
        r = {"metric": "weight", "op": "delta_pct_increase", "threshold_pct": 3.0}
        self.assertEqual(len(_trig(r, {"weight_now": 65.0, "weight_baseline": 62.0})), 1)  # +4.8%
        self.assertEqual(len(_trig(r, {"weight_now": 63.0, "weight_baseline": 62.0})), 0)  # +1.6%
        self.assertEqual(len(_trig(r, {"weight_now": 63.0, "weight_baseline": 0})), 0)     # 分母 0

    # ---------- 连续/区间 ----------

    def test_consecutive_gte_trigger_and_not(self):
        r = {"metric": "rpe", "op": "consecutive_gte", "count": 3, "threshold": 15}
        self.assertEqual(len(_trig(r, {"rpe_seq": [15, 16, 15]})), 1)     # 连续 3 次 ≥15
        self.assertEqual(len(_trig(r, {"rpe_seq": [15, 14, 15]})), 0)     # 中断
        self.assertEqual(len(_trig(r, {"rpe_seq": [15, 15]})), 0)         # 只 2 次

    def test_sustained_range_trigger_and_not(self):
        r = {"metric": "hr", "op": "sustained_range", "min": 100, "max": 120}
        self.assertEqual(len(_trig(r, {"hr_seq": [80, 105, 110, 115]})), 1)   # 末 3 次持续在区间
        self.assertEqual(len(_trig(r, {"hr_seq": [80, 105, 110, 95]})), 0)    # 末次出区间
        self.assertEqual(len(_trig(r, {"hr_seq": []})), 0)

    # ---------- 达标/漏检 ----------

    def test_any_not_met_trigger_and_not(self):
        r = {"metric": "risk_factor", "op": "any_not_met",
             "items": ["LDL_C", "BP", "HbA1c"]}
        self.assertEqual(len(_trig(r, {"LDL_C_met": False, "BP_met": True, "HbA1c_met": True})), 1)
        self.assertEqual(len(_trig(r, {"LDL_C_met": True, "BP_met": True, "HbA1c_met": True})), 0)

    def test_consecutive_missed_trigger_and_not(self):
        r = {"metric": "upload", "op": "consecutive_missed", "count": 2}
        self.assertEqual(len(_trig(r, {"upload_gap_cycles": 2})), 1)
        self.assertEqual(len(_trig(r, {"upload_gap_cycles": 1})), 0)

    def test_days_before_trigger_and_not(self):
        r = {"metric": "followup_due", "op": "days_before", "value": 3}
        self.assertEqual(len(_trig(r, {"followup_due": 2})), 1)   # 3 天内
        self.assertEqual(len(_trig(r, {"followup_due": 3})), 1)   # 等于边界
        self.assertEqual(len(_trig(r, {"followup_due": 4})), 0)   # 超 3 天
        self.assertEqual(len(_trig(r, {})), 0)

    def test_consecutive_met_trigger_and_not(self):
        r = {"metric": "streak", "op": "consecutive_met", "count": 3}
        self.assertEqual(len(_trig(r, {"streak": 3})), 1)
        self.assertEqual(len(_trig(r, {"streak": 2})), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
