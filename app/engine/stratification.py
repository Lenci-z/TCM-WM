# -*- coding: utf-8 -*-
"""
危险分层判定引擎（2.1）
依据：设计方案 v0.2 第 2.1 节 轴一（CAD_PCI 参数集，存于 disease_config.strat_threshold_json）
逻辑：按 高危→中危→低危 逐级判定，任一级条件满足任一即达本级。
输入：clinical dict，键为 metric 名（LVEF / met_capacity / six_mwd / complete_revascularization ...）
"""
import json


def load_strat_config(conn, disease_category: str) -> dict:
    """读取病种危险分层参数集。"""
    row = conn.execute(
        "SELECT strat_threshold_json FROM disease_config WHERE disease_category=?",
        (disease_category,),
    ).fetchone()
    if not row or not row["strat_threshold_json"]:
        raise ValueError(f"病种 {disease_category} 无危险分层参数集（未启用或未配置）")
    return json.loads(row["strat_threshold_json"])


def _met_capacity_from_6mwd(six_mwd):
    """6MWT 推算运动能力（文档 2.3）：
    peak VO2 ≈ 4.948 + 0.023 × 6MWD(m)；METs = VO2 / 3.5
    注意：公式需本院数据校准（技术秘密），此处为文献默认系数。
    """
    if six_mwd is None:
        return None
    vo2 = 4.948 + 0.023 * six_mwd
    return vo2 / 3.5


def _norm(clinical: dict) -> dict:
    """归一化：补充推算字段（met_capacity 缺失时用 6MWD 推算）。"""
    data = dict(clinical)
    if data.get("met_capacity") is None and data.get("six_mwd") is not None:
        data["met_capacity"] = _met_capacity_from_6mwd(data["six_mwd"])
    return data


def _eval_condition(cond: dict, data: dict) -> bool:
    """判定单条条件。op: lt / gte / range / eq"""
    metric = cond["metric"]
    value = data.get(metric)
    if value is None:
        return False  # 缺数据视为不命中（保守：不因缺数据升级）
    op = cond["op"]
    if op == "lt":
        return value < cond["value"]
    if op == "gte":
        return value >= cond["value"]
    if op == "range":
        return cond["min"] <= value <= cond["max"]
    if op == "eq":
        return value == cond["value"]
    raise ValueError(f"未知操作符: {op}")


def stratify(conn, disease_category: str, clinical: dict):
    """执行危险分层。
    返回 (risk_level, triggered)：
      risk_level: 低危/中危/高危
      triggered: 命中条件描述列表（写入 risk_stratification.trigger_json）
    """
    cfg = load_strat_config(conn, disease_category)
    data = _norm(clinical)
    for level in ["高危", "中危", "低危"]:
        conds = cfg["levels"].get(level, [])
        triggered = []
        for c in conds:
            if _eval_condition(c, data):
                triggered.append({"level": level, "metric": c["metric"], "desc": c["desc"]})
        if triggered:
            return level, triggered
    # 所有条件均未命中（如无数据）→ 保守返回高危（医疗安全取向）
    return "高危", [{"level": "高危", "metric": "_default", "desc": "数据不足，保守判高危"}]


if __name__ == "__main__":
    import sys
    import os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from db import get_conn

    conn = get_conn()
    cases = [
        ("高危用例（LVEF 35%）", {"LVEF": 35, "complete_revascularization": 0}),
        ("中危用例（LVEF 45，MET 6）", {"LVEF": 45, "met_capacity": 6, "revascularization_status": "incomplete_no_ischemia"}),
        ("低危用例（LVEF 55，完全血运重建，MET 8）",
         {"LVEF": 55, "complete_revascularization": True, "exercise_test_clean": True, "met_capacity": 8}),
        ("6MWD 推算用例（300m）", {"LVEF": 50, "six_mwd": 300}),
    ]
    for name, clinical in cases:
        level, triggered = stratify(conn, "CAD_PCI", clinical)
        print(f"{name} → {level}")
        for t in triggered:
            print(f"    命中: [{t['level']}] {t['desc']}")
    conn.close()
