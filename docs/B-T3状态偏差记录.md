# B-T3 状态偏差记录：HerMes 混淆 tkinter 与 React 开发主线

> **发现时间**：2026-08-04 10:34  
> **发现者**：用户（Lenci）+ 交付总监（Qi）  
> **严重程度**：中等 — 方向性偏差（投入旧框架而非新路线），但投入量小（两个提交），可纠正

---

## 1. 偏差描述

用户反馈"B-T3 做了但看到的还是 tkinter"。经核实：

| 应该做的（B-T3 标准） | 实际发生 |
|---------------------|---------|
| React 评估录入前端页面 `frontend/src/pages/Assessment.jsx` | ❌ 不存在 |
| Playwright e2e 测试评估流程 | ❌ 不存在 |
| 对接现有 `app/api/assessment.py` 后端 API | ❌ 未对接 |
| — | ✅ `5a0d28a` tkinter 评估页布局修正（grid weight + sticky） |
| — | ✅ `64e2323` tkinter 评估页滚轮支持 |

**HerMes 把"评估相关改动"等同于 B-T3，但做的是 tkinter（路线 C 范畴），而非 React 前端（路线 B 主线）。**

## 2. 影响评估

| 维度 | 评估 |
|------|------|
| 浪费的工作量 | 两个提交（布局修正 + 滚轮），约 0.5 天 |
| 对路线 B 的阻塞 | 无 — B-T3 真正的 React 前端还未开工 |
| 可补救性 | 高 — `app/api/assessment.py` 后端 API 已存在可直接复用 |
| 旧框架债务 | 轻微 — tkinter 评估页的改进对后续无价值（路线 B 下 tkinter 整体淘汰） |

## 3. 现状

- `frontend/src/pages/` 仅有 `Login.jsx` + `Patients.jsx`（B-T2 成果）
- `app/api/assessment.py` 已存在（后端就绪）
- B-T3（React 评估录入前端）**尚未启动**

## 4. 纠正措施

1. **停止所有 tkinter 页面的改进**（路线 B 已锁定，tkinter 将整体淘汰）
2. **启动真正的 B-T3**：`frontend/src/pages/Assessment.jsx` + Playwright e2e，对接 `app/api/assessment.py`
3. 后续 B-T4~B-T7 同理——全部走 React 前端，不再碰 tkinter

## 5. 教训

任务命名规范需要强化：B-T3 的正式名称是"评估录入 **React** 前端 + 测试"，不能简称为"评估录入"——HerMes 收到"评估录入"四个字后，可能不理解"前端框架已切换"，继续在 tkinter 上开发。
