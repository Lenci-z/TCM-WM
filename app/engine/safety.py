# -*- coding: utf-8 -*-
"""
安全校验层（2.5）
依据：设计方案 v0.2 第 3.4 节引擎执行流程中的安全校验层
      + 2.0 节病种差异化参数（运动禁忌与限制）
构成：
  - 通用/证型禁忌：rule_contraindication 表（disease_category/pattern/risk_level 支持 * 通配）
  - 病种特异禁忌：disease_config.contraindication_json
"""
import json


def _match(value, rule_value) -> bool:
    """规则匹配：* 通配任意值。"""
    return rule_value in ("*", value)


def check_safety(safety_rules: list, disease_contra: dict,
                 disease_category: str, pattern: str, risk_level: str):
    """执行安全校验。纯逻辑，无 conn（P2-T4）。
    参数：
      safety_rules: 禁忌规则列表（由 repo.get_safety_rules() 获取，
                     元素含 disease_category/pattern/risk_level/name/rule）
      disease_contra: 病种特异禁忌 dict（由 repo.get_disease_contraindication() 获取，含 items）
    返回 {'blocked': [...], 'warnings': [...]}：
      blocked   — 硬性禁忌（如禁高强度抗阻），处方必须处理
      warnings  — 提示性限制（如监测症状、控制体重）
    """
    blocked, warnings = [], []

    # 1. 规则表（通用 + 证型级 + 病种级）
    for r in safety_rules:
        if not (_match(disease_category, r.get("disease_category"))
                and _match(pattern, r.get("pattern"))
                and _match(risk_level, r.get("risk_level"))):
            continue
        rule = r.get("rule", {})
        item = {"name": r.get("name", ""), "detail": rule.get("detail", ""),
                "action": rule.get("action", "")}
        if rule.get("level") == "block":
            blocked.append(item)
        else:
            warnings.append(item)

    # 2. 病种特异禁忌（disease_config.contraindication_json）
    for item in (disease_contra or {}).get("items", []):
        entry = {"name": item.get("name", ""), "detail": item.get("rule", ""),
                 "window": item.get("window", "")}
        if item.get("level") == "block":
            blocked.append(entry)
        else:
            warnings.append(entry)

    return {"blocked": blocked, "warnings": warnings}


def apply_safety(rx: dict, safety: dict) -> dict:
    """把安全校验结果应用到处方：
    - blocked 含 block_resistance / block_upper_limb → 禁用抗阻
    - blocked 含 supervision_required → 标注需监护
    - 其余 warning 仅记录提示
    返回带 safety 标注的处方 dict（不修改原 dict）。
    """
    out = dict(rx)
    out["safety"] = {"blocked": safety["blocked"], "warnings": safety["warnings"]}
    actions = {b.get("action") for b in safety["blocked"]}
    if "block_resistance" in actions or "block_upper_limb" in actions:
        try:
            res = json.loads(out.get("resistance_json") or "{}")
            res["enabled"] = False
            out["resistance_json"] = json.dumps(res, ensure_ascii=False)
            out["safety"]["applied"] = "抗阻已禁用（禁忌命中）"
        except (ValueError, TypeError):
            pass
    if "supervision_required" in actions:
        out["safety"]["supervision"] = "需监护下运动"
    return out


if __name__ == "__main__":
    import sys
    import os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from db import get_conn
    from repo import Repository
    from prescription import build_prescription

    conn = get_conn()
    repo = Repository(conn)
    print("=== 2.5 安全校验 ===")
    for pattern, risk in [("肝阳上亢", "低危"), ("气虚血瘀", "中危"), ("阳虚水泛", "高危")]:
        s = check_safety(repo.get_safety_rules(),
                    repo.get_disease_contraindication("CAD_PCI"),
                    "CAD_PCI", pattern, risk)
        print(f"{pattern}/{risk}: block={len(s['blocked'])} warning={len(s['warnings'])}")
        for b in s["blocked"]:
            print(f"    ⛔ {b['name']}: {b['detail']}")
        for w in s["warnings"][:3]:
            print(f"    ⚠ {w['name']}: {w['detail'][:30]}...")

    print("\n=== 2.5 应用到处方（肝阳上亢 → 抗阻禁用） ===")
    rx = build_prescription(repo.get_rx_template("CAD_PCI", "CAD_PCI-F1"),
                            repo.get_baduanjin_cfg("CAD_PCI"),
                            "CAD_PCI", "肝阳上亢", "低危", phase="II", week_no=1,
                            resting_hr=65, age=60)
    s = check_safety(repo.get_safety_rules(),
                    repo.get_disease_contraindication("CAD_PCI"),
                    "CAD_PCI", "肝阳上亢", "低危")
    rx = apply_safety(rx, s)
    res = json.loads(rx["resistance_json"])
    print(f"  抗阻 enabled={res['enabled']} | 应用标注: {rx['safety'].get('applied')}")
    conn.close()
