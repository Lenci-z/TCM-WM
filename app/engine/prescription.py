# -*- coding: utf-8 -*-
"""
矩阵编码 + 处方生成引擎（2.3 / 2.4）
依据：设计方案 v0.2 第 2.3 节（无 CPET 处方路径）、2.4 节（八段锦分级）、2.1 节（双轴矩阵）
核心：
  - matrix_code()        病种-证型-分层 → 矩阵编码（如 CAD_PCI-A2）
  - build_prescription() 模板调取 + 阶段适配 + 心率区间计算 → 结构化处方
  - progression_decision() 进阶/降级判定（文档 2.3）
"""
import json
from datetime import date, timedelta

# 矩阵编码映射（文档 2.1 双轴矩阵）
PATTERN_CODE = {"气虚血瘀": "A", "痰浊闭阻": "B", "气阴两虚": "C",
                "心血瘀阻": "D", "阳虚水泛": "E", "肝阳上亢": "F"}
RISK_CODE = {"低危": "1", "中危": "2", "高危": "3"}

# 阶段 RPE 区间（文档 2.3 通道一）
PHASE_RPE = {
    "I": (9, 11),          # 住院期
    "II": (12, 14),        # 模板默认 II 期中后；初周由模板 RPE 覆盖
    "III": (12, 14),       # 间歇可达 15
}


def matrix_code(disease_category: str, pattern: str, risk_level: str) -> str:
    """生成矩阵编码：病种-证型字母-分层数字。"""
    p = PATTERN_CODE.get(pattern)
    r = RISK_CODE.get(risk_level)
    if not p:
        raise ValueError(f"未知证型: {pattern}")
    if not r:
        raise ValueError(f"未知分层: {risk_level}")
    return f"{disease_category}-{p}{r}"


def load_template(conn, disease_category: str, matrix: str):
    """调取处方模板（II 期基线模板，第一版各矩阵码一条）。
    注意：模板表 matrix_code 存格子编码（A2），处方表 matrix_code 存完整编码（CAD_PCI-A2），
    这里自动取末节，两处保持一致。
    已迁移至 repo.get_rx_template()（P2-T3）；保留本函数仅为向后兼容旧调用。
    """
    m = matrix.rsplit("-", 1)[-1]  # CAD_PCI-A2 → A2
    row = conn.execute(
        "SELECT template_id, output_json FROM rule_rx_template "
        "WHERE disease_category=? AND matrix_code=? AND phase='II' AND enabled=1",
        (disease_category, m),
    ).fetchone()
    if not row:
        raise ValueError(f"无处方模板: {matrix}（规则库未填充或未启用）")
    return json.loads(row["output_json"])


def load_baduanjin_cfg(conn, disease_category: str) -> dict:
    """读取八段锦参数集（起始映射/升降级/阶段角色）。
    已迁移至 repo.get_baduanjin_cfg()（P2-T3）；保留本函数仅为向后兼容旧调用。
    """
    row = conn.execute(
        "SELECT baduanjin_start_json FROM disease_config WHERE disease_category=?",
        (disease_category,),
    ).fetchone()
    return json.loads(row["baduanjin_start_json"]) if row and row["baduanjin_start_json"] else {}


def calc_target_hr(resting_hr, max_hr, age, on_beta_blocker, k_range):
    """目标心率区间（文档 2.3 通道二）：
    - 服 β 受体阻滞剂 → 不用公式，粗略上限 静息+20~30，以 RPE 为准
    - 无实测最大心率且未服 β 阻滞剂 → HRmax = 220 − 年龄（低置信度）
    返回 (hr_min, hr_max)，无法计算时返回 (None, None)
    """
    if resting_hr is None:
        return None, None
    if on_beta_blocker:
        return resting_hr + 20, resting_hr + 30
    if max_hr is None:
        if age is None:
            return None, None
        max_hr = 220 - age
    k = (k_range[0] + k_range[1]) / 2.0
    hr_min = int(round(resting_hr + k_range[0] * (max_hr - resting_hr)))
    hr_max = int(round(resting_hr + k_range[1] * (max_hr - resting_hr)))
    return hr_min, hr_max


def phase_adjust(template: dict, phase: str, risk_level: str, baduanjin_cfg: dict) -> dict:
    """阶段适配（文档 2.3/2.4）：I 期低强度，II 期用模板，III 期进阶维持。"""
    out = json.loads(json.dumps(template))  # 深拷贝
    aerobic = out["aerobic"]
    if phase == "I":
        aerobic["rpe_range"] = list(PHASE_RPE["I"])   # 9–11
        aerobic["duration_min"] = max(10, aerobic["duration_min"] // 2)
        aerobic["frequency_per_week"] = max(3, aerobic["frequency_per_week"] - 1)
        # I 期八段锦为主要形式：按起始映射
        mapping = baduanjin_cfg.get("start_mapping", {})
        out["baduanjin_level"] = mapping.get(risk_level, "L0")
    elif phase == "III":
        # 维持期：时长 +10 分钟（上限 40），RPE 间歇可达 15
        aerobic["duration_min"] = min(40, aerobic["duration_min"] + 10)
        aerobic["rpe_range"] = list(PHASE_RPE["III"])  # 12–14，间歇可达 15
        # 八段锦居家维持：级别升一档（低危且耐受良好 → L3+）
        levels = ["L0", "L1", "L2", "L3", "L3+"]
        cur = out["baduanjin_level"]
        idx = levels.index(cur) if cur in levels else 0
        out["baduanjin_level"] = levels[min(idx + 1, len(levels) - 1)]
    return out


def build_prescription(template: dict, baduanjin_cfg: dict,
                       disease_category: str, pattern: str, risk_level: str,
                       phase: str = "II", week_no: int = 1,
                       resting_hr=None, max_hr=None, age=None, on_beta_blocker=False,
                       gen_date=None, valid_days: int = 14):
    """生成结构化康复处方（草稿状态，待医师审核签发）。纯逻辑，无 conn（P2-T3）。
    参数：
      template: 处方模板 dict（由 repo.get_rx_template() 获取）
      baduanjin_cfg: 八段锦参数集（由 repo.get_baduanjin_cfg() 获取）
    返回 dict（对应 prescription 表字段，status='草稿'）。
    """
    matrix = matrix_code(disease_category, pattern, risk_level)
    tpl = phase_adjust(template, phase, risk_level, baduanjin_cfg)

    aerobic = tpl["aerobic"]
    rpe_min, rpe_max = aerobic["rpe_range"]
    hr_min, hr_max = calc_target_hr(resting_hr, max_hr, age, on_beta_blocker, aerobic["k_range"])

    if gen_date is None:
        gen_date = date.today().isoformat()
    valid_until = (date.fromisoformat(gen_date) + timedelta(days=valid_days)).isoformat()

    return {
        "disease_category": disease_category,
        "gen_date": gen_date,
        "valid_until": valid_until,
        "phase": phase,
        "week_no": week_no,
        "matrix_code": matrix,
        "baduanjin_level": tpl["baduanjin_level"],
        "aerobic_type": "/".join(aerobic["types"]),
        "aerobic_duration": aerobic["duration_min"],
        "aerobic_freq": aerobic["frequency_per_week"],
        "rpe_min": rpe_min,
        "rpe_max": rpe_max,
        "hr_min": hr_min,
        "hr_max": hr_max,
        "resistance_json": json.dumps(tpl["resistance"], ensure_ascii=False),
        "tcm_json": json.dumps(tpl["tcm"], ensure_ascii=False),
        "nutrition_json": json.dumps({"diet_notes": tpl["tcm"]["diet_notes"],
                                      "diet_tags": tpl["tcm"]["diet_tags"]}, ensure_ascii=False),
        "risk_factor_json": json.dumps({"LDL_C_target": 1.4, "BP_target": "130/80",
                                        "note": "文档 2.6 危险因素管理目标"}, ensure_ascii=False),
        "physician_sign": None,
        "status": "草稿",
        "version": 1,
    }


def progression_decision(stats: dict) -> dict:
    """进阶/降级判定（文档 2.3 进阶与降级规则）。
    参数 stats:
      completion_rate_2w   连续 2 周完成率 %
      avg_rpe              平均 RPE
      target_rpe_max       目标区间上限
      red_alert            近 2 周是否有红色预警 (bool)
      yellow_alert         近 2 周是否有黄色预警 (bool)
      new_symptom          是否有新发症状 (bool)
      rpe_ge15_count       连续 3 次 RPE≥15 的次数窗口内是否发生 (bool)
      resting_hr_rise      静息心率较基线上升 >20% (bool)
    返回 {'decision': 'upgrade'|'downgrade'|'maintain', 'reasons': [...]}
    """
    reasons = []
    # 降级：满足任一
    if stats.get("red_alert"):
        reasons.append("出现红色预警")
    if stats.get("rpe_ge15_count"):
        reasons.append("连续 3 次 RPE ≥15")
    if stats.get("new_symptom"):
        reasons.append("运动中或运动后出现胸痛、气促加重、头晕")
    if stats.get("resting_hr_rise"):
        reasons.append("静息心率较基线上升 >20%")
    if reasons:
        return {"decision": "downgrade", "reasons": reasons}
    # 进阶：全部满足
    ok = (
        (stats.get("completion_rate_2w") or 0) >= 80
        and (stats.get("avg_rpe") or 0) <= stats.get("target_rpe_max", 14)
        and not stats.get("red_alert")
        and not stats.get("yellow_alert")
        and not stats.get("new_symptom")
    )
    if ok:
        return {"decision": "upgrade", "reasons": ["连续 2 周完成率≥80%", "平均 RPE 达标", "无预警", "无新发症状"]}
    return {"decision": "maintain", "reasons": ["未满足进阶条件，无需降级"]}


if __name__ == "__main__":
    import sys
    import os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from db import get_conn
    from repo import Repository

    conn = get_conn()
    repo = Repository(conn)
    print("=== 2.3 矩阵编码 ===")
    for pattern, risk in [("气虚血瘀", "中危"), ("肝阳上亢", "低危"), ("阳虚水泛", "高危")]:
        print(f"  {pattern}/{risk} → {matrix_code('CAD_PCI', pattern, risk)}")

    print("\n=== 2.4 处方生成 ===")
    rx = build_prescription(repo.get_rx_template("CAD_PCI", "CAD_PCI-A2"),
                            repo.get_baduanjin_cfg("CAD_PCI"),
                            "CAD_PCI", "气虚血瘀", "中危", phase="II", week_no=3,
                            resting_hr=60, age=65, on_beta_blocker=False)
    print(f"  II期 A2: 八段锦{rx['baduanjin_level']} 有氧{rx['aerobic_duration']}min×{rx['aerobic_freq']}次"
          f" RPE[{rx['rpe_min']},{rx['rpe_max']}] HR[{rx['hr_min']},{rx['hr_max']}] 矩阵{rx['matrix_code']}")
    rx_i = build_prescription(repo.get_rx_template("CAD_PCI", "CAD_PCI-E3"),
                            repo.get_baduanjin_cfg("CAD_PCI"),
                            "CAD_PCI", "阳虚水泛", "高危", phase="I", week_no=1,
                              resting_hr=70, age=70, on_beta_blocker=True)
    print(f"  I期 E3(服β): 八段锦{rx_i['baduanjin_level']} 有氧{rx_i['aerobic_duration']}min "
          f"RPE[{rx_i['rpe_min']},{rx_i['rpe_max']}] HR[{rx_i['hr_min']},{rx_i['hr_max']}]")
    rx_iii = build_prescription(repo.get_rx_template("CAD_PCI", "CAD_PCI-F1"),
                            repo.get_baduanjin_cfg("CAD_PCI"),
                            "CAD_PCI", "肝阳上亢", "低危", phase="III", week_no=12,
                                resting_hr=65, age=60, on_beta_blocker=False)
    print(f"  III期 F1: 八段锦{rx_iii['baduanjin_level']} 有氧{rx_iii['aerobic_duration']}min "
          f"RPE[{rx_iii['rpe_min']},{rx_iii['rpe_max']}]")

    print("\n=== 2.4 进阶/降级 ===")
    d1 = progression_decision({"completion_rate_2w": 85, "avg_rpe": 12, "target_rpe_max": 14})
    d2 = progression_decision({"completion_rate_2w": 70, "avg_rpe": 13, "target_rpe_max": 14})
    d3 = progression_decision({"completion_rate_2w": 90, "avg_rpe": 15, "target_rpe_max": 14,
                               "rpe_ge15_count": True})
    for d in [d1, d2, d3]:
        print(f"  {d['decision']}: {d['reasons']}")
    conn.close()
