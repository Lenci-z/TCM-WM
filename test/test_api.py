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


if __name__ == "__main__":
    unittest.main(verbosity=2)
