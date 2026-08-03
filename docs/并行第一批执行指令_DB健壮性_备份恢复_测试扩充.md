# 并行第一批执行指令：DB 健壮性 + 备份恢复 + 测试扩充

> **定位**：P4 决策备忘（闸门）等待期间，可并行推进的"技术栈无关"工程债。任何路线（A/B/C）下都不浪费。
> **编制**：交付总监（Qi） · **执行**：Hermes · **审核**：交付总监（Qi） + 用户（Lenci）
> **日期**：2026-08-03
> **前置状态**：P2 已完成（102 tests 基线 OK）；P3 已实现（auth/security/log/config）；`delete_patient` 已按保护性拒绝方案修复并补测（P2 遗留关闭）
> **配套**：`docs/P4开发策略建议.md`、`docs/P4开发设计文档.md`

---

## 0. 任务总览

| 线 | 内容 | 来源 | 涉及文件 | 工作量 |
|----|------|------|---------|--------|
| ② | DB 健壮性：启动健康检查 + locked 重试 | PRD P2 功能 6/7 | `app/db.py`、`app/ui/main.py` | 0.5-1 天 |
| ③ | 数据备份与恢复 | PRD P4 功能 6（单机版） | `app/backup.py`（新增）、`app/ui/main.py` | 1-2 天 |
| ⑤ | 测试扩充：矩阵边界 + 预警操作符 | .hermes.md 测试纪律 | `test/test_engine_pure.py`、`test/test_alerts_operators.py`（新增） | 0.5-1 天 |

**总计**：2-4 天，三条线互不依赖，可并行执行。

### 红线（本批不可越界）

- ❌ 不改引擎 6 文件（`app/engine/` 全部只读引用）
- ❌ 不改 `app/repo.py` 现有方法签名（仅可在通用 DAO 内接入重试，见 ②-2）
- ❌ 不改 `app/auth.py` / `app/security.py` / `app/log.py`（P3 已定稿）
- ✅ 允许动 `app/ui/main.py`（健康检查接入 + 备份按钮，最小改动 ≤30 行）
- ✅ 允许新增 `app/backup.py`、`test/test_alerts_operators.py`
- ✅ 允许在 `test/test_engine_pure.py` 追加测试类

### 回归红线（硬门槛）

**执行完成后，全部测试 0 FAIL 0 ERROR**（本审核环境 102+；用户有 tkinter 环境 109+）。每完成一条线跑一次全量测试。

---

## 1. 线② DB 健壮性（PRD P2 功能 6/7）

### ②-1 启动健康检查（PRD P2 功能 6：P1）

**现状**：`db.py` 已有 `get_conn()`（timeout=5.0 + WAL + foreign_keys），`main.py` 的 `_init_database()` 只 try 了规则表计数，**无 DB 完整性检查**。库损坏时启动直接崩溃。

**实现规格**：`app/db.py` 新增函数

```python
def check_db_health(db_path: str = DB_PATH) -> tuple[bool, str]:
    """启动时数据库健康检查。
    返回 (是否正常, 描述信息)。
    检查项：
      1. 文件存在性（不存在 → (False, "数据库文件不存在: xxx")）
      2. 能否打开连接（失败 → (False, "无法打开数据库: <异常>")）
      3. PRAGMA quick_check（结果非 "ok" → (False, "完整性校验失败: <结果>")）
    全部通过 → (True, "ok")
    注意：用 quick_check 而非 integrity_check（启动场景要快）；
          只读方式检查，不触发写锁。
    """
```

要点：
- 打开连接时同样设置 `timeout`（短一些，如 2.0），避免检查本身卡锁
- `PRAGMA quick_check` 返回单行结果，`"ok"` 即正常
- 函数不抛异常，所有失败路径返回 `(False, msg)`

**`app/ui/main.py` 改动**（`_init_database()` 内，`init_db()` 调用前插入）：

```python
ok, msg = check_db_health()
if not ok:
    proceed = messagebox.askyesno(
        "数据库异常",
        f"数据库健康检查未通过：\n{msg}\n\n是否仍尝试启动？（建议先备份数据）")
    if not proceed:
        sys.exit(1)
```

- 提示而非静默崩溃（PRD 原文："损坏时提示而非崩溃"）
- 用户选"否"则退出；选"是"继续尝试（SQLite 可能部分可读）

**测试**：`test/test_repo.py` 或新建 `test/test_db_health.py`（推荐新建，归属清晰）：

| 用例 | 断言 |
|------|------|
| 正常库（临时建库） | `(True, "ok")` |
| 不存在的路径 | `(False, ...)`，且不抛异常 |
| 损坏库（写入垃圾字节后检查） | `(False, ...)`，且不抛异常 |

### ②-2 "database is locked" 重试（PRD P2 功能 7：P2）

**现状**：`get_conn()` 已设 `timeout=5.0`（sqlite3 内置忙等待，能覆盖大部分瞬时锁），但**锁超时后直接抛 `OperationalError`，无显式重试**。

**实现规格**：`app/db.py` 新增

```python
def execute_with_retry(conn, sql: str, params: tuple = (),
                       retries: int = 3, base_delay: float = 0.2):
    """执行 SQL，遇 "database is locked"（OperationalError）时指数退避重试。
    重试间隔：base_delay * 2^n（0.2s / 0.4s / 0.8s）。
    retries 次后仍失败 → 原样抛出。
    非 locked 错误 → 立即抛出，不重试。
    """
```

要点：
- 只匹配 `sqlite3.OperationalError` 且 `"locked" in str(e)` 才重试
- 重试间 `time.sleep(delay)`（指数退避）
- 其他异常不吞

**接入点**（最小改动原则）：仅接入 `app/repo.py` 的通用写 DAO（`insert_row` / `update_row` / `delete_row` 三处），把 `self.conn.execute(...)` 换为 `execute_with_retry(self.conn, ...)`。**不**逐个改 50 个业务方法（那是大 diff，非本批目标）。

**测试**（`test/test_db_health.py`）：

| 用例 | 做法 | 断言 |
|------|------|------|
| locked 重试成功 | 连接 A 开 `BEGIN IMMEDIATE` 持写锁 → 连接 B 用 `execute_with_retry` 写（retries 调大）→ A 提交释放 | B 最终写入成功 |
| 非 locked 错误不重试 | 传非法 SQL | 立即抛错（可通过计时/mock 验证未 sleep） |
| retries 耗尽抛原错 | mock `time.sleep`，构造持续锁 | 抛 `OperationalError` |

> 测试中用短 timeout 连接（如 0.2s）模拟真实锁冲突，避免测试等待 5 秒。

---

## 2. 线③ 数据备份与恢复（PRD P4 功能 6 单机版）

**背景**：PRD P4 功能 6 原文写"自动定时备份（pg_dump）+ 手动备份 + 恢复验证"——那是 **PostgreSQL 路线（P4-B）** 的方案。当前单机 SQLite 阶段，备份须用 **SQLite 官方 backup API**（`sqlite3.Connection.backup()`），它保证 WAL 模式下未 checkpoint 的数据也一致入库，**不能用文件复制**（WAL 下复制会丢最近数据）。

### ③-1 备份模块：`app/backup.py`（新增）

```python
DEFAULT_BACKUP_DIR = "data/backups"   # 相对项目根，经 db._default_path 解析

def backup_db(source_path: str, backup_dir: str = None, max_backups: int = 7) -> str:
    """一致性备份数据库。
    用 sqlite3 backup API（src.backup(dst)），WAL 安全。
    文件名：rehab_backup_YYYYMMDD_HHMMSS.db
    备份后调用 prune_backups 清理超出 max_backups 的旧备份。
    返回备份文件完整路径。
    """

def list_backups(backup_dir: str = None) -> list[dict]:
    """列出备份文件。每项 {path, filename, size_bytes, mtime}，按 mtime 降序。"""

def prune_backups(backup_dir: str = None, max_backups: int = 7) -> list[str]:
    """保留最新的 max_backups 个，删除更旧的。返回被删除文件路径列表。"""

def restore_db(backup_path: str, target_path: str = None) -> None:
    """恢复：目标库已存在则先备份为 target_path.bak_before_restore_<ts>.db，
    再用 backup_path 覆盖 target_path。
    恢复前校验 backup_path 是合法 SQLite 文件（可打开）。
    """
```

要点：
- `backup_db` 用 `src = sqlite3.connect(source_path); dst = sqlite3.connect(backup_path); src.backup(dst)`，备份期间源库可被其他连接继续读写（backup API 在线备份）
- 备份目录不存在则 `os.makedirs`
- `restore_db` 的"恢复前先备份当前库"是医疗数据底线（防止误恢复覆盖现有数据）
- 备份文件名时间戳用 `datetime.now().strftime("%Y%m%d_%H%M%S")`

### ③-2 GUI 入口：`app/ui/main.py`（最小改动）

标题栏右侧（用户栏旁）加一个「备份」按钮（±15 行）：

```python
tk.Button(header, text="备份数据", command=self._backup_now,
          bg="#8B2F2F", fg="white", relief="flat").pack(side="right", padx=8)

def _backup_now(self):
    """手动备份：调 backup.backup_db，结果弹窗提示。"""
    try:
        path = backup_db()
        self.set_status(f"备份完成：{os.path.basename(path)}")
        messagebox.showinfo("备份完成", f"数据已备份到：\n{path}")
    except Exception as e:
        _logger.error("备份失败: %s", e)
        messagebox.showerror("备份失败", str(e))
```

- 手动备份为主（P3 权限：管理员可见；非管理员隐藏——沿用 `_apply_permissions` 模式，`can_backup` 用 `backup:run` 权限，P3 权限矩阵已有 `data:backup` 类似项，按实际角色 JSON 匹配）
- 定时备份（APScheduler）不在本批——那是 P4-B 路线的部署态需求，单机手动备份已满足"可用"

### ③-3 测试：`test/test_backup.py`（新增）

| 用例 | 做法 | 断言 |
|------|------|------|
| 备份成功 + 文件存在 | 临时库插入数据 → backup_db | 返回路径存在，文件非空 |
| WAL 数据完整备份 | 连接写数据不 commit 关闭（WAL 有未 checkpoint 数据）→ backup → 新连接打开备份 | 数据完整（验证 backup API 一致性） |
| prune 保留最新 N 个 | 生成 5 个备份 → max_backups=3 | 仅保留 3 个，删除顺序正确（最旧先删） |
| restore 恢复数据 | 库 A 写数据 → backup → 删数据 → restore | 数据恢复，且恢复前原库先被 .bak 备份 |
| restore 非法文件拒绝 | 传非 SQLite 文件 | 抛 ValueError，不覆盖目标库 |

---

## 3. 线⑤ 测试扩充

**背景**：现有纯逻辑 24 用例（`test_engine_pure.py`）覆盖了 stratify 6 / pattern 4 / prescription 7 / safety 3 / alerts 4。缺口：**① 18 格矩阵边界未全遍历；② 预警 12 个操作符只测了 2 个（gte / consecutive_met）**。

### ⑤-1 矩阵边界遍历：`test/test_engine_pure.py` 追加

```python
class TestMatrixBoundary(unittest.TestCase):
    """18 格矩阵（6 证型 × 3 分层）边界遍历（纯逻辑，不碰 DB）。"""

    def test_matrix_code_all_18_combinations(self):
        # 6 证型编码 × 3 分层 → 18 个合法 matrix_code（如 CAD_PCI-A1 ... F3）
        # 断言：格式 ^[A-F][1-3]$，且组合数 = 18
        ...

    def test_build_prescription_all_templates_ok(self):
        # 构造 18 个最小 template dict（同 TEMPLATE 结构，baduanjin_level/aerobic/resistance/tcm）
        # 每个都过 build_prescription（phase=II，无安全禁忌）→ 不抛异常，返回结构含必填键
        ...
```

要点：
- 证型编码固定为 6 个常量（A-F），分层 3 个（1-3），全遍历
- template 用现有 `TEMPLATE` dict 结构循环构造（每格只改 baduanjin_level 按分层映射：低危 L2 / 中危 L1 / 高危 L0）
- 纯逻辑，不建 DB

### ⑤-2 预警操作符覆盖：`test/test_alerts_operators.py`（新增）

先读 `app/engine/alerts.py` 的 `_eval_condition` 确认已实现的操作符全集（当前应有：`eq / out_of_range / gte / lt / delta_increase / delta_pct_increase / consecutive_gte / sustained_range / any_not_met / consecutive_missed / days_before / consecutive_met`），对**每个操作符至少补 1 个触发 + 1 个不触发用例**：

| 操作符 | 至少覆盖 |
|--------|---------|
| eq / out_of_range / gte / lt | 基础边界（含等于边界值） |
| delta_increase / delta_pct_increase | 较上次升高触发；降低不触发 |
| consecutive_gte | 连续 N 次达到触发；中断不触发 |
| sustained_range | 持续处于区间触发；出区间不触发 |
| any_not_met | 任一未达标触发；全达标不触发 |
| consecutive_missed | 连续 N 次未完成触发；中断不触发 |
| days_before | 距某日期 N 天内触发；超过不触发 |

要点：
- 复用 `ALERT_RULES` 的 rule dict 结构，直接构造 condition 调 `evaluate_alerts`（纯逻辑版签名）
- 与 `test_engine_pure.py` 保持同风格（构造 dict，不碰 DB）
- 若发现某操作符在 `_eval_condition` 中**未实现**（返回 False 或抛错）→ **记录为缺陷报告给交付总监**，不擅自实现引擎代码（红线：不改引擎）

---

## 4. 验收标准清单

| # | 验收项 | 判定 |
|---|--------|------|
| A1 | `check_db_health` 三用例通过（正常/不存在/损坏） | 测试绿 |
| A2 | `execute_with_retry` 三用例通过（重试成功/非locked不重试/耗尽抛错） | 测试绿 |
| A3 | main.py 启动接入健康检查，损坏时弹窗且可选退出 | 代码审查 + 冒烟 |
| A4 | `backup_db` 备份文件存在且 WAL 数据完整 | 测试绿 |
| A5 | `restore_db` 恢复一致且先备份当前库 | 测试绿 |
| A6 | prune 保留最新 N 个 | 测试绿 |
| A7 | main.py「备份」按钮可用，结果提示 | 冒烟 |
| A8 | 18 格矩阵全遍历用例通过 | 测试绿 |
| A9 | 预警操作符全覆盖用例通过（12 操作符） | 测试绿 |
| A10 | **全量测试 0 FAIL 0 ERROR**（102+ 用例） | 回归红线 |

---

## 5. 执行顺序建议

三条线互不依赖，可并行。单线程执行建议：

```
线②（db.py 改动 + main.py 接入 + 测试）→ 全量测试 → 线③（backup.py + main.py 按钮 + 测试）→ 全量测试 → 线⑤（两个测试文件）→ 全量测试
```

每完成一条线跑一次全量测试，回归红线不后置。

---

## 6. 交付物清单

| 文件 | 操作 |
|------|------|
| `app/db.py` | 修改：+`check_db_health` +`execute_with_retry` |
| `app/backup.py` | 新增：备份/列表/清理/恢复 |
| `app/ui/main.py` | 修改：健康检查接入 + 备份按钮（≤30 行） |
| `test/test_db_health.py` | 新增：② 两个功能的测试 |
| `test/test_backup.py` | 新增：③ 五个测试 |
| `test/test_engine_pure.py` | 修改：追加 TestMatrixBoundary |
| `test/test_alerts_operators.py` | 新增：⑤-2 操作符覆盖 |

执行完成后按 §4 验收清单逐项自检，报告每条线的通过情况。
