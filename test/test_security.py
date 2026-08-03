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


if __name__ == "__main__":
    unittest.main(verbosity=2)
