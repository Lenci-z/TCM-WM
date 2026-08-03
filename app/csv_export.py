# -*- coding: utf-8 -*-
"""
CSV 导出工具（阶段7-3）：统一导出逻辑，UTF-8 BOM（Excel 直接打开中文不乱码）。
"""
import csv


def export_csv(path: str, headers: list, rows: list) -> int:
    """导出 CSV（UTF-8 BOM）。rows 为 list[list] 或 list[dict]（按 headers 键取值）。
    返回写入行数。"""
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        n = 0
        for row in rows:
            if isinstance(row, dict):
                values = [row.get(h, "") for h in headers]
            else:
                values = list(row)
            writer.writerow(values)
            n += 1
    return n


def patient_csv_rows(patients: list) -> list:
    """患者列表 → CSV 行（明文姓名/联系方式）。"""
    return [
        {
            "medical_no": p.get("medical_no", ""),
            "patient_id": p["patient_id"],
            "name": p.get("name", ""),
            "gender": p.get("gender", ""),
            "birth_date": p.get("birth_date", ""),
            "disease_category": p.get("disease_category", ""),
            "register_date": p.get("register_date", ""),
            "status": p.get("status", ""),
            "contact": p.get("contact", ""),
            "inpatient_no": p.get("inpatient_no", ""),
        }
        for p in patients
    ]


def followup_csv_rows(followups: list) -> list:
    """随访记录 → CSV 行。"""
    return [
        {
            "fu_id": r["fu_id"],
            "patient_id": r["patient_id"],
            "patient_name": r.get("patient_name", ""),
            "fu_type": r.get("fu_type", ""),
            "plan_date": r.get("plan_date", ""),
            "actual_date": r.get("actual_date", ""),
            "status": r.get("status", ""),
            "handler": r.get("handler", ""),
        }
        for r in followups
    ]


def audit_csv_rows(logs: list) -> list:
    """审计日志 → CSV 行。"""
    return [
        {
            "log_id": r["log_id"],
            "username": r.get("username", ""),
            "action_time": r.get("action_time", ""),
            "action_type": r.get("action_type", ""),
            "table_name": r.get("table_name", ""),
            "record_id": r.get("record_id", ""),
            "detail": r.get("detail", ""),
        }
        for r in logs
    ]
