# -*- coding: utf-8 -*-
"""
预警引擎（2.6）
依据：设计方案 v0.2 第 2.8 节（预警规则与处置闭环）+ 3.4 节（预警规则表 JSON 结构）
流程：触发 → 分级 → 通知对象 → 处置 → 记录 → 关闭，全程留痕
规则：rule_alert 表（condition_json / applicable_json / actions_json）
"""
import json
from datetime import datetime


def load_alert_rules(conn):
    rows = conn.execute(
        "SELECT rule_code, level, name, condition_json, applicable_json, actions_json "
        "FROM rule_alert WHERE enabled=1"
    ).fetchall()
    return rows


def _applicable(rule, disease_category, pattern, risk_level) -> bool:
    """适用范围过滤（病种/证型/分层，* 通配；列表含 * 视为全匹配）。"""
    app = json.loads(rule["applicable_json"] or "{}")
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


def evaluate_alerts(conn, disease_category: str, pattern: str, risk_level: str,
                    ctx: dict, patient_id: int = None, persist: bool = False):
    """评估全部启用的预警规则，返回触发列表。
    persist=True 时写入 alert 表（全程留痕）。
    返回 [ {rule_code, level, name, trigger_data, notify_target} ... ]
    """
    triggered = []
    rules = load_alert_rules(conn)
    for rule in rules:
        if not _applicable(rule, disease_category, pattern, risk_level):
            continue
        cond = json.loads(rule["condition_json"])
        if _eval_condition(cond, ctx):
            actions = json.loads(rule["actions_json"] or "[]")
            item = {
                "rule_code": rule["rule_code"],
                "level": rule["level"],
                "name": rule["name"],
                "trigger_data": json.dumps(ctx, ensure_ascii=False, default=str),
                "notify_target": _notify_target(actions),
            }
            triggered.append(item)
            if persist and patient_id is not None:
                insert_alert(conn, patient_id, item)
    return triggered


def insert_alert(conn, patient_id: int, item: dict) -> int:
    """写入预警记录（状态=待处置）。"""
    return conn.execute(
        "INSERT INTO alert (patient_id, trigger_time, level, rule_code, trigger_data_json, "
        "notify_target, status) VALUES (?,?,?,?,?,?,'待处置')",
        (patient_id, datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
         item["level"], item["rule_code"], item["trigger_data"], item["notify_target"]),
    ).lastrowid


def pending_alerts(conn, level: str = None):
    """待处置预警列表（GUI 工作台用）。"""
    sql = "SELECT * FROM alert WHERE status IN ('待处置','处置中')"
    params = []
    if level:
        sql += " AND level=?"
        params.append(level)
    sql += " ORDER BY trigger_time DESC"
    return conn.execute(sql, params).fetchall()


def close_alert(conn, alert_id: int, handler: str, handle_content: str) -> None:
    """处置并关闭预警（闭环留痕）。"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        "UPDATE alert SET handler=?, handle_time=?, handle_content=?, status='已关闭' WHERE alert_id=?",
        (handler, now, handle_content, alert_id),
    )
    conn.commit()


if __name__ == "__main__":
    import sys
    import os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from db import get_conn

    conn = get_conn()
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
        trig = evaluate_alerts(conn, "CAD_PCI", "气虚血瘀", "中危", ctx)
        if trig:
            for t in trig:
                print(f"  {name} → [{t['level']}] {t['name']} | 通知: {t['notify_target']}")
        else:
            print(f"  {name} → 无触发")

    print("\n=== 闭环留痕测试 ===")
    # 先建测试患者（外键要求）
    pid = conn.execute(
        "INSERT INTO patient (name_enc, register_date, disease_category) VALUES (?,?,?)",
        ("dGVzdA==", "2026-08-03", "CAD_PCI"),
    ).lastrowid
    conn.commit()
    ctx = {"resting_hr": 108}
    trig = evaluate_alerts(conn, "CAD_PCI", "气虚血瘀", "中危", ctx, patient_id=pid, persist=True)
    aid = None
    rows = conn.execute("SELECT alert_id, level, rule_code, status FROM alert ORDER BY alert_id DESC LIMIT 1").fetchall()
    if rows:
        aid = rows[0]["alert_id"]
        print(f"  已写入: alert_id={aid} [{rows[0]['level']}] {rows[0]['rule_code']} 状态={rows[0]['status']}")
    if aid:
        close_alert(conn, aid, "测试医师", "已电话联系患者，心率复测正常")
        r = conn.execute("SELECT status, handler, handle_content FROM alert WHERE alert_id=?", (aid,)).fetchone()
        print(f"  已关闭: 状态={r['status']} 处置人={r['handler']} 内容={r['handle_content']}")
    conn.close()
