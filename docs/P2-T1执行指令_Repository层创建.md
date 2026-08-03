# P2-T1 执行指令：Repository 层创建

> **任务编号**：P2-T1  
> **任务名称**：Repository 层创建（集中全部数据访问 + 加密/解密透明处理）  
> **执行者**：Hermes  
> **设计来源**：`docs/分阶段开发设计与任务列表.md` §3.4.1  
> **预计工作量**：1 天  
> **日期**：2026-08-03

---

## 一、任务边界

### 1.1 本任务做什么

创建 `app/repo.py`，实现 `Repository` 类，集中全部数据库访问。同时修改 `app/ui/main.py` 初始化 `self.repo`。创建 `test/test_repo.py` 集成测试。

### 1.2 本任务不做什么（严格边界）

| 不做 | 原因 |
|------|------|
| ❌ 不修改 `app/engine/` 下任何引擎文件 | 引擎解耦是 P2-T2/T3/T4 的任务 |
| ❌ 不修改 `app/ui/` 下除 `main.py` 外的任何文件 | GUI 适配是 P2-T5 的任务 |
| ❌ 不修改 `app/db.py` 的现有函数 | 保留 `get_conn`/`init_db`/`import_seed`/`encrypt_text`/`decrypt_text` 等函数供 repo 复用 |
| ❌ 不修改现有测试文件 | 测试适配是 P2-T5 的任务 |
| ❌ 不新增任何第三方依赖 | 纯 Python 标准库 + 已有依赖 |

### 1.3 为什么不改引擎和 GUI

P2-T1 只新增 Repository 层，引擎和 GUI 仍用旧方式（`conn` 直连）工作。Repository 就位后，P2-T2 起逐步把引擎函数改成调用 repo，P2-T5 把 GUI 改成调用 repo。这种"增量替换"策略保证每步都能跑全量测试。

---

## 二、新增文件：`app/repo.py`

### 2.1 文件结构

```
app/repo.py
├── class Repository
│   ├── __init__(conn=None)
│   ├── # ---- 规则数据读取（只读）----
│   ├── # ---- Patient CRUD（加密透明处理）----
│   ├── # ---- Procedure ----
│   ├── # ---- Assessment ----
│   ├── # ---- TCM Pattern ----
│   ├── # ---- Risk Stratification ----
│   ├── # ---- Prescription ----
│   ├── # ---- Follow-up ----
│   ├── # ---- Alert ----
│   └── # ---- 通用 DAO ----
```

### 2.2 完整方法清单与实现规格

以下逐个方法给出签名、SQL、实现要点。**严格按此实现，不得自行增减方法。**

---

#### 2.2.1 初始化

```python
class Repository:
    """集中全部数据访问。引擎不碰 conn。加密/解密在此层透明处理。"""

    def __init__(self, conn=None):
        """conn 可注入（测试用），默认从 db.get_conn() 获取。"""
        if conn is None:
            from db import get_conn
            conn = get_conn()
        self.conn = conn
```

---

#### 2.2.2 规则数据读取（只读）

**方法 1：`get_strat_config`**

```python
def get_strat_config(self, disease_category: str) -> dict:
    """读取病种危险分层参数集（解析 JSON）。
    对应旧引擎函数：stratification.load_strat_config(conn, disease_category)
    """
    row = self.conn.execute(
        "SELECT strat_threshold_json FROM disease_config WHERE disease_category=?",
        (disease_category,)
    ).fetchone()
    if not row or not row["strat_threshold_json"]:
        return {}
    return json.loads(row["strat_threshold_json"])
```

**方法 2：`get_patterns`**

```python
def get_patterns(self) -> list:
    """读取全部启用证型特征库（已解析 features_json）。
    对应旧引擎函数：pattern.load_patterns(conn)
    """
    rows = self.conn.execute(
        "SELECT pattern_name, features_json, comorbidity_json FROM rule_tcm_pattern WHERE enabled=1"
    ).fetchall()
    result = []
    for r in rows:
        item = {"pattern_name": r["pattern_name"]}
        feat = json.loads(r["features_json"]) if r["features_json"] else {}
        item["keywords"] = feat.get("keywords", [])
        item["symptoms"] = feat.get("symptoms", [])
        item["tongue"] = feat.get("tongue", [])
        item["pulse"] = feat.get("pulse", [])
        if r["comorbidity_json"]:
            item["comorbidity"] = json.loads(r["comorbidity_json"])
        result.append(item)
    return result
```

**方法 3：`get_pattern_names`**

```python
def get_pattern_names(self) -> list:
    """读取全部证型名列表。"""
    rows = self.conn.execute(
        "SELECT pattern_name FROM rule_tcm_pattern WHERE enabled=1"
    ).fetchall()
    return [r["pattern_name"] for r in rows]
```

**方法 4：`get_pattern_keywords`**

```python
def get_pattern_keywords(self) -> list:
    """读取全部证型 keywords（去重保序，用于生成四诊问卷）。"""
    patterns = self.get_patterns()
    seen = set()
    result = []
    for p in patterns:
        for kw in p.get("keywords", []):
            if kw not in seen:
                seen.add(kw)
                result.append(kw)
    return result
```

**方法 5：`get_rx_template`**

```python
def get_rx_template(self, disease_category: str, matrix_code: str) -> dict:
    """调取处方模板（解析 output_json）。
    对应旧引擎函数：prescription.load_template(conn, disease_category, matrix)
    """
    row = self.conn.execute(
        "SELECT output_json FROM rule_rx_template "
        "WHERE disease_category=? AND matrix_code=? AND enabled=1",
        (disease_category, matrix_code)
    ).fetchone()
    if not row:
        return {}
    return json.loads(row["output_json"])
```

**方法 6：`get_baduanjin_cfg`**

```python
def get_baduanjin_cfg(self, disease_category: str) -> dict:
    """读取八段锦参数集（解析 baduanjin_start_json）。
    对应旧引擎函数：prescription.load_baduanjin_cfg(conn, disease_category)
    """
    row = self.conn.execute(
        "SELECT baduanjin_start_json FROM disease_config WHERE disease_category=?",
        (disease_category,)
    ).fetchone()
    if not row or not row["baduanjin_start_json"]:
        return {}
    return json.loads(row["baduanjin_start_json"])
```

**方法 7：`get_safety_rules`**

```python
def get_safety_rules(self) -> list:
    """读取全部启用禁忌规则（rule_contraindication 表）。
    对应旧引擎函数：safety.check_safety 内部的 SQL 查询
    """
    rows = self.conn.execute(
        "SELECT disease_category, pattern, risk_level, name, rule_json "
        "FROM rule_contraindication WHERE enabled=1"
    ).fetchall()
    result = []
    for r in rows:
        item = {
            "disease_category": r["disease_category"],
            "pattern": r["pattern"],
            "risk_level": r["risk_level"],
            "name": r["name"],
        }
        if r["rule_json"]:
            item["rule"] = json.loads(r["rule_json"])
        result.append(item)
    return result
```

**方法 8：`get_disease_contraindication`**

```python
def get_disease_contraindication(self, disease_category: str) -> dict:
    """读取病种特异禁忌（disease_config.contraindication_json）。
    对应旧引擎函数：safety.check_safety 内部的 SQL 查询
    """
    row = self.conn.execute(
        "SELECT contraindication_json FROM disease_config WHERE disease_category=?",
        (disease_category,)
    ).fetchone()
    if not row or not row["contraindication_json"]:
        return {}
    return json.loads(row["contraindication_json"])
```

**方法 9：`get_alert_rules`**

```python
def get_alert_rules(self) -> list:
    """读取全部启用预警规则（rule_alert 表）。
    对应旧引擎函数：alerts.load_alert_rules(conn)
    """
    rows = self.conn.execute(
        "SELECT rule_code, level, name, condition_json, applicable_json, actions_json "
        "FROM rule_alert WHERE enabled=1"
    ).fetchall()
    result = []
    for r in rows:
        item = {
            "rule_code": r["rule_code"],
            "level": r["level"],
            "name": r["name"],
            "condition": json.loads(r["condition_json"]) if r["condition_json"] else {},
            "applicable": json.loads(r["applicable_json"]) if r["applicable_json"] else {},
            "actions": json.loads(r["actions_json"]) if r["actions_json"] else {},
        }
        result.append(item)
    return result
```

**方法 10：`get_followup_template`**

```python
def get_followup_template(self, disease_category: str) -> list:
    """读取随访节点模板（disease_config.followup_template_json）。
    对应旧 GUI 代码：followup_view._followup_template 中的 SQL
    """
    row = self.conn.execute(
        "SELECT followup_template_json FROM disease_config WHERE disease_category=?",
        (disease_category,)
    ).fetchone()
    if not row or not row["followup_template_json"]:
        return []
    return json.loads(row["followup_template_json"])
```

**方法 11：`get_enabled_diseases`**

```python
def get_enabled_diseases(self) -> list:
    """读取启用的病种列表。
    对应旧 GUI 代码：patient_view._enabled_diseases 中的 SQL
    """
    rows = self.conn.execute(
        "SELECT disease_category FROM disease_config WHERE enabled=1"
    ).fetchall()
    return [r["disease_category"] for r in rows]
```

---

#### 2.2.3 Patient CRUD（加密透明处理）

> **核心原则**：调用方传入/接收的是**明文** name/contact。Repository 内部调用 `db.encrypt_text` / `db.decrypt_text` 透明处理。

**方法 12：`list_patients`**

```python
def list_patients(self) -> list:
    """患者列表（解密后返回 name/contact 明文）。
    对应旧 GUI 代码：patient_view.refresh 中的 SQL + decrypt_text
    """
    rows = self.conn.execute(
        "SELECT patient_id, name_enc, gender, birth_date, contact_enc, "
        "inpatient_no, register_date, physician, status, disease_category "
        "FROM patient ORDER BY register_date DESC"
    ).fetchall()
    result = []
    for r in rows:
        result.append({
            "patient_id": r["patient_id"],
            "name": decrypt_text(r["name_enc"]),
            "gender": r["gender"],
            "birth_date": r["birth_date"],
            "contact": decrypt_text(r["contact_enc"]),
            "inpatient_no": r["inpatient_no"],
            "register_date": r["register_date"],
            "physician": r["physician"],
            "status": r["status"],
            "disease_category": r["disease_category"],
        })
    return result
```

**方法 13：`get_patient`**

```python
def get_patient(self, patient_id: int) -> dict | None:
    """读取单个患者（解密 name/contact）。
    对应旧 GUI 代码：patient_view._load_form 中的 SQL
    """
    row = self.conn.execute(
        "SELECT * FROM patient WHERE patient_id=?", (patient_id,)
    ).fetchone()
    if not row:
        return None
    return {
        "patient_id": row["patient_id"],
        "name": decrypt_text(row["name_enc"]),
        "gender": row["gender"],
        "birth_date": row["birth_date"],
        "contact": decrypt_text(row["contact_enc"]),
        "inpatient_no": row["inpatient_no"],
        "register_date": row["register_date"],
        "physician": row["physician"],
        "status": row["status"],
        "disease_category": row["disease_category"],
        "created_at": row["created_at"],
    }
```

**方法 14：`get_patient_disease_category`**

```python
def get_patient_disease_category(self, patient_id: int) -> str:
    """读取患者病种（分层/处方用）。"""
    row = self.conn.execute(
        "SELECT disease_category FROM patient WHERE patient_id=?", (patient_id,)
    ).fetchone()
    return row["disease_category"] if row else "CAD_PCI"
```

**方法 15：`get_patient_for_pdf`**

```python
def get_patient_for_pdf(self, patient_id: int) -> dict:
    """读取患者信息（PDF 导出用，解密 name）。
    对应旧引擎函数：pdf_export.export_rx_pdf 内部的 SQL
    """
    row = self.conn.execute(
        "SELECT name_enc, gender, birth_date FROM patient WHERE patient_id=?",
        (patient_id,)
    ).fetchone()
    if not row:
        return {}
    return {
        "name": decrypt_text(row["name_enc"]),
        "gender": row["gender"],
        "birth_date": row["birth_date"],
    }
```

**方法 16：`insert_patient`**

```python
def insert_patient(self, data: dict) -> int:
    """新建患者（自动加密 name/contact）。
    data 含 name/contact 明文。
    对应旧 GUI 代码：patient_view._save 中的 encrypt_text + insert_row
    """
    enc_data = dict(data)
    if "name" in enc_data:
        enc_data["name_enc"] = encrypt_text(enc_data.pop("name"))
    if "contact" in enc_data:
        enc_data["contact_enc"] = encrypt_text(enc_data.pop("contact"))
    return insert_row(self.conn, "patient", enc_data)
```

**方法 17：`update_patient`**

```python
def update_patient(self, patient_id: int, data: dict) -> None:
    """更新患者（自动加密 name/contact）。"""
    enc_data = dict(data)
    if "name" in enc_data:
        enc_data["name_enc"] = encrypt_text(enc_data.pop("name"))
    if "contact" in enc_data:
        enc_data["contact_enc"] = encrypt_text(enc_data.pop("contact"))
    update_row(self.conn, "patient", enc_data,
               "patient_id=?", (patient_id,))
```

**方法 18：`delete_patient`**

```python
def delete_patient(self, patient_id: int) -> None:
    """删除患者（含手术信息）。
    注意：外键级联需手动处理（SQLite PRAGMA foreign_keys=ON 已开启，
    但 patient 表无 ON DELETE CASCADE，需手动删 procedure）。
    """
    self.conn.execute("DELETE FROM procedure WHERE patient_id=?", (patient_id,))
    self.conn.execute("DELETE FROM patient WHERE patient_id=?", (patient_id,))
    self.conn.commit()
```

---

#### 2.2.4 Procedure

**方法 19：`get_procedure`**

```python
def get_procedure(self, patient_id: int) -> dict | None:
    """读取最新手术信息。"""
    row = self.conn.execute(
        "SELECT * FROM procedure WHERE patient_id=? "
        "ORDER BY procedure_id DESC LIMIT 1",
        (patient_id,)
    ).fetchone()
    return dict(row) if row else None
```

**方法 20：`get_procedure_complete_revasc`**

```python
def get_procedure_complete_revasc(self, patient_id: int) -> bool:
    """读取完全血运重建标志（分层用）。
    对应旧 GUI 代码：assessment_view._build_clinical 中的 SQL
    """
    row = self.conn.execute(
        "SELECT complete_revascularization FROM procedure "
        "WHERE patient_id=? ORDER BY procedure_id DESC LIMIT 1",
        (patient_id,)
    ).fetchone()
    return bool(row["complete_revascularization"]) if row else False
```

**方法 21：`get_procedure_id`**

```python
def get_procedure_id(self, patient_id: int) -> int | None:
    """读取最新 procedure_id（更新用）。"""
    row = self.conn.execute(
        "SELECT procedure_id FROM procedure WHERE patient_id=? "
        "ORDER BY procedure_id DESC LIMIT 1",
        (patient_id,)
    ).fetchone()
    return row["procedure_id"] if row else None
```

**方法 22：`insert_procedure`**

```python
def insert_procedure(self, data: dict) -> int:
    """新建手术记录。"""
    return insert_row(self.conn, "procedure", data)
```

**方法 23：`update_procedure`**

```python
def update_procedure(self, procedure_id: int, data: dict) -> None:
    """更新手术记录。"""
    update_row(self.conn, "procedure", data,
               "procedure_id=?", (procedure_id,))
```

---

#### 2.2.5 Assessment

**方法 24：`list_assessments`**

```python
def list_assessments(self, patient_id: int) -> list:
    """评估历史列表。"""
    rows = self.conn.execute(
        "SELECT * FROM assessment WHERE patient_id=? ORDER BY assess_date DESC",
        (patient_id,)
    ).fetchall()
    return [dict(r) for r in rows]
```

**方法 25：`get_assessment`**

```python
def get_assessment(self, assessment_id: int) -> dict | None:
    """读取单条评估。"""
    row = self.conn.execute(
        "SELECT * FROM assessment WHERE assessment_id=?", (assessment_id,)
    ).fetchone()
    return dict(row) if row else None
```

**方法 26：`get_latest_phq9`**

```python
def get_latest_phq9(self, patient_id: int) -> int | None:
    """读取最新 PHQ-9（处方预览用）。
    对应旧 GUI 代码：prescription_view._render_detail 中的 SQL
    """
    row = self.conn.execute(
        "SELECT PHQ9 FROM assessment WHERE patient_id=? "
        "ORDER BY assess_date DESC LIMIT 1",
        (patient_id,)
    ).fetchone()
    return row["PHQ9"] if row else None
```

**方法 27：`insert_assessment`**

```python
def insert_assessment(self, data: dict) -> int:
    """新建评估记录。"""
    return insert_row(self.conn, "assessment", data)
```

---

#### 2.2.6 TCM Pattern

**方法 28：`get_latest_confirmed_pattern`**

```python
def get_latest_confirmed_pattern(self, patient_id: int) -> str | None:
    """读取最新医师确认的证型。"""
    row = self.conn.execute(
        "SELECT main_pattern FROM tcm_pattern "
        "WHERE patient_id=? AND physician_confirm=1 "
        "ORDER BY assess_date DESC LIMIT 1",
        (patient_id,)
    ).fetchone()
    return row["main_pattern"] if row else None
```

**方法 29：`get_tcm_pattern_by_date`**

```python
def get_tcm_pattern_by_date(self, patient_id: int, assess_date: str) -> dict | None:
    """按日期读取证型记录。"""
    row = self.conn.execute(
        "SELECT * FROM tcm_pattern WHERE patient_id=? AND assess_date=?",
        (patient_id, assess_date)
    ).fetchone()
    return dict(row) if row else None
```

**方法 30：`insert_tcm_pattern`**

```python
def insert_tcm_pattern(self, data: dict) -> int:
    """新建证型记录。"""
    return insert_row(self.conn, "tcm_pattern", data)
```

---

#### 2.2.7 Risk Stratification

**方法 31：`get_latest_risk_level`**

```python
def get_latest_risk_level(self, patient_id: int) -> str | None:
    """读取最新分层结果。"""
    row = self.conn.execute(
        "SELECT risk_level FROM risk_stratification "
        "WHERE patient_id=? ORDER BY assess_date DESC LIMIT 1",
        (patient_id,)
    ).fetchone()
    return row["risk_level"] if row else None
```

**方法 32：`insert_risk_stratification`**

```python
def insert_risk_stratification(self, data: dict) -> int:
    """新建分层记录。"""
    return insert_row(self.conn, "risk_stratification", data)
```

---

#### 2.2.8 Prescription

**方法 33：`list_prescriptions`**

```python
def list_prescriptions(self, patient_id: int) -> list:
    """处方历史列表。"""
    rows = self.conn.execute(
        "SELECT * FROM prescription WHERE patient_id=? ORDER BY gen_date DESC",
        (patient_id,)
    ).fetchall()
    return [dict(r) for r in rows]
```

**方法 34：`get_prescription`**

```python
def get_prescription(self, rx_id: int) -> dict | None:
    """读取单条处方。"""
    row = self.conn.execute(
        "SELECT * FROM prescription WHERE rx_id=?", (rx_id,)
    ).fetchone()
    return dict(row) if row else None
```

**方法 35：`insert_prescription`**

```python
def insert_prescription(self, data: dict) -> int:
    """新建处方（草稿）。"""
    return insert_row(self.conn, "prescription", data)
```

**方法 36：`update_prescription`**

```python
def update_prescription(self, rx_id: int, data: dict) -> None:
    """更新处方（全字段）。"""
    update_row(self.conn, "prescription", data,
               "rx_id=?", (rx_id,))
```

---

#### 2.2.9 Follow-up

**方法 37：`list_followups`**

```python
def list_followups(self, patient_id: int) -> list:
    """随访计划列表。"""
    rows = self.conn.execute(
        "SELECT * FROM follow_up WHERE patient_id=? ORDER BY plan_date",
        (patient_id,)
    ).fetchall()
    return [dict(r) for r in rows]
```

**方法 38：`list_due_followups`**

```python
def list_due_followups(self) -> list:
    """到期提醒列表（待随访状态）。"""
    rows = self.conn.execute(
        "SELECT f.*, p.name_enc FROM follow_up f "
        "JOIN patient p ON f.patient_id=p.patient_id "
        "WHERE f.status='待随访' AND f.plan_date <= date('now','localtime') "
        "ORDER BY f.plan_date"
    ).fetchall()
    result = []
    for r in rows:
        item = dict(r)
        item["patient_name"] = decrypt_text(r["name_enc"])
        result.append(item)
    return result
```

**方法 39：`get_followup`**

```python
def get_followup(self, fu_id: int) -> dict | None:
    """读取单条随访。"""
    row = self.conn.execute(
        "SELECT * FROM follow_up WHERE fu_id=?", (fu_id,)
    ).fetchone()
    return dict(row) if row else None
```

**方法 40：`list_existing_fu_types`**

```python
def list_existing_fu_types(self, patient_id: int) -> list:
    """读取已有随访类型（避免重复生成）。"""
    rows = self.conn.execute(
        "SELECT fu_type FROM follow_up WHERE patient_id=?", (patient_id,)
    ).fetchall()
    return [r["fu_type"] for r in rows]
```

**方法 41：`insert_followup`**

```python
def insert_followup(self, data: dict) -> int:
    """新建随访计划。"""
    return insert_row(self.conn, "follow_up", data)
```

**方法 42：`update_followup_status`**

```python
def update_followup_status(self, fu_id: int, actual_date: str,
                          handler: str, record_json: str) -> None:
    """标记随访完成。"""
    self.conn.execute(
        "UPDATE follow_up SET actual_date=?, status='已完成', "
        "handler=?, record_json=? WHERE fu_id=?",
        (actual_date, handler, record_json, fu_id)
    )
    self.conn.commit()
```

**方法 43：`get_day0`**

```python
def get_day0(self, patient_id: int) -> str | None:
    """Day 0：手术日期优先，其次建档日期。
    对应旧 GUI 代码：followup_view._day0 中的两段 SQL
    """
    row = self.conn.execute(
        "SELECT proc_date FROM procedure WHERE patient_id=? "
        "ORDER BY procedure_id DESC LIMIT 1",
        (patient_id,)
    ).fetchone()
    if row and row["proc_date"]:
        return row["proc_date"]
    row = self.conn.execute(
        "SELECT register_date FROM patient WHERE patient_id=?",
        (patient_id,)
    ).fetchone()
    return row["register_date"] if row else None
```

---

#### 2.2.10 Alert

**方法 44：`insert_alert`**

```python
def insert_alert(self, patient_id: int, item: dict) -> int:
    """写入预警记录（状态=待处置）。
    对应旧引擎函数：alerts.insert_alert(conn, patient_id, item)
    """
    from db import now_str
    data = {
        "patient_id": patient_id,
        "trigger_time": now_str(),
        "level": item.get("level", ""),
        "rule_code": item.get("rule_code", ""),
        "trigger_data_json": json.dumps(item.get("trigger_data", {}),
                                        ensure_ascii=False),
        "notify_target": item.get("notify_target", ""),
        "status": "待处置",
    }
    return insert_row(self.conn, "alert", data)
```

**方法 45：`list_pending_alerts`**

```python
def list_pending_alerts(self, level: str = None) -> list:
    """待处置预警列表。
    对应旧引擎函数：alerts.pending_alerts(conn, level)
    """
    if level:
        rows = self.conn.execute(
            "SELECT a.*, p.name_enc FROM alert a "
            "JOIN patient p ON a.patient_id=p.patient_id "
            "WHERE a.status='待处置' AND a.level=? "
            "ORDER BY a.trigger_time DESC",
            (level,)
        ).fetchall()
    else:
        rows = self.conn.execute(
            "SELECT a.*, p.name_enc FROM alert a "
            "JOIN patient p ON a.patient_id=p.patient_id "
            "WHERE a.status='待处置' "
            "ORDER BY a.trigger_time DESC"
        ).fetchall()
    result = []
    for r in rows:
        item = dict(r)
        item["patient_name"] = decrypt_text(r["name_enc"])
        result.append(item)
    return result
```

**方法 46：`close_alert`**

```python
def close_alert(self, alert_id: int, handler: str, handle_content: str) -> None:
    """处置并关闭预警（闭环留痕）。
    对应旧引擎函数：alerts.close_alert(conn, alert_id, handler, content)
    """
    from db import now_str
    self.conn.execute(
        "UPDATE alert SET handler=?, handle_time=?, "
        "handle_content=?, status='已关闭' WHERE alert_id=?",
        (handler, now_str(), handle_content, alert_id)
    )
    self.conn.commit()
```

---

#### 2.2.11 通用 DAO

**方法 47：`query_all`**

```python
def query_all(self, sql: str, params: tuple = ()) -> list:
    """通用查询（返回 dict 列表）。供 rules_view.py 使用。"""
    rows = self.conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]
```

**方法 48：`query_one`**

```python
def query_one(self, sql: str, params: tuple = ()) -> dict | None:
    """通用单行查询。"""
    row = self.conn.execute(sql, params).fetchone()
    return dict(row) if row else None
```

**方法 49：`insert_row`**

```python
def insert_row(self, table: str, data: dict) -> int:
    """通用插入。复用 db.insert_row。"""
    from db import insert_row as _insert_row
    return _insert_row(self.conn, table, data)
```

**方法 50：`update_row`**

```python
def update_row(self, table: str, data: dict, where: str, params: tuple) -> None:
    """通用更新。复用 db.update_row。"""
    from db import update_row as _update_row
    _update_row(self.conn, table, data, where, params)
```

---

### 2.3 文件头部 import

```python
# -*- coding: utf-8 -*-
"""
中西医结合心血管康复系统 — Repository 层
集中全部数据访问，引擎不碰 conn。
加密/解密在此层透明处理（调用方传明文）。
"""
import json
from db import encrypt_text, decrypt_text, insert_row, update_row, now_str
```

> **注意**：`encrypt_text`、`decrypt_text`、`insert_row`、`update_row`、`now_str` 从 `db.py` 导入复用，不重复实现。

---

## 三、修改文件：`app/ui/main.py`

### 3.1 改动范围

只改 2 处，不重构其他代码。

### 3.2 改动 1：import 新增

在 `from db import ...` 行之后新增：

```python
from repo import Repository
```

### 3.3 改动 2：`_init_database` 方法末尾

当前代码（第 100 行）：

```python
self.conn = get_conn()
```

改为：

```python
self.conn = get_conn()
self.repo = Repository(self.conn)
```

### 3.4 不改的部分

- 各视图（`PatientView` 等）仍用 `self.conn` 调引擎——这是 P2-T5 才改的
- 不改 Notebook、状态栏、异常处理等任何其他代码

---

## 四、新增文件：`test/test_repo.py`

### 4.1 测试策略

用临时 SQLite 数据库，初始化 + 导入种子，验证 Repository 各方法。

### 4.2 测试用例清单

```python
# -*- coding: utf-8 -*-
"""
Repository 集成测试。
验证：加密透明、JSON 解析、CRUD 正确性、规则读取完整性。
"""
import os
import sys
import json
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db
from repo import Repository


class TestRepoRules(unittest.TestCase):
    """规则数据读取测试。"""

    @classmethod
    def setUpClass(cls):
        cls.db_fd, cls.db_path = tempfile.mkstemp(suffix=".db")
        db.init_db(cls.db_path)
        db.import_seed(cls.db_path)
        cls.conn = db.get_conn(cls.db_path)
        cls.repo = Repository(cls.conn)

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()
        os.close(cls.db_fd)
        os.unlink(cls.db_path)

    def test_get_strat_config(self):
        cfg = self.repo.get_strat_config("CAD_PCI")
        self.assertIsInstance(cfg, dict)
        self.assertIn("levels", cfg)

    def test_get_patterns(self):
        patterns = self.repo.get_patterns()
        self.assertGreaterEqual(len(patterns), 6)
        p0 = patterns[0]
        self.assertIn("pattern_name", p0)
        self.assertIn("keywords", p0)

    def test_get_pattern_keywords(self):
        kws = self.repo.get_pattern_keywords()
        self.assertGreater(len(kws), 0)
        # 去重
        self.assertEqual(len(kws), len(set(kws)))

    def test_get_rx_template(self):
        tpl = self.repo.get_rx_template("CAD_PCI", "CAD_PCI-A2")
        self.assertIsInstance(tpl, dict)
        self.assertIn("aerobic_type", tpl)

    def test_get_baduanjin_cfg(self):
        cfg = self.repo.get_baduanjin_cfg("CAD_PCI")
        self.assertIsInstance(cfg, dict)

    def test_get_safety_rules(self):
        rules = self.repo.get_safety_rules()
        self.assertGreater(len(rules), 0)

    def test_get_alert_rules(self):
        rules = self.repo.get_alert_rules()
        self.assertEqual(len(rules), 16)  # 7红+7黄+2蓝

    def test_get_enabled_diseases(self):
        diseases = self.repo.get_enabled_diseases()
        self.assertIn("CAD_PCI", diseases)


class TestRepoPatientCRUD(unittest.TestCase):
    """患者 CRUD + 加密透明测试。"""

    @classmethod
    def setUpClass(cls):
        cls.db_fd, cls.db_path = tempfile.mkstemp(suffix=".db")
        db.init_db(cls.db_path)
        db.import_seed(cls.db_path)
        cls.conn = db.get_conn(cls.db_path)
        cls.repo = Repository(cls.conn)

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()
        os.close(cls.db_fd)
        os.unlink(cls.db_path)

    def test_insert_and_get_patient(self):
        """插入患者 → 读取 → name 为明文。"""
        pid = self.repo.insert_patient({
            "name": "测试患者",
            "gender": "男",
            "birth_date": "1960-01-01",
            "contact": "13800138000",
            "register_date": "2026-08-03",
            "disease_category": "CAD_PCI",
        })
        self.assertGreater(pid, 0)

        patient = self.repo.get_patient(pid)
        self.assertEqual(patient["name"], "测试患者")  # 明文
        self.assertEqual(patient["contact"], "13800138000")  # 明文

    def test_list_patients_returns_plaintext(self):
        """list_patients 返回明文 name。"""
        self.repo.insert_patient({
            "name": "列表测试",
            "gender": "女",
            "birth_date": "1970-06-15",
            "contact": "13900139000",
            "register_date": "2026-08-03",
            "disease_category": "CAD_PCI",
        })
        patients = self.repo.list_patients()
        self.assertGreaterEqual(len(patients), 1)
        # 所有 name 都是明文（不含 base64 特征）
        for p in patients:
            self.assertNotIn("\\x", p["name"])

    def test_update_patient(self):
        """更新患者 → name 仍为明文。"""
        pid = self.repo.insert_patient({
            "name": "更新前",
            "gender": "男",
            "birth_date": "1955-03-20",
            "contact": "13700137000",
            "register_date": "2026-08-03",
            "disease_category": "CAD_PCI",
        })
        self.repo.update_patient(pid, {"name": "更新后", "status": "在组"})
        patient = self.repo.get_patient(pid)
        self.assertEqual(patient["name"], "更新后")
        self.assertEqual(patient["status"], "在组")

    def test_delete_patient(self):
        """删除患者 → 查不到。"""
        pid = self.repo.insert_patient({
            "name": "删除测试",
            "gender": "男",
            "birth_date": "1965-01-01",
            "contact": "13600136000",
            "register_date": "2026-08-03",
            "disease_category": "CAD_PCI",
        })
        self.repo.delete_patient(pid)
        self.assertIsNone(self.repo.get_patient(pid))


class TestRepoProcedure(unittest.TestCase):
    """手术信息 CRUD。"""

    @classmethod
    def setUpClass(cls):
        cls.db_fd, cls.db_path = tempfile.mkstemp(suffix=".db")
        db.init_db(cls.db_path)
        db.import_seed(cls.db_path)
        cls.conn = db.get_conn(cls.db_path)
        cls.repo = Repository(cls.conn)
        cls.pid = cls.repo.insert_patient({
            "name": "手术测试患者",
            "gender": "男",
            "birth_date": "1960-01-01",
            "contact": "13800138000",
            "register_date": "2026-08-03",
            "disease_category": "CAD_PCI",
        })

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()
        os.close(cls.db_fd)
        os.unlink(cls.db_path)

    def test_insert_and_get_procedure(self):
        self.repo.insert_procedure({
            "patient_id": self.pid,
            "proc_date": "2026-07-15",
            "proc_type": "PCI",
            "stent_count": 2,
            "lesion_vessel_count": 3,
            "complete_revascularization": 1,
            "is_emergency": 0,
        })
        proc = self.repo.get_procedure(self.pid)
        self.assertEqual(proc["proc_type"], "PCI")
        self.assertTrue(self.repo.get_procedure_complete_revasc(self.pid))


class TestRepoAssessmentAndAlert(unittest.TestCase):
    """评估、分层、预警、随访综合测试。"""

    @classmethod
    def setUpClass(cls):
        cls.db_fd, cls.db_path = tempfile.mkstemp(suffix=".db")
        db.init_db(cls.db_path)
        db.import_seed(cls.db_path)
        cls.conn = db.get_conn(cls.db_path)
        cls.repo = Repository(cls.conn)
        cls.pid = cls.repo.insert_patient({
            "name": "综合测试患者",
            "gender": "男",
            "birth_date": "1958-05-10",
            "contact": "13500135000",
            "register_date": "2026-08-03",
            "disease_category": "CAD_PCI",
        })

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()
        os.close(cls.db_fd)
        os.unlink(cls.db_path)

    def test_assessment_insert_and_list(self):
        aid = self.repo.insert_assessment({
            "patient_id": self.pid,
            "assessment_type": "基线",
            "assess_date": "2026-08-03",
            "LVEF": 55,
            "six_mwd": 450,
        })
        self.assertGreater(aid, 0)
        lst = self.repo.list_assessments(self.pid)
        self.assertEqual(len(lst), 1)

    def test_risk_stratification_insert_and_get(self):
        self.repo.insert_risk_stratification({
            "patient_id": self.pid,
            "disease_category": "CAD_PCI",
            "assess_date": "2026-08-03",
            "risk_level": "中危",
        })
        level = self.repo.get_latest_risk_level(self.pid)
        self.assertEqual(level, "中危")

    def test_alert_insert_pending_close(self):
        aid = self.repo.insert_alert(self.pid, {
            "level": "红",
            "rule_code": "ALERT-R-001",
            "trigger_data": {"value": 200},
            "notify_target": "主治医师",
        })
        self.assertGreater(aid, 0)
        pending = self.repo.list_pending_alerts()
        self.assertGreaterEqual(len(pending), 1)
        red_pending = self.repo.list_pending_alerts("红")
        self.assertGreaterEqual(len(red_pending), 1)
        self.repo.close_alert(aid, "张医师", "已处理")
        red_after = self.repo.list_pending_alerts("红")
        # 关闭后待处置少一条
        self.assertEqual(len(red_after), len(red_pending) - 1)

    def test_followup_insert_and_complete(self):
        fu_id = self.repo.insert_followup({
            "patient_id": self.pid,
            "plan_date": "2026-08-10",
            "fu_type": "1周",
            "status": "待随访",
        })
        self.assertGreater(fu_id, 0)
        due = self.repo.list_due_followups()
        self.assertGreaterEqual(len(due), 0)
        self.repo.update_followup_status(fu_id, "2026-08-10", "李治疗师",
                                        json.dumps({"note": "完成"}))
        fu = self.repo.get_followup(fu_id)
        self.assertEqual(fu["status"], "已完成")

    def test_get_day0(self):
        """Day 0：无手术 → 建档日期。"""
        day0 = self.repo.get_day0(self.pid)
        self.assertEqual(day0, "2026-08-03")

    def test_get_patient_for_pdf(self):
        info = self.repo.get_patient_for_pdf(self.pid)
        self.assertEqual(info["name"], "综合测试患者")
        self.assertIn("gender", info)
        self.assertIn("birth_date", info)


if __name__ == "__main__":
    unittest.main(verbosity=2)
```

### 4.3 测试运行命令

```bash
cd D:\AI-Hermes\PROJECTS\中西医结合心血管康复方案包与数字化全程管理系统
python -m pytest test/test_repo.py -v
# 或
python -m unittest test.test_repo -v
```

---

## 五、验收标准（逐条对照）

| # | 验收项 | 验证方法 | 通过标准 |
|---|--------|---------|---------|
| 1 | `app/repo.py` 创建完成 | 文件存在 | 50 个方法全部实现 |
| 2 | Repository 单元测试通过 | `python -m pytest test/test_repo.py -v` | 全绿 |
| 3 | 现有 33 测试全部 0 FAIL | `python -m pytest test/ -v` | 33/33 通过 |
| 4 | 加密透明处理 | `list_patients()` 返回明文 name | name 不含 base64 特征 |
| 5 | `main.py` 新增 `self.repo` | `MainApp` 实例有 `repo` 属性 | `hasattr(app, 'repo')` 为 True |
| 6 | 引擎文件未被修改 | `git diff app/engine/` 无变化 | 空输出 |
| 7 | GUI 视图文件未被修改 | `git diff app/ui/patient_view.py` 等无变化 | 空输出 |
| 8 | `db.py` 未被修改 | `git diff app/db.py` 无变化 | 空输出 |

---

## 六、实现注意事项

### 6.1 JSON 字段解析

所有 `_json` 后缀的数据库字段在 Repository 层解析为 dict/list 后返回。调用方不应再自行 `json.loads`。

涉及的方法：
- `get_strat_config` → `strat_threshold_json`
- `get_patterns` → `features_json`、`comorbidity_json`
- `get_rx_template` → `output_json`
- `get_baduanjin_cfg` → `baduanjin_start_json`
- `get_safety_rules` → `rule_json`
- `get_disease_contraindication` → `contraindication_json`
- `get_alert_rules` → `condition_json`、`applicable_json`、`actions_json`
- `get_followup_template` → `followup_template_json`

### 6.2 加密透明

| 方法 | 加密/解密 | 说明 |
|------|----------|------|
| `insert_patient` | 加密 | 调用方传 `"name": "张三"` → repo 内 `encrypt_text("张三")` → 存入 `name_enc` |
| `update_patient` | 加密 | 同上 |
| `list_patients` | 解密 | 从 `name_enc` 解密 → 返回 `"name": "张三"` |
| `get_patient` | 解密 | 同上 |
| `get_patient_for_pdf` | 解密 | 只解密 name（PDF 不需要 contact） |
| `list_due_followups` | 解密 | JOIN patient 取 `name_enc` → 解密为 `patient_name` |
| `list_pending_alerts` | 解密 | 同上 |

### 6.3 `now_str` 的导入

`now_str()` 在 `db.py` 中定义。Repository 的 `insert_alert` 和 `close_alert` 需要调用它。import 方式：

```python
from db import now_str
```

在方法内部调用，不要在文件顶部导入（避免循环导入风险）。或在文件顶部导入，视实际测试情况调整。

### 6.4 `dict(Row)` 转换

`sqlite3.Row` 对象不能直接被 JSON 序列化。所有返回 Row 的方法需要用 `dict(row)` 或列表推导 `[dict(r) for r in rows]` 转换为普通 dict。

### 6.5 不改 `db.py` 的函数签名

Repository 内部**调用** `db.insert_row`、`db.update_row`、`db.encrypt_text`、`db.decrypt_text`、`db.now_str`、`db.get_conn`，但**不修改**它们的签名或实现。如果发现 `db.py` 的某个函数有 bug，记录下来报告，不在本任务中修。

---

## 七、文件清单

| 文件 | 操作 | 预计行数 |
|------|------|---------|
| `app/repo.py` | **新增** | ~400 行 |
| `app/ui/main.py` | 修改（2 行） | +2 行 |
| `test/test_repo.py` | **新增** | ~200 行 |

---

## 八、执行后检查清单

完成实现后，依次执行以下命令确认：

```bash
# 1. 新增测试全绿
python -m pytest test/test_repo.py -v

# 2. 现有测试全绿（不应有任何变化）
python -m pytest test/test_engine.py test/test_e2e.py test/test_gui.py -v

# 3. 全量测试
python -m pytest test/ -v

# 4. 引擎和 GUI 未被修改
git diff --stat app/engine/
git diff --stat app/ui/patient_view.py app/ui/assessment_view.py app/ui/prescription_view.py app/ui/followup_view.py app/ui/rules_view.py
git diff --stat app/db.py

# 5. repo.py 可独立 import
python -c "from repo import Repository; print('OK')"
```

如果第 4 步有任何输出（非空），说明改了不该改的文件，需要回退。

---

## 九、交付物

完成后交付以下文件给审核方（Ada）：

1. `app/repo.py` — 新增的 Repository 层
2. `app/ui/main.py` — 修改后的主窗口（+2 行）
3. `test/test_repo.py` — Repository 集成测试
4. 全量测试输出日志（33 + 新增 = 全绿）
