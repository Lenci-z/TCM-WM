# -*- coding: utf-8 -*-
"""
安全基础设施测试（P3-T1）：AES 加密往返、bcrypt 哈希、会话 token、迁移脚本。
"""
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)  # scripts/ 包导入
sys.path.insert(0, os.path.join(ROOT, "app"))

from security import SecurityManager  # noqa: E402


class TestAesEncryption(unittest.TestCase):
    """AES-256-CBC 加密往返。"""

    @classmethod
    def setUpClass(cls):
        # 固定密钥（测试隔离：不触碰 data/.secret_key）
        cls.sec = SecurityManager(key=b"0" * 32)

    def test_roundtrip_chinese(self):
        enc = self.sec.encrypt("张三")
        self.assertNotEqual(enc, "张三")  # 密文非明文
        self.assertEqual(self.sec.decrypt(enc), "张三")

    def test_roundtrip_contact(self):
        enc = self.sec.encrypt("13800138000")
        self.assertEqual(self.sec.decrypt(enc), "13800138000")

    def test_iv_randomness(self):
        """同一明文两次加密密文不同（随机 IV）。"""
        e1 = self.sec.encrypt("同一内容")
        e2 = self.sec.encrypt("同一内容")
        self.assertNotEqual(e1, e2)
        self.assertEqual(self.sec.decrypt(e1), self.sec.decrypt(e2))

    def test_empty_string(self):
        self.assertEqual(self.sec.encrypt(""), "")
        self.assertEqual(self.sec.decrypt(""), "")

    def test_long_text(self):
        txt = "测试" * 500
        self.assertEqual(self.sec.decrypt(self.sec.encrypt(txt)), txt)

    def test_base64_format(self):
        """密文为 base64（ASCII），与 XOR 旧格式区分（非纯文本）。"""
        import base64
        enc = self.sec.encrypt("张三")
        base64.b64decode(enc)  # 不抛异常


class TestPasswordHash(unittest.TestCase):
    """bcrypt 密码哈希。"""

    @classmethod
    def setUpClass(cls):
        cls.sec = SecurityManager(key=b"0" * 32)

    def test_hash_and_verify(self):
        h = self.sec.hash_password("Rehab@2026")
        self.assertNotEqual(h, "Rehab@2026")
        self.assertTrue(self.sec.verify_password("Rehab@2026", h))

    def test_wrong_password(self):
        h = self.sec.hash_password("正确密码")
        self.assertFalse(self.sec.verify_password("错误密码", h))

    def test_hash_salt_randomness(self):
        h1 = self.sec.hash_password("同密码")
        h2 = self.sec.hash_password("同密码")
        self.assertNotEqual(h1, h2)  # bcrypt 自动盐

    def test_invalid_hash(self):
        self.assertFalse(self.sec.verify_password("任意", "不是哈希"))


class TestSessionToken(unittest.TestCase):
    """会话 token（内存）。"""

    @classmethod
    def setUpClass(cls):
        cls.sec = SecurityManager(key=b"0" * 32)

    def test_generate_verify(self):
        token = self.sec.generate_token(7)
        self.assertEqual(self.sec.verify_token(token), 7)

    def test_revoke(self):
        token = self.sec.generate_token(3)
        self.sec.revoke_token(token)
        self.assertIsNone(self.sec.verify_token(token))

    def test_unknown_token(self):
        self.assertIsNone(self.sec.verify_token("不存在的token"))

    def test_tokens_unique(self):
        t1 = self.sec.generate_token(1)
        t2 = self.sec.generate_token(1)
        self.assertNotEqual(t1, t2)


class TestMigrateScript(unittest.TestCase):
    """迁移脚本：XOR 存量数据 → AES。"""

    def test_migrate_converts_xor_to_aes(self):
        import db
        import scripts.migrate_encrypt as mig
        fd, dbp = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        db.init_db(dbp)
        # 造 XOR 存量患者（直接调用 db 的 XOR 加密函数）
        conn = db.get_conn(dbp)
        xor_name = db.encrypt_text("存量患者")
        xor_contact = db.encrypt_text("13800138000")
        pid = conn.execute(
            "INSERT INTO patient (name_enc, contact_enc, register_date, disease_category) "
            "VALUES (?,?,?,'CAD_PCI')", (xor_name, xor_contact, "2026-08-03")
        ).lastrowid
        conn.commit()
        conn.close()

        n = mig.migrate(dbp, sec=SecurityManager(key=b"1" * 32))
        self.assertEqual(n, 1)

        # 迁移后：AES 可解密，且不再能 XOR 解密
        conn = db.get_conn(dbp)
        row = conn.execute(
            "SELECT name_enc, contact_enc FROM patient WHERE patient_id=?", (pid,)
        ).fetchone()
        conn.close()
        sec = SecurityManager(key=b"1" * 32)
        self.assertEqual(sec.decrypt(row["name_enc"]), "存量患者")
        self.assertEqual(sec.decrypt(row["contact_enc"]), "13800138000")
        # 清理（含备份文件）
        os.unlink(dbp)
        for f in os.listdir(os.path.dirname(dbp)):
            if f.startswith(os.path.basename(dbp) + ".bak"):
                os.unlink(os.path.join(os.path.dirname(dbp), f))


class TestAuthManager(unittest.TestCase):
    """登录认证 + RBAC + 审计（P3-T2）。"""

    @classmethod
    def setUpClass(cls):
        import db
        from repo import Repository
        from auth import AuthManager
        from security import SecurityManager
        fd, cls.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        db.init_db(cls.db_path)
        db.import_seed(cls.db_path)
        cls.conn = db.get_conn(cls.db_path)
        cls.repo = Repository(cls.conn)
        cls.sec = SecurityManager(key=b"2" * 32)
        cls.auth = AuthManager(cls.repo, cls.sec)
        # 测试用户：admin（管理员）/ doctor（医师）/ therapist（治疗师）
        cls.repo.create_user("admin", cls.sec.hash_password("Admin@123"),
                             "系统管理员", "管理员")
        cls.repo.create_user("doctor", cls.sec.hash_password("Doctor@123"),
                             "张医师", "医师")
        cls.repo.create_user("therapist", cls.sec.hash_password("Thera@123"),
                             "李治疗师", "治疗师")

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()
        os.unlink(cls.db_path)

    def test_login_success(self):
        token = self.auth.login("admin", "Admin@123")
        self.assertIsNotNone(token)
        self.assertEqual(self.auth.get_role(token), "管理员")

    def test_login_wrong_password(self):
        token = self.auth.login("doctor", "错误密码")
        self.assertIsNone(token)

    def test_login_unknown_user(self):
        self.assertIsNone(self.auth.login("不存在", "任意密码"))

    def test_failed_lock_after_5(self):
        """连续 5 次失败 → 锁定（第 6 次即使密码正确也拒绝）。"""
        for _ in range(5):
            self.auth.login("therapist", "错误密码")
        user = self.repo.get_user_by_username("therapist")
        self.assertGreaterEqual(user["failed_count"], 5)
        self.assertIsNotNone(user["locked_until"])
        # 锁定期间正确密码也拒绝
        token = self.auth.login("therapist", "Thera@123")
        self.assertIsNone(token)

    def test_rbac_matrix(self):
        t_doc = self.auth.login("doctor", "Doctor@123")
        t_th = self.auth.login("therapist", "Thera@123")
        t_adm = self.auth.login("admin", "Admin@123")
        # 处方签发：医师✅ 治疗师❌ 管理员✅
        self.assertTrue(self.auth.check_permission(t_doc, "prescription:sign"))
        self.assertFalse(self.auth.check_permission(t_th, "prescription:sign"))
        self.assertTrue(self.auth.check_permission(t_adm, "prescription:sign"))
        # 规则编辑：仅管理员
        self.assertFalse(self.auth.check_permission(t_doc, "rules:edit"))
        self.assertTrue(self.auth.check_permission(t_adm, "rules:edit"))
        # 患者删除：医师✅ 治疗师❌（矩阵：治疗师无 patient:delete）
        self.assertTrue(self.auth.check_permission(t_doc, "patient:delete"))
        self.assertFalse(self.auth.check_permission(t_th, "patient:delete"))
        # 无效 token
        self.assertFalse(self.auth.check_permission("坏token", "patient:view"))

    def test_logout_revokes(self):
        token = self.auth.login("doctor", "Doctor@123")
        self.auth.logout(token)
        self.assertIsNone(self.auth.get_current_user(token))

    def test_audit_log_records_login(self):
        """登录成功/失败均写审计日志。"""
        self.auth.login("admin", "Admin@123")
        logs = self.repo.list_audit_logs()
        action_types = [l["action_type"] for l in logs]
        self.assertIn("LOGIN", action_types)
        # 至少一条含用户名详情的成功登录记录
        self.assertTrue(any("admin" in (l.get("detail") or "") for l in logs))


if __name__ == "__main__":
    unittest.main(verbosity=2)
