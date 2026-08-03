# -*- coding: utf-8 -*-
"""
GUI 逻辑层回归测试（验收报告建议 9：覆盖 4 个 P1 修复路径）
- P1-1: patient_view._load_form 对 Entry/Combobox 混合清空不再崩溃
- P1-2: prescription_view._sign 显式 simpledialog（不依赖导入顺序）
- P1-3: _save_draft 全字段更新（医师调整持久化）
- P1-4: alerts 引擎 consecutive_met 操作符（蓝色激励触发）
独立测试库 + 隐藏 Tk root（root.withdraw），不触碰主库、不弹窗。
运行：python -m unittest test.test_gui -v
"""
import os
import sys
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "app"))

TEST_DB = os.path.join(ROOT, "data", "test_rehab.db")

# tkinter 缺失时跳过 GUI 测试（B-2：部分精简 Python 发行版不含 tkinter，
# 如 WorkBuddy managed Python 3.13；本机 python 3.11 含 tkinter 全量运行）
try:
    import tkinter as tk  # noqa: E402
    TK_AVAILABLE = True
except ImportError:
    TK_AVAILABLE = False

from db import init_db, get_conn, import_seed, insert_row, encrypt_text  # noqa: E402
from engine.prescription import build_prescription  # noqa: E402
from engine.alerts import evaluate_alerts  # noqa: E402
from repo import Repository  # noqa: E402


@unittest.skipIf(not TK_AVAILABLE, "当前 Python 环境无 tkinter，GUI 回归测试跳过")
class GuiTestBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.path.exists(TEST_DB):
            os.remove(TEST_DB)
        init_db(TEST_DB)
        import_seed(TEST_DB)
        cls.conn = get_conn(TEST_DB)
        # 测试患者（张三：PCI 术后）
        cls.pid = insert_row(cls.conn, "patient", {
            "name_enc": encrypt_text("张三"), "gender": "男", "birth_date": "1960-05-01",
            "contact_enc": encrypt_text("13800000000"), "inpatient_no": "ZY20260001",
            "register_date": "2026-07-28", "physician": "李医师", "status": "在组",
            "disease_category": "CAD_PCI",
        })
        insert_row(cls.conn, "procedure", {
            "patient_id": cls.pid, "proc_date": "2026-07-28", "proc_type": "PCI",
            "stent_count": 2, "lesion_vessel_count": 1, "complete_revascularization": 1,
            "is_emergency": 0, "incision_type": "经皮", "anticoagulation": "DAPT",
        })
        # 评估 + 分层（供处方自动填充）
        insert_row(cls.conn, "assessment", {
            "patient_id": cls.pid, "disease_category": "CAD_PCI", "assessment_type": "基线",
            "assess_date": "2026-07-30", "LVEF": 52, "six_mwd": 600,
        })
        insert_row(cls.conn, "tcm_pattern", {
            "patient_id": cls.pid, "assess_date": "2026-07-30", "main_pattern": "气虚血瘀",
            "physician_confirm": 1,
        })
        insert_row(cls.conn, "risk_stratification", {
            "patient_id": cls.pid, "disease_category": "CAD_PCI", "assess_date": "2026-07-30",
            "risk_level": "中危", "physician_confirm": 1,
        })
        # 隐藏 Tk root（GUI 视图共用）
        cls.root = tk.Tk()
        cls.root.withdraw()
        cls.repo = Repository(cls.conn)
        cls.app_stub = SimpleNamespace(conn=cls.conn, set_status=lambda s: None,
                                       repo=cls.repo)

    @classmethod
    def tearDownClass(cls):
        cls.root.destroy()
        cls.conn.close()
        if os.path.exists(TEST_DB):
            os.remove(TEST_DB)


class TestP1_1LoadForm(GuiTestBase):
    def test_load_form_entry_combobox_mix(self):
        """P1-1 回归：_load_form 混合 Entry/Combobox 清空不崩溃，字段正确载入。"""
        from ui.patient_view import PatientView
        with patch("ui.patient_view.messagebox"):
            pv = PatientView(self.root, self.app_stub)
            pv.refresh()
            # 真实路径：点击列表 → selection_set 触发事件 → _load_form
            pv.tree.selection_set(str(self.pid))
            pv._load_form()
            # patient 字段（Entry 明文解密）
            self.assertEqual(pv.vars["name"].get(), "张三")
            self.assertEqual(pv.vars["inpatient_no"].get(), "ZY20260001")
            # procedure 字段（Combobox + Entry 混合）
            self.assertEqual(pv.pvars["proc_type"].get(), "PCI")
            self.assertEqual(pv.pvars["stent_count"].get(), "2")
            self.assertEqual(pv.pvars["incision_type"].get(), "经皮")
            self.assertTrue(pv.flag_complete.get())
            pv.destroy()

    def test_load_form_no_procedure(self):
        """无手术记录时清空不崩溃。"""
        from ui.patient_view import PatientView
        with patch("ui.patient_view.messagebox"):
            pid2 = insert_row(self.conn, "patient", {
                "name_enc": encrypt_text("李四"), "register_date": "2026-08-01",
                "disease_category": "CAD_PCI"})
            pv = PatientView(self.root, self.app_stub)
            pv.refresh()
            pv.tree.selection_set(str(pid2))
            pv._load_form()
            self.assertEqual(pv.pvars["proc_type"].get(), "")
            pv.destroy()
            self.conn.execute("DELETE FROM patient WHERE patient_id=?", (pid2,))
            self.conn.commit()


class TestP1_3FullFieldSave(GuiTestBase):
    def test_adjustment_persisted(self):
        """P1-3 回归：保存草稿全字段更新，医师调整持久化。"""
        from ui.prescription_view import PrescriptionView
        with patch("ui.prescription_view.messagebox"):
            pv = PrescriptionView(self.root, self.app_stub)
            pv.current_pid = self.pid
            rx = build_prescription(self.repo.get_rx_template("CAD_PCI", "CAD_PCI-A2"),
                            self.repo.get_baduanjin_cfg("CAD_PCI"),
                            "CAD_PCI", "气虚血瘀", "中危",
                            phase="II", week_no=2, resting_hr=60, age=65)
            rx["patient_id"] = self.pid
            pv.current_rx = rx
            pv._save_draft()
            rid = pv.current_rx["rx_id"]
            self.assertIsNotNone(rid)
            # 医师调整时长 25→33，再保存
            pv.current_rx["aerobic_duration"] = 33
            pv._save_draft()
            row = self.conn.execute(
                "SELECT aerobic_duration, rpe_min, baduanjin_level FROM prescription WHERE rx_id=?",
                (rid,)).fetchone()
            self.assertEqual(row["aerobic_duration"], 33)
            self.assertEqual(row["rpe_min"], 11)
            self.assertEqual(row["baduanjin_level"], "L1")
            pv.destroy()


class TestP1_2Sign(GuiTestBase):
    def test_sign_with_simpledialog(self):
        """P1-2 回归：签发走显式 simpledialog，不依赖导入顺序。"""
        from ui.prescription_view import PrescriptionView
        rx = build_prescription(self.repo.get_rx_template("CAD_PCI", "CAD_PCI-A2"),
                            self.repo.get_baduanjin_cfg("CAD_PCI"),
                            "CAD_PCI", "气虚血瘀", "中危", phase="II", week_no=1)
        rx["patient_id"] = self.pid
        rx["status"] = "草稿"
        rid = insert_row(self.conn, "prescription", rx)
        with patch("ui.prescription_view.messagebox"), \
             patch("ui.prescription_view.simpledialog.askstring", return_value="李医师"):
            pv = PrescriptionView(self.root, self.app_stub)
            pv.current_rx = {"rx_id": rid, "patient_id": self.pid, "status": "草稿"}
            pv._sign()
            row = self.conn.execute(
                "SELECT status, physician_sign FROM prescription WHERE rx_id=?", (rid,)).fetchone()
            self.assertEqual(row["status"], "已签发")
            self.assertEqual(row["physician_sign"], "李医师")
            pv.destroy()

    def test_sign_blank_rejected(self):
        """签发签名为空被拒绝（不可跳过）。"""
        from ui.prescription_view import PrescriptionView
        with patch("ui.prescription_view.messagebox") as mb, \
             patch("ui.prescription_view.simpledialog.askstring", return_value="   "):
            pv = PrescriptionView(self.root, self.app_stub)
            pv.current_rx = {"rx_id": 99999, "patient_id": self.pid, "status": "草稿"}
            pv._sign()
            mb.showwarning.assert_called()  # 拦截提示
            pv.destroy()


class TestP1_4ConsecutiveMet(GuiTestBase):
    def test_blue_incentive_triggers(self):
        """P1-4 回归：consecutive_met 操作符实现，蓝色激励可触发。"""
        trig = evaluate_alerts(self.repo.get_alert_rules(), "CAD_PCI", "气虚血瘀", "中危", {"streak": 3})
        codes = [t["rule_code"] for t in trig]
        self.assertIn("ALERT-B-001", codes)

    def test_blue_not_trigger_below_count(self):
        trig = evaluate_alerts(self.repo.get_alert_rules(), "CAD_PCI", "气虚血瘀", "中危", {"streak": 0})
        self.assertNotIn("ALERT-B-001", [t["rule_code"] for t in trig])


if __name__ == "__main__":
    unittest.main(verbosity=2)
