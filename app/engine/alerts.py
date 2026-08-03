# -*- coding: utf-8 -*-
"""
预警引擎（2.6）— 纯领域逻辑（P2-T4 解耦后不接 conn）
依据：设计方案 v0.2 第 2.8 节（预警规则与处置闭环）+ 3.4 节（预警规则表 JSON 结构）
流程：触发 → 分级 → 通知对象；持久化由调用方经 repo.insert_alert() 完成
规则：rule_alert（由 repo.get_alert_rules() 提供，condition/applicable/actions 已解析）
"""
import json


def _applicable(rule, disease_category, pattern, risk_level) -> bool:
    """适用范围过滤（病种/证型/分层，* 通配；列表含 * 视为全匹配）。"""
    app = rule.get("applicable", {}) or {}
    for key, val in [("disease_category", disease_category),
                     ("pattern", pattern),
                     ("risk_level", risk_level)]:
        allowed = app.get(key, ["*"])
        if "*" not in allowed and val not in allowed:
            return False
    return True


def _consecutive(values, count, threshold):
    """列表末尾是否连续 count 个 ≥ threshold。"""
    tail = values[-count:] if len(values) >= count else values
    return len(tail) == count and all(v >= threshold for v in tail)


def _eval_condition(cond: dict, ctx: dict) -> bool:
    """判定单条预警条件（op 全集见种子数据）。"""
    metric = cond["metric"]
    op = cond["op"]
    if op == "eq":
        return ctx.get(metric) == cond.get("value")
    if op == "out_of_range":
        v = ctx.get(metric)
        if v is None:
            return False
        return v < cond["min"] or v > cond["max"]
    if op == "gte":
        return (ctx.get(metric) or 0) >= cond["value"]
    if op == "lt":
        return (ctx.get(metric) if ctx.get(metric) is not None else 1e9) < cond["value"]
    if op == "delta_increase":
        now = ctx.get(f"{metric}_now")
        prev = ctx.get(f"{metric}_prev")
        if now is None or prev is None:
            return False
        return now - prev >= cond.get("threshold_kg", 0)
    if op == "delta_pct_increase":
        now = ctx.get(f"{metric}_now")
        base = ctx.get(f"{metric}_baseline")
        if now is None or base in (None, 0):
            return False
        return (now - base) / base * 100 > cond.get("threshold_pct", 0)
    if op == "consecutive_gte":
        seq = ctx.get(f"{metric}_seq") or []
        return _consecutive(seq, cond.get("count", 1), cond.get("threshold", 0))
    if op == "sustained_range":
        seq = ctx.get(f"{metric}_seq") or []
        return bool(seq) and all(cond["min"] <= v <= cond["max"] for v in seq[-3:])
    if op == "any_not_met":
        return any(not ctx.get(f"{item}_met", True) for item in cond.get("items", []))
    if op == "consecutive_missed":
        return (ctx.get("upload_gap_cycles") or 0) >= cond.get("count", 1)
    if op == "consecutive_met":
        # 连续达标激励：ctx[metric]（如 streak=连续达标天数）>= count 即触发
        return (ctx.get(metric) or 0) >= cond.get("count", 1)
    if op == "days_before":
        due = ctx.get(metric)
        return due is not None and 0 <= due <= cond.get("value", 3)
    return False


def _notify_target(actions: list) -> str:
    targets = []
    for a in actions:
        if a.get("type") == "notify_physician":
            targets.append("医师端(即时通知)")
        if a.get("type") == "notify_patient":
            targets.append("患者端")
        if a.get("type") == "create_task":
            targets.append(f"待办{int(a.get('due_hours', 72))}h")
    return "+".join(targets) if targets else "记录"


def evaluate_alerts(alert_rules: list, disease_category: str, pattern: str,
                    risk_level: str, ctx: dict):
    """评估全部启用的预警规则，返回触发列表。纯逻辑，无 conn（P2-T4）。
    参数：
      alert_rules: 预警规则列表（由 repo.get_alert_rules() 获取，
                    元素含 rule_code/level/name/condition/applicable/actions）
      ctx: 预警上下文 dict
    返回 [ {rule_code, level, name, trigger_data, notify_target} ... ]
    注意：不持久化。持久化由调用方经 repo.insert_alert() 完成。
    """
    triggered = []
    for rule in alert_rules:
        if not _applicable(rule, disease_category, pattern, risk_level):
            continue
        cond = rule.get("condition", {})
        if _eval_condition(cond, ctx):
            actions = rule.get("actions", []) or []
            item = {
                "rule_code": rule["rule_code"],
                "level": rule["level"],
                "name": rule["name"],
                "trigger_data": json.dumps(ctx, ensure_ascii=False, default=str),
                "notify_target": _notify_target(actions),
            }
            triggered.append(item)
    return triggered




if __name__ == "__main__":
    import sys
    import os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from db import get_conn
    from repo import Repository

    conn = get_conn()
    repo = Repository(conn)
    alert_rules = repo.get_alert_rules()
    print("=== 2.6 预警引擎 ===")
    cases = [
        ("红色·心率105", {"resting_hr": 105}),
        ("红色·体重3日+2.5kg", {"weight_now": 64.5, "weight_prev": 62.0}),
        ("黄色·PHQ9=12", {"phq9_or_gad7": 12}),
        ("黄色·完成率40%", {"completion_rate": 40.0}),
        ("黄色·LDL未达标", {"LDL_C_met": False, "BP_met": True, "HbA1c_met": True}),
        ("蓝色·随访2天后", {"followup_due": 2}),
        ("无触发·正常数据", {"resting_hr": 72, "weight_now": 62.0, "weight_prev": 61.8,
                            "phq9_or_gad7": 6, "completion_rate": 80.0, "followup_due": 9}),
    ]
    for name, ctx in cases:
        trig = evaluate_alerts(alert_rules, "CAD_PCI", "气虚血瘀", "中危", ctx)
        if trig:
            for t in trig:
                print(f"  {name} → [{t['level']}] {t['name']} | 通知: {t['notify_target']}")
        else:
            print(f"  {name} → 无触发")

    print()
    print("=== 闭环留痕（repo 持久化） ===")
    # 先建测试患者（外键要求）
    pid = repo.insert_patient({"name": "预警测试", "gender": "男", "birth_date": "1960-01-01",
                               "contact": "13800138000", "register_date": "2026-08-03",
                               "disease_category": "CAD_PCI"})
    ctx = {"resting_hr": 108}
    trig = evaluate_alerts(alert_rules, "CAD_PCI", "气虚血瘀", "中危", ctx)
    aid = None
    for item in trig:
        aid = repo.insert_alert(pid, item)
        print(f"  已写入: alert_id={aid} [{item['level']}] {item['rule_code']} 状态=待处置")
    if aid:
        repo.close_alert(aid, "测试医师", "已电话联系患者，心率复测正常")
        r = repo.query_one("SELECT status, handler, handle_content FROM alert WHERE alert_id=?", (aid,))
        print(f"  已关闭: 状态={r['status']} 处置人={r['handler']} 内容={r['handle_content']}")
    conn.close()
