# -*- coding: utf-8 -*-
"""
B-T1 API 测试：认证（login/me）+ 患者 CRUD + RBAC 权限。
测试注入临时库 repo + 固定密钥 auth，不触碰主库。
"""
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "app"))

import db  # noqa: E402
from repo import Repository  # noqa: E402
from security import SecurityManager  # noqa: E402
from auth import AuthManager  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


class ApiBase(unittest.TestCase):
    """临时库 + 用户 + TestClient。"""

    @classmethod
    def setUpClass(cls):
        fd, cls.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        db.init_db(cls.db_path)
        db.import_seed(cls.db_path)
        cls.conn = db.get_conn(cls.db_path)
        cls.repo = Repository(cls.conn)
        cls.sec = SecurityManager(key=b"8" * 32)
        cls.auth = AuthManager(cls.repo, cls.sec)
        cls.repo.create_user("admin", cls.sec.hash_password("Admin@1234"), "管理员", "管理员")
        cls.repo.create_user("therapist", cls.sec.hash_password("Thera@1234"), "治疗师", "治疗师")
        from api.main import create_app
        cls.app = create_app(repo=cls.repo, auth_manager=cls.auth)
        cls.client = TestClient(cls.app)

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()
        os.unlink(cls.db_path)

    def _login(self, username="admin", password="Admin@1234") -> str:
        r = self.client.post("/api/auth/login",
                             json={"username": username, "password": password})
        self.assertEqual(r.status_code, 200)
        return r.json()["token"]

    def _auth_headers(self, token: str) -> dict:
        return {"Authorization": f"Bearer {token}"}


class TestAuth(ApiBase):
    def test_health(self):
        r = self.client.get("/api/health")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["status"], "ok")

    def test_login_success(self):
        r = self.client.post("/api/auth/login",
                             json={"username": "admin", "password": "Admin@1234"})
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertIn("token", data)
        self.assertEqual(data["role"], "管理员")

    def test_login_wrong_password(self):
        r = self.client.post("/api/auth/login",
                             json={"username": "admin", "password": "错误"})
        self.assertEqual(r.status_code, 401)

    def test_me(self):
        token = self._login()
        r = self.client.get("/api/auth/me", headers=self._auth_headers(token))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["username"], "admin")

    def test_me_unauthorized(self):
        r = self.client.get("/api/auth/me")
        self.assertEqual(r.status_code, 401)


class TestPatientCrud(ApiBase):
    def test_list_requires_auth(self):
        r = self.client.get("/api/patients")
        self.assertEqual(r.status_code, 401)

    def test_create_and_list(self):
        token = self._login()
        r = self.client.post("/api/patients", headers=self._auth_headers(token), json={
            "name": "API患者", "gender": "男", "birth_date": "1960-01-01",
            "contact": "13912345678", "register_date": "2026-08-03",
            "disease_category": "CAD_PCI",
        })
        self.assertEqual(r.status_code, 201)
        pid = r.json()["patient_id"]
        # 列表含明文姓名
        r2 = self.client.get("/api/patients", headers=self._auth_headers(token))
        self.assertEqual(r2.status_code, 200)
        names = [p["name"] for p in r2.json()]
        self.assertIn("API患者", names)
        # 数据库 AES 密文（非明文）
        row = self.conn.execute(
            "SELECT name_enc FROM patient WHERE patient_id=?", (pid,)).fetchone()
        self.assertNotEqual(row["name_enc"], "API患者")
        # 单个读取明文
        r3 = self.client.get(f"/api/patients/{pid}", headers=self._auth_headers(token))
        self.assertEqual(r3.json()["name"], "API患者")
        self.assertEqual(r3.json()["contact"], "13912345678")

    def test_update(self):
        token = self._login()
        pid = self.client.post("/api/patients", headers=self._auth_headers(token), json={
            "name": "更新前", "disease_category": "CAD_PCI"}).json()["patient_id"]
        r = self.client.put(f"/api/patients/{pid}", headers=self._auth_headers(token),
                            json={"status": "出院", "name": "更新后"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["status"], "出院")
        self.assertEqual(r.json()["name"], "更新后")

    def test_delete_protected(self):
        """有业务记录的患者删除 → 409（保护性设计）。"""
        token = self._login()
        pid = self.client.post("/api/patients", headers=self._auth_headers(token), json={
            "name": "删除测试", "disease_category": "CAD_PCI"}).json()["patient_id"]
        self.repo.insert_assessment({
            "patient_id": pid, "disease_category": "CAD_PCI",
            "assessment_type": "基线", "assess_date": "2026-08-03",
        })
        r = self.client.delete(f"/api/patients/{pid}", headers=self._auth_headers(token))
        self.assertEqual(r.status_code, 409)

    def test_delete_ok(self):
        token = self._login()
        pid = self.client.post("/api/patients", headers=self._auth_headers(token), json={
            "name": "可删患者", "disease_category": "CAD_PCI"}).json()["patient_id"]
        r = self.client.delete(f"/api/patients/{pid}", headers=self._auth_headers(token))
        self.assertEqual(r.status_code, 204)


class TestRbac(ApiBase):
    def test_therapist_cannot_delete(self):
        """治疗师无 patient:delete → 403。"""
        token = self._login("therapist", "Thera@1234")
        pid = self.client.post("/api/patients", headers=self._auth_headers(token), json={
            "name": "权限患者", "disease_category": "CAD_PCI"}).json()["patient_id"]
        r = self.client.delete(f"/api/patients/{pid}", headers=self._auth_headers(token))
        self.assertEqual(r.status_code, 403)

    def test_therapist_can_view_and_create(self):
        token = self._login("therapist", "Thera@1234")
        r = self.client.get("/api/patients", headers=self._auth_headers(token))
        self.assertEqual(r.status_code, 200)

    def test_invalid_token(self):
        r = self.client.get("/api/patients", headers={"Authorization": "Bearer badtoken"})
        self.assertEqual(r.status_code, 401)


class TestAssessment(ApiBase):
    """评估 API（B-T3）：创建（自动证型+分层）+ 历史 + 校验。"""

    def _create_patient(self, token):
        r = self.client.post("/api/patients", headers=self._auth_headers(token), json={
            "name": "评估患者", "gender": "女", "birth_date": "1965-01-01",
            "contact": "13912345679", "register_date": "2026-08-03",
            "disease_category": "CAD_PCI",
        })
        return r.json()["patient_id"]

    def test_pattern_keywords(self):
        token = self._login()
        r = self.client.get("/api/meta/pattern-keywords", headers=self._auth_headers(token))
        self.assertEqual(r.status_code, 200)
        self.assertTrue(len(r.json()["items"]) > 0)  # 规则外置：从证型 keywords 来

    def test_create_with_auto_judge(self):
        token = self._login()
        pid = self._create_patient(token)
        r = self.client.post("/api/assessments", headers=self._auth_headers(token), json={
            "patient_id": pid, "assessment_type": "基线",
            "LVEF": 46, "six_mwd": 550, "PHQ9": 5,
            "pattern_items": ["胸闷", "心悸", "舌质紫暗", "脉涩"],
        })
        self.assertEqual(r.status_code, 201, r.text)
        data = r.json()
        self.assertIsNotNone(data["main_pattern"])  # 自动证型判定
        self.assertIn(data["risk_level"], ["低危", "中危", "高危"])  # 自动分层
        # 证型/分层已落库（physician_confirm=1）
        row = self.repo.query_one(
            "SELECT main_pattern FROM tcm_pattern WHERE patient_id=? ORDER BY pattern_id DESC LIMIT 1",
            (pid,))
        self.assertEqual(row["main_pattern"], data["main_pattern"])
        row2 = self.repo.query_one(
            "SELECT risk_level FROM risk_stratification WHERE patient_id=? ORDER BY strat_id DESC LIMIT 1",
            (pid,))
        self.assertEqual(row2["risk_level"], data["risk_level"])

    def test_validate_range(self):
        token = self._login()
        pid = self._create_patient(token)
        r = self.client.post("/api/assessments", headers=self._auth_headers(token), json={
            "patient_id": pid, "LVEF": 150,  # 超出 0-100
        })
        self.assertEqual(r.status_code, 422)
        self.assertIn("LVEF", r.json()["detail"])

    def test_assessment_requires_patient(self):
        token = self._login()
        r = self.client.post("/api/assessments", headers=self._auth_headers(token), json={
            "patient_id": 99999, "LVEF": 50,
        })
        self.assertEqual(r.status_code, 404)

    def test_list_history(self):
        token = self._login()
        pid = self._create_patient(token)
        self.client.post("/api/assessments", headers=self._auth_headers(token), json={
            "patient_id": pid, "LVEF": 50, "six_mwd": 600,
        })
        r = self.client.get(f"/api/assessments/{pid}", headers=self._auth_headers(token))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.json()), 1)


class TestPrescription(ApiBase):
    """处方 API（B-T4）：生成/调整/签发/PDF/权限。"""

    def _setup_patient_with_assessment(self, token):
        """建档 + 评估（自动分层），返回 patient_id。"""
        pid = self.client.post("/api/patients", headers=self._auth_headers(token), json={
            "name": "处方患者", "gender": "男", "birth_date": "1960-01-01",
            "contact": "13912345670", "register_date": "2026-08-03",
            "disease_category": "CAD_PCI",
        }).json()["patient_id"]
        self.client.post("/api/assessments", headers=self._auth_headers(token), json={
            "patient_id": pid, "LVEF": 50, "six_mwd": 600,
        })
        return pid

    def test_latest_assessment(self):
        token = self._login()
        pid = self._setup_patient_with_assessment(token)
        r = self.client.get(f"/api/patients/{pid}/latest-assessment",
                            headers=self._auth_headers(token))
        self.assertEqual(r.status_code, 200)
        self.assertIn("risk_level", r.json())

    def test_generate(self):
        token = self._login()
        pid = self._setup_patient_with_assessment(token)
        r = self.client.post("/api/prescriptions/generate", headers=self._auth_headers(token), json={
            "patient_id": pid, "pattern": "气虚血瘀", "risk_level": "中危",
        })
        self.assertEqual(r.status_code, 201, r.text)
        data = r.json()
        self.assertEqual(data["matrix_code"], "CAD_PCI-A2")  # 气虚血瘀=1 + 中危=2
        self.assertIn("safety", data)
        self.assertEqual(data["status"], "草稿")
        self.assertIsNotNone(data["baduanjin_level"])

    def test_sign_requires_signature(self):
        token = self._login()
        pid = self._setup_patient_with_assessment(token)
        rx_id = self.client.post("/api/prescriptions/generate", headers=self._auth_headers(token), json={
            "patient_id": pid, "pattern": "痰浊闭阻", "risk_level": "高危",
        }).json()["rx_id"]
        # 空签名 → 422
        r = self.client.post(f"/api/prescriptions/{rx_id}/sign", headers=self._auth_headers(token),
                             json={"physician_sign": "  "})
        self.assertEqual(r.status_code, 422)
        # 正常签发
        r = self.client.post(f"/api/prescriptions/{rx_id}/sign", headers=self._auth_headers(token),
                             json={"physician_sign": "张医师"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["status"], "已签发")
        # 已签发不可修改 → 409
        r = self.client.put(f"/api/prescriptions/{rx_id}", headers=self._auth_headers(token),
                            json={"rpe_max": 15})
        self.assertEqual(r.status_code, 409)

    def test_pdf_only_signed(self):
        token = self._login()
        pid = self._setup_patient_with_assessment(token)
        rx_id = self.client.post("/api/prescriptions/generate", headers=self._auth_headers(token), json={
            "patient_id": pid, "pattern": "气阴两虚", "risk_level": "低危",
        }).json()["rx_id"]
        # 未签发 → 409
        r = self.client.get(f"/api/prescriptions/{rx_id}/pdf", headers=self._auth_headers(token))
        self.assertEqual(r.status_code, 409)
        # 签发后下载
        self.client.post(f"/api/prescriptions/{rx_id}/sign", headers=self._auth_headers(token),
                         json={"physician_sign": "李医师"})
        r = self.client.get(f"/api/prescriptions/{rx_id}/pdf", headers=self._auth_headers(token))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.headers["content-type"], "application/pdf")
        self.assertTrue(r.content[:5].startswith(b"%PDF"))

    def test_therapist_cannot_generate(self):
        """治疗师无 prescription:create → 403。"""
        token = self._login("therapist", "Thera@1234")
        r = self.client.post("/api/prescriptions/generate", headers=self._auth_headers(token), json={
            "patient_id": 1, "pattern": "气虚血瘀", "risk_level": "中危",
        })
        self.assertEqual(r.status_code, 403)

    def test_update_draft(self):
        token = self._login()
        pid = self._setup_patient_with_assessment(token)
        rx_id = self.client.post("/api/prescriptions/generate", headers=self._auth_headers(token), json={
            "patient_id": pid, "pattern": "气虚血瘀", "risk_level": "中危",
        }).json()["rx_id"]
        r = self.client.put(f"/api/prescriptions/{rx_id}", headers=self._auth_headers(token),
                            json={"rpe_max": 14, "aerobic_duration": 30})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["rpe_max"], 14)


class TestFollowup(ApiBase):
    """随访 API（B-T5）：计划生成/历史/完成登记。"""

    def _setup(self, token):
        pid = self.client.post("/api/patients", headers=self._auth_headers(token), json={
            "name": "随访患者", "gender": "女", "birth_date": "1968-05-05",
            "contact": "13912345671", "register_date": "2026-08-03",
            "disease_category": "CAD_PCI",
        }).json()["patient_id"]
        return pid

    def test_generate_plan(self):
        token = self._login()
        pid = self._setup(token)
        r = self.client.post("/api/followups/generate", headers=self._auth_headers(token),
                             json={"patient_id": pid})
        self.assertEqual(r.status_code, 201, r.text)
        d = r.json()
        self.assertEqual(d["created"], 5)  # 1周/1月/3月/6月/12月
        # 幂等：重复生成不新增
        r2 = self.client.post("/api/followups/generate", headers=self._auth_headers(token),
                              json={"patient_id": pid})
        self.assertEqual(r2.json()["created"], 0)

    def test_list_with_overdue(self):
        token = self._login()
        pid = self._setup(token)
        self.client.post("/api/followups/generate", headers=self._auth_headers(token),
                         json={"patient_id": pid})
        r = self.client.get(f"/api/followups/{pid}", headers=self._auth_headers(token))
        self.assertEqual(r.status_code, 200)
        rows = r.json()
        self.assertEqual(len(rows), 5)
        self.assertIn("overdue", rows[0])  # 逾期标记

    def test_complete(self):
        token = self._login()
        pid = self._setup(token)
        self.client.post("/api/followups/generate", headers=self._auth_headers(token),
                         json={"patient_id": pid})
        fu_id = self.client.get(f"/api/followups/{pid}", headers=self._auth_headers(token)).json()[0]["fu_id"]
        r = self.client.post(f"/api/followups/{fu_id}/complete", headers=self._auth_headers(token),
                             json={"handler": "王医师"})
        self.assertEqual(r.status_code, 200)
        d = r.json()
        self.assertEqual(d["status"], "已完成")
        self.assertEqual(d["handler"], "王医师")

    def test_requires_patient(self):
        token = self._login()
        r = self.client.post("/api/followups/generate", headers=self._auth_headers(token),
                             json={"patient_id": 99999})
        self.assertEqual(r.status_code, 404)

    def test_therapist_cannot_generate(self):
        """治疗师无 followup:create → 403。"""
        token = self._login("therapist", "Thera@1234")
        r = self.client.post("/api/followups/generate", headers=self._auth_headers(token),
                             json={"patient_id": 1})
        self.assertEqual(r.status_code, 403)


if __name__ == "__main__":
    unittest.main(verbosity=2)
