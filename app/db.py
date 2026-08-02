# -*- coding: utf-8 -*-
"""
中西医结合心血管康复系统 — 数据库层
依据：中西医结合心血管康复系统设计方案_v0.2.md 第 3.3/3.4 节
架构约束：全表含 disease_category 字段（多病种设计），第一版仅启用 CAD_PCI
规则外置：规则层（分层阈值/证型特征/处方模板/八段锦分级/预警/禁忌）全部配置化存表，不硬编码
"""
import base64
import json
import os
import sqlite3
from datetime import datetime

# ---------- 路径 ----------
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
DB_PATH = os.path.join(DATA_DIR, "rehab.db")
SEED_DIR = os.path.join(DATA_DIR, "seed")

# ---------- 加密工具（MVP 标准库可逆加密，正式版对接医院加密方案） ----------
_ENCRYPT_KEY = b"CR-Rehab-MVP-2026"  # 本地工具用固定密钥；正式版须更换并纳入密钥管理


def encrypt_text(plain: str) -> str:
    """姓名/联系方式加密存储（XOR + base64，可逆）。"""
    if plain is None:
        return None
    data = plain.encode("utf-8")
    key = _ENCRYPT_KEY
    xored = bytes(b ^ key[i % len(key)] for i, b in enumerate(data))
    return base64.b64encode(xored).decode("ascii")


def decrypt_text(cipher: str) -> str:
    """解密 encrypt_text 的产物。"""
    if cipher is None:
        return None
    xored = base64.b64decode(cipher.encode("ascii"))
    key = _ENCRYPT_KEY
    data = bytes(b ^ key[i % len(key)] for i, b in enumerate(xored))
    return data.decode("utf-8")


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ---------- 建表 SQL（严格按文档 3.3 节字段） ----------

SCHEMA = {
    # 病种参数集表 ★v0.2新增★
    "disease_config": """
        CREATE TABLE IF NOT EXISTS disease_config (
            config_id          INTEGER PRIMARY KEY AUTOINCREMENT,
            disease_category   TEXT NOT NULL UNIQUE,        -- 病种编码，如 CAD_PCI
            name               TEXT NOT NULL,               -- 病种名称
            enabled            INTEGER NOT NULL DEFAULT 0,  -- 1=启用 0=预留
            strat_threshold_json   TEXT,                    -- 危险分层阈值(JSON)
            contraindication_json  TEXT,                    -- 运动禁忌规则(JSON)
            baduanjin_start_json   TEXT,                    -- 八段锦起始级别映射(JSON)
            followup_template_json TEXT,                    -- 随访节点模板(JSON)
            alert_special_json     TEXT,                    -- 特有预警规则(JSON)
            version            TEXT,                        -- 参数集版本号
            effective_date     TEXT                         -- 生效日期
        )
    """,
    # 患者主表
    "patient": """
        CREATE TABLE IF NOT EXISTS patient (
            patient_id       INTEGER PRIMARY KEY AUTOINCREMENT,
            name_enc         TEXT NOT NULL,                 -- 姓名(加密)
            gender           TEXT,                          -- 性别
            birth_date       TEXT,                          -- 出生日期
            contact_enc      TEXT,                          -- 联系方式(加密)
            inpatient_no     TEXT,                          -- 住院号
            register_date    TEXT NOT NULL,                 -- 建档日期
            physician        TEXT,                          -- 责任医师
            status           TEXT NOT NULL DEFAULT '建档',  -- 建档/在组/随访中/完成/失访/退出
            disease_category TEXT NOT NULL DEFAULT 'CAD_PCI', -- ★v0.2 多病种★
            created_at       TEXT DEFAULT (datetime('now','localtime'))
        )
    """,
    # 手术/事件信息
    "procedure": """
        CREATE TABLE IF NOT EXISTS procedure (
            procedure_id      INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id        INTEGER NOT NULL REFERENCES patient(patient_id),
            proc_date         TEXT,                          -- 手术日期(即 Day 0)
            proc_type         TEXT,                          -- PCI/CABG/瓣膜/起搏器/ICD/无手术
            stent_count       INTEGER,                       -- 支架数
            lesion_vessel_count INTEGER,                     -- 病变支数
            complete_revascularization INTEGER,              -- 1=完全血运重建 0=否
            is_emergency      INTEGER,                       -- 1=急诊 0=择期
            incision_type     TEXT,                          -- 切口类型：经皮/胸骨正中/微创 ★v0.2★
            anticoagulation   TEXT                           -- 抗凝状态 ★v0.2★
        )
    """,
    # 评估记录（含代谢维度全人群纳入）
    "assessment": """
        CREATE TABLE IF NOT EXISTS assessment (
            assessment_id     INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id        INTEGER NOT NULL REFERENCES patient(patient_id),
            disease_category  TEXT NOT NULL DEFAULT 'CAD_PCI', -- ★v0.2★
            assessment_type   TEXT NOT NULL,                -- 基线/1周/1月/3月/6月/12月
            assess_date       TEXT NOT NULL,
            LVEF              REAL,                         -- 左室射血分数 %
            NT_proBNP         REAL,                         -- pg/mL
            LDL_C             REAL,                         -- mmol/L
            HbA1c             REAL,                         -- %
            BP_sys            INTEGER,                      -- 收缩压 mmHg
            BP_dia            INTEGER,                      -- 舒张压 mmHg
            BMI               REAL,
            waist             REAL,                         -- 腰围 cm
            uric_acid         REAL,                         -- 尿酸 μmol/L
            eGFR              REAL,                         -- mL/min/1.73m²
            UACR              REAL,                         -- mg/g
            six_mwd           REAL,                         -- 6分钟步行距离 m
            grip              REAL,                         -- 握力 kg
            sit_stand         INTEGER,                      -- 30秒坐立试验次数
            PHQ9              INTEGER,                      -- 抑郁量表
            GAD7              INTEGER,                      -- 焦虑量表
            adherence_score   INTEGER,                      -- Morisky 依从性评分
            smoking           TEXT,                         -- 吸烟状态
            drinking          TEXT,                         -- 饮酒状态
            diet              TEXT,                         -- 膳食频率
            activity          TEXT,                         -- 活动量
            ecg               TEXT,                         -- 心电图结论(选查)
            echo              TEXT,                         -- 心超结论(选查)
            remark            TEXT
        )
    """,
    # 证型记录
    "tcm_pattern": """
        CREATE TABLE IF NOT EXISTS tcm_pattern (
            pattern_id        INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id        INTEGER NOT NULL REFERENCES patient(patient_id),
            assess_date       TEXT NOT NULL,
            main_pattern      TEXT,                          -- 主证（六证型之一）
            secondary_pattern TEXT,                          -- 兼证
            four_diag_json    TEXT,                          -- 四诊结构化数据(JSON)
            tongue_image_url  TEXT,                          -- 舌象图片路径
            judge_method      TEXT DEFAULT '系统',           -- 系统/医师
            physician_confirm INTEGER NOT NULL DEFAULT 0     -- 1=医师确认
        )
    """,
    # 危险分层
    "risk_stratification": """
        CREATE TABLE IF NOT EXISTS risk_stratification (
            strat_id          INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id        INTEGER NOT NULL REFERENCES patient(patient_id),
            disease_category  TEXT NOT NULL DEFAULT 'CAD_PCI', -- ★v0.2★
            assess_date       TEXT NOT NULL,
            risk_level        TEXT NOT NULL,                -- 低危/中危/高危
            param_version     TEXT,                         -- 所用参数集版本 ★v0.2★
            trigger_json      TEXT,                         -- 触发条件(JSON)
            physician_confirm INTEGER NOT NULL DEFAULT 0    -- 1=医师确认
        )
    """,
    # 康复处方
    "prescription": """
        CREATE TABLE IF NOT EXISTS prescription (
            rx_id             INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id        INTEGER NOT NULL REFERENCES patient(patient_id),
            disease_category  TEXT NOT NULL DEFAULT 'CAD_PCI', -- ★v0.2★
            gen_date          TEXT NOT NULL,
            valid_until       TEXT,                          -- 有效期
            phase             TEXT,                          -- I/II/III
            week_no           INTEGER,                       -- 周次
            matrix_code       TEXT,                          -- 矩阵编码 如 CAD_PCI-A2
            baduanjin_level   TEXT,                          -- 八段锦级别 L0~L3+
            aerobic_type      TEXT,                          -- 有氧类型
            aerobic_duration  INTEGER,                       -- 主体时长(分钟)
            aerobic_freq      INTEGER,                       -- 次/周
            rpe_min           INTEGER,
            rpe_max           INTEGER,
            hr_min            INTEGER,                       -- 目标心率下限
            hr_max            INTEGER,                       -- 目标心率上限
            resistance_json   TEXT,                          -- 抗阻方案(JSON)
            tcm_json          TEXT,                          -- 中医干预(JSON)
            nutrition_json    TEXT,                          -- 营养建议(JSON)
            risk_factor_json  TEXT,                          -- 危险因素目标(JSON)
            physician_sign    TEXT,                          -- 医师签名（签发必填）
            status            TEXT NOT NULL DEFAULT '草稿',  -- 草稿/已签发/已调整/作废
            version           INTEGER NOT NULL DEFAULT 1
        )
    """,
    # 打卡记录
    "adherence_log": """
        CREATE TABLE IF NOT EXISTS adherence_log (
            log_id            INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id        INTEGER NOT NULL REFERENCES patient(patient_id),
            log_date          TEXT NOT NULL,
            task_type         TEXT,                          -- 运动/服药/测量/八段锦
            is_done           INTEGER DEFAULT 0,
            actual_duration   INTEGER,                       -- 实际时长(分钟)
            self_rpe          INTEGER,                       -- 自评RPE 6-20
            symptom_json      TEXT,                          -- 症状标记(JSON)
            remark            TEXT
        )
    """,
    # 自测数据
    "vital_upload": """
        CREATE TABLE IF NOT EXISTS vital_upload (
            upload_id         INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id        INTEGER NOT NULL REFERENCES patient(patient_id),
            measure_time      TEXT NOT NULL,
            data_type         TEXT NOT NULL,                 -- 血压/心率/体重/步数/血糖
            value             REAL NOT NULL,
            source            TEXT DEFAULT '手动'            -- 手动/设备
        )
    """,
    # 预警记录
    "alert": """
        CREATE TABLE IF NOT EXISTS alert (
            alert_id          INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id        INTEGER NOT NULL REFERENCES patient(patient_id),
            trigger_time      TEXT NOT NULL,
            level             TEXT NOT NULL,                 -- 红/黄/蓝
            rule_code         TEXT,                          -- 规则编码
            trigger_data_json TEXT,                          -- 触发数据(JSON)
            notify_target     TEXT,                          -- 通知对象
            notify_time       TEXT,
            handler           TEXT,                          -- 处置人
            handle_time       TEXT,
            handle_content    TEXT,                          -- 处置内容
            status            TEXT NOT NULL DEFAULT '待处置' -- 待处置/处置中/已关闭
        )
    """,
    # 随访计划与记录
    "follow_up": """
        CREATE TABLE IF NOT EXISTS follow_up (
            fu_id             INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id        INTEGER NOT NULL REFERENCES patient(patient_id),
            plan_date         TEXT NOT NULL,                 -- 计划日期
            actual_date       TEXT,                          -- 实际日期
            fu_type           TEXT NOT NULL,                 -- 1周/1月/3月/6月/12月
            status            TEXT NOT NULL DEFAULT '待随访',-- 待随访/已完成/逾期/跳过
            handler           TEXT,                          -- 完成人
            record_json       TEXT                           -- 复评记录(JSON)
        )
    """,
    # 临床事件
    "clinical_event": """
        CREATE TABLE IF NOT EXISTS clinical_event (
            event_id          INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id        INTEGER NOT NULL REFERENCES patient(patient_id),
            event_date        TEXT NOT NULL,
            event_type        TEXT NOT NULL,                 -- 死亡/再入院/再次血运重建/心梗/卒中/出血
            detail            TEXT,
            source            TEXT
        )
    """,
    # ---------- 规则层表（★核心IP★ 规则外置，GUI 可视化维护） ----------
    # 危险分层规则（按病种参数集）
    "rule_stratification": """
        CREATE TABLE IF NOT EXISTS rule_stratification (
            rule_id        INTEGER PRIMARY KEY AUTOINCREMENT,
            disease_category TEXT NOT NULL,
            risk_level     TEXT NOT NULL,                    -- 低危/中危/高危
            condition_json TEXT NOT NULL,                    -- 判定条件(JSON)，满足任一即达此级
            priority       INTEGER DEFAULT 0,
            enabled        INTEGER NOT NULL DEFAULT 1
        )
    """,
    # 证型特征库
    "rule_tcm_pattern": """
        CREATE TABLE IF NOT EXISTS rule_tcm_pattern (
            pattern_id     INTEGER PRIMARY KEY AUTOINCREMENT,
            pattern_name   TEXT NOT NULL UNIQUE,             -- 证型名
            features_json  TEXT NOT NULL,                    -- 主要特征(JSON)
            comorbidity_json TEXT,                           -- 常见合并(JSON)
            enabled        INTEGER NOT NULL DEFAULT 1
        )
    """,
    # 处方模板库（双轴矩阵 A1~F3 × 病种）
    "rule_rx_template": """
        CREATE TABLE IF NOT EXISTS rule_rx_template (
            template_id    INTEGER PRIMARY KEY AUTOINCREMENT,
            disease_category TEXT NOT NULL,
            matrix_code    TEXT NOT NULL,                    -- A1~F3
            pattern        TEXT NOT NULL,                    -- 证型
            risk_level     TEXT NOT NULL,                    -- 低危/中危/高危
            phase          TEXT NOT NULL,                    -- I/II/III
            week_range_json TEXT,                            -- 适用周次 [3,4]
            output_json    TEXT NOT NULL,                    -- FITT-VP 全要素(JSON)
            enabled        INTEGER NOT NULL DEFAULT 1
        )
    """,
    # 八段锦分级
    "rule_baduanjin": """
        CREATE TABLE IF NOT EXISTS rule_baduanjin (
            level_id       INTEGER PRIMARY KEY AUTOINCREMENT,
            level_code     TEXT NOT NULL UNIQUE,             -- L0/L1/L2/L3/L3+
            posture        TEXT NOT NULL,                    -- 卧位/坐位/站位
            moves_json     TEXT NOT NULL,                    -- 招式(JSON)
            met_est        REAL,                             -- 估算强度 METs
            applicable     TEXT,                             -- 适用说明
            enabled        INTEGER NOT NULL DEFAULT 1
        )
    """,
    # 预警规则
    "rule_alert": """
        CREATE TABLE IF NOT EXISTS rule_alert (
            alert_rule_id  INTEGER PRIMARY KEY AUTOINCREMENT,
            rule_code      TEXT NOT NULL UNIQUE,             -- 如 ALERT-R-003
            level          TEXT NOT NULL,                    -- 红/黄/蓝
            name           TEXT NOT NULL,
            condition_json TEXT NOT NULL,                    -- 触发条件(JSON)
            applicable_json TEXT,                            -- 适用范围(病种/证型/分层)
            actions_json   TEXT,                            -- 处置动作(JSON)
            enabled        INTEGER NOT NULL DEFAULT 1
        )
    """,
    # 禁忌规则（通用 + 病种特异）
    "rule_contraindication": """
        CREATE TABLE IF NOT EXISTS rule_contraindication (
            con_id         INTEGER PRIMARY KEY AUTOINCREMENT,
            disease_category TEXT NOT NULL DEFAULT '*',      -- * = 通用
            pattern        TEXT NOT NULL DEFAULT '*',        -- * = 通用
            risk_level     TEXT NOT NULL DEFAULT '*',
            name           TEXT NOT NULL,                    -- 禁忌名称
            rule_json      TEXT NOT NULL,                    -- 禁忌内容(JSON)
            enabled        INTEGER NOT NULL DEFAULT 1
        )
    """,
}

# 业务表 + 规则表全量清单
ALL_TABLES = list(SCHEMA.keys())


# ---------- 连接与初始化 ----------

def get_conn(db_path: str = DB_PATH) -> sqlite3.Connection:
    """获取数据库连接（row 工厂 + 外键开启）。"""
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(db_path: str = DB_PATH) -> None:
    """建库：全部业务表 + 规则层表。可重复执行。"""
    conn = get_conn(db_path)
    try:
        for sql in SCHEMA.values():
            conn.execute(sql)
        conn.commit()
    finally:
        conn.close()


def table_columns(conn: sqlite3.Connection, table: str) -> list:
    """返回表字段名列表。"""
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return [r["name"] for r in rows]


# ---------- 种子数据导入 ----------

def import_seed(db_path: str = DB_PATH, seed_dir: str = SEED_DIR) -> dict:
    """从 data/seed/*.json 导入种子数据到规则层表。
    约定：文件名 = 表名（如 rule_stratification.json）。幂等：先清空目标表再导入。
    返回 {表名: 导入条数}
    """
    if not os.path.isdir(seed_dir):
        return {}
    conn = get_conn(db_path)
    result = {}
    try:
        for fname in sorted(os.listdir(seed_dir)):
            if not fname.endswith(".json"):
                continue
            table = fname[:-5]
            if table not in SCHEMA:
                print(f"[seed] 跳过未知表: {table}")
                continue
            with open(os.path.join(seed_dir, fname), "r", encoding="utf-8") as f:
                rows = json.load(f)
            if not isinstance(rows, list) or not rows:
                print(f"[seed] {table}: 空数据，跳过")
                continue
            cols = table_columns(conn, table)
            cols = [c for c in cols if c != "id"]
            placeholders = ",".join("?" * len(cols))
            colnames = ",".join(cols)
            conn.execute(f"DELETE FROM {table}")
            n = 0
            for row in rows:
                values = [row.get(c) for c in cols]
                conn.execute(
                    f"INSERT INTO {table} ({colnames}) VALUES ({placeholders})",
                    values,
                )
                n += 1
            conn.commit()
            result[table] = n
            print(f"[seed] {table}: {n} 条")
    finally:
        conn.close()
    return result


# ---------- 通用 DAO ----------

def insert_row(conn: sqlite3.Connection, table: str, data: dict) -> int:
    """插入一行，返回自增 id。data 键需与表字段一致。"""
    cols = [c for c in data.keys()]
    placeholders = ",".join("?" * len(cols))
    colnames = ",".join(cols)
    cur = conn.execute(
        f"INSERT INTO {table} ({colnames}) VALUES ({placeholders})",
        [data[c] for c in cols],
    )
    conn.commit()
    return cur.lastrowid


def update_row(conn: sqlite3.Connection, table: str, data: dict, where: str, params: tuple) -> None:
    """按条件更新一行。"""
    sets = ",".join(f"{c}=?" for c in data.keys())
    conn.execute(
        f"UPDATE {table} SET {sets} WHERE {where}",
        [data[c] for c in data.keys()] + list(params),
    )
    conn.commit()


def query(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> list:
    return conn.execute(sql, params).fetchall()


if __name__ == "__main__":
    # 自测：建库并打印全部表字段
    init_db()
    conn = get_conn()
    print(f"数据库: {DB_PATH}")
    for table in ALL_TABLES:
        cols = table_columns(conn, table)
        print(f"  {table:24s} {len(cols)} 字段: {', '.join(cols)}")
    # 加密往返测试
    test = "张三"
    enc = encrypt_text(test)
    print(f"加密测试: '{test}' -> '{enc}' -> '{decrypt_text(enc)}'")
    conn.close()
