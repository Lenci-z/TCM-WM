# -*- coding: utf-8 -*-
"""
证型判定引擎（2.2）
依据：设计方案 v0.2 第 2.1 节 轴二 + 2.5 辨证施养
逻辑：结构化四诊问卷勾选条目 → 与各证型 keywords 匹配计数
      最高分为主证，次高为兼证；医师可改判并确认（GUI 环节）。
"""
import json


def load_patterns(conn):
    """读取证型特征库（rule_tcm_pattern）。"""
    rows = conn.execute(
        "SELECT pattern_name, features_json, comorbidity_json FROM rule_tcm_pattern WHERE enabled=1"
    ).fetchall()
    result = []
    for r in rows:
        f = json.loads(r["features_json"])
        result.append({
            "name": r["pattern_name"],
            "keywords": f.get("keywords", []),
            "symptoms": f.get("symptoms", []),
            "tongue": f.get("tongue", ""),
            "pulse": f.get("pulse", ""),
            "comorbidity": r["comorbidity_json"],
        })
    return result


def judge_pattern(conn, selected_items):
    """证型判定。
    参数 selected_items: 四诊问卷勾选条目文本列表。
    返回 (main, secondary, scores)：
      main: 主证（最高分证型名或 None）
      secondary: 兼证（次高且分数>0 的证型名或 None）
      scores: {证型名: 命中数}
    """
    patterns = load_patterns(conn)
    if not selected_items:
        return None, None, {}
    items = set(selected_items)
    scores = {}
    for p in patterns:
        hits = [kw for kw in p["keywords"] if kw in items]
        scores[p["name"]] = len(hits)
    ranked = sorted(scores.items(), key=lambda x: -x[1])
    main = ranked[0][0] if ranked and ranked[0][1] > 0 else None
    secondary = None
    if len(ranked) > 1 and ranked[1][1] > 0:
        secondary = ranked[1][0]
    return main, secondary, scores


if __name__ == "__main__":
    import sys
    import os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from db import get_conn

    conn = get_conn()
    cases = [
        ("气虚血瘀典型", ["胸闷隐痛", "乏力", "气短", "动则加重", "舌暗", "瘀斑", "脉细", "脉涩"]),
        ("痰浊闭阻典型", ["胸闷如窒", "体胖", "痰多", "苔厚腻", "脉滑"]),
        ("气阴两虚典型", ["心悸", "乏力", "口干", "五心烦热", "舌红", "少苔", "脉细", "脉数"]),
        ("肝阳上亢典型", ["头晕", "头痛", "烦躁", "易怒", "面红", "舌红", "脉弦"]),
        ("混合（气阴+气虚兼夹）", ["心悸", "乏力", "口干", "舌红", "少苔"]),
    ]
    for name, items in cases:
        main, sec, scores = judge_pattern(conn, items)
        top = sorted(scores.items(), key=lambda x: -x[1])[:3]
        print(f"{name} → 主证: {main} | 兼证: {sec}")
        print(f"    得分: {top}")
    conn.close()
