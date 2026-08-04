# -*- coding: utf-8 -*-
"""规则库 API（B-T7）：7 类规则读取/更新（质控权限 rules:edit 仅管理员）。
规则配置与 GUI RulesView.RULE_TYPES 一致（规则外置，存库不硬编码）。
"""
import sys
import os
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

router = APIRouter()

# 与 app/ui/rules_view.py RULE_TYPES 一致：(表名, 主键, 列[(字段,标题)], JSON字段[(字段,说明)], 普通字段)
RULE_TYPES = {
    "危险分层阈值（CAD_PCI参数集）": {
        "table": "disease_config", "pk": "config_id",
        "columns": [("disease_category", "病种"), ("enabled", "启用"), ("version", "版本")],
        "json_fields": [("strat_threshold_json", "分层阈值JSON")],
        "plain_fields": ["name", "version", "effective_date"],
        "filter": "disease_category='CAD_PCI'",
    },
    "证型特征库": {
        "table": "rule_tcm_pattern", "pk": "pattern_id",
        "columns": [("pattern_name", "证型"), ("enabled", "启用")],
        "json_fields": [("features_json", "特征JSON"), ("comorbidity_json", "合并JSON")],
        "plain_fields": ["pattern_name"],
    },
    "处方模板（双轴矩阵）": {
        "table": "rule_rx_template", "pk": "template_id",
        "columns": [("matrix_code", "矩阵"), ("pattern", "证型"), ("risk_level", "分层"),
                    ("phase", "阶段"), ("enabled", "启用")],
        "json_fields": [("output_json", "FITT-VP模板JSON"), ("week_range_json", "周次JSON")],
        "plain_fields": ["disease_category", "matrix_code", "pattern", "risk_level", "phase"],
    },
    "八段锦分级": {
        "table": "rule_baduanjin", "pk": "level_id",
        "columns": [("level_code", "级别"), ("posture", "体位"), ("met_est", "METs")],
        "json_fields": [("moves_json", "招式JSON")],
        "plain_fields": ["level_code", "posture", "met_est", "applicable"],
    },
    "预警规则": {
        "table": "rule_alert", "pk": "alert_rule_id",
        "columns": [("rule_code", "编码"), ("level", "级别"), ("name", "名称"), ("enabled", "启用")],
        "json_fields": [("condition_json", "触发条件JSON"), ("applicable_json", "适用范围JSON"),
                        ("actions_json", "处置动作JSON")],
        "plain_fields": ["rule_code", "level", "name"],
    },
    "禁忌规则": {
        "table": "rule_contraindication", "pk": "con_id",
        "columns": [("disease_category", "病种"), ("pattern", "证型"),
                    ("risk_level", "分层"), ("name", "名称")],
        "json_fields": [("rule_json", "禁忌内容JSON")],
        "plain_fields": ["disease_category", "pattern", "risk_level", "name"],
    },
    "病种参数集": {
        "table": "disease_config", "pk": "config_id",
        "columns": [("disease_category", "病种"), ("name", "名称"), ("enabled", "启用")],
        "json_fields": [("strat_threshold_json", "分层阈值"), ("contraindication_json", "运动禁忌"),
                        ("baduanjin_start_json", "八段锦起始映射"), ("followup_template_json", "随访模板"),
                        ("alert_special_json", "特有预警")],
        "plain_fields": ["disease_category", "name", "version", "effective_date"],
        "filter": None,
    },
}


def _require_admin(request: Request):
    """规则库质控权限：仅管理员（rules:edit）。"""
    from api.patient import _require as _r
    return _r(request, "rules:edit")


def _check_table(table: str):
    for cfg in RULE_TYPES.values():
        if cfg["table"] == table:
            return cfg
    raise HTTPException(status_code=422, detail=f"不允许的表：{table}")


@router.get("/rules")
def list_rules(request: Request):
    """全部规则类别 + 行数据（JSON 字段按文本返回，前端编辑）。"""
    _require_admin(request)
    from api.main import get_repo
    repo = get_repo(request.app)
    out = []
    for name, cfg in RULE_TYPES.items():
        sql = f"SELECT * FROM {cfg['table']}"
        params = ()
        if cfg.get("filter"):
            sql += f" WHERE {cfg['filter']}"
        rows = repo.query_all(sql, params)
        out.append({
            "key": name, "table": cfg["table"], "pk": cfg["pk"],
            "columns": cfg["columns"], "json_fields": cfg["json_fields"],
            "plain_fields": cfg["plain_fields"], "rows": rows,
        })
    return {"categories": out}


class RuleUpdate(BaseModel):
    plain: dict = {}
    json_fields: dict = {}


@router.put("/rules/{table}/{row_id}")
def update_rule(table: str, row_id: int, body: RuleUpdate, request: Request):
    """更新规则行（白名单表/字段，JSON 字段校验 JSON 语法）。"""
    _require_admin(request)
    from api.main import get_repo
    repo = get_repo(request.app)
    cfg = _check_table(table)

    data = {}
    for k, v in (body.plain or {}).items():
        if k not in cfg["plain_fields"]:
            raise HTTPException(status_code=422, detail=f"不允许的字段：{k}")
        data[k] = v
    for k, v in (body.json_fields or {}).items():
        if k not in [jf[0] for jf in cfg["json_fields"]]:
            raise HTTPException(status_code=422, detail=f"不允许的字段：{k}")
        if isinstance(v, str):
            try:
                json.loads(v)  # 校验 JSON 语法
            except json.JSONDecodeError:
                raise HTTPException(status_code=422, detail=f"{k} 不是合法 JSON")
        data[k] = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)

    if not data:
        raise HTTPException(status_code=422, detail="无更新内容")
    where = f"{cfg['pk']}=?"
    repo.update_row(table, data, where, (row_id,))
    return repo.query_one(f"SELECT * FROM {table} WHERE {cfg['pk']}=?", (row_id,))
