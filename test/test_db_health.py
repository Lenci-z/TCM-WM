# -*- coding: utf-8 -*-
"""
DB 健壮性测试（并行第一批线②：PRD P2 功能 6/7）。
覆盖：check_db_health（正常/不存在/损坏）+ execute_with_retry（重试成功/非locked不重试/耗尽抛错）。
"""
import os
import sys
import sqlite3
import tempfile
import threading
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "app"))

from db import check_db_health, execute_with_retry  # noqa: E402


class TestCheckDbHealth(unittest.TestCase):
    """②-1 启动健康检查。"""

    def _tmp_db(self, with_table=True):
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        if with_table:
            conn = sqlite3.connect(path)
            conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
            conn.commit()
            conn.close()
        return path

    def test_healthy_db(self):
        path = self._tmp_db()
        try:
            ok, msg = check_db_health(path)
            self.assertTrue(ok)
            self.assertEqual(msg, "ok")
        finally:
            os.unlink(path)

    def test_missing_db(self):
        path = os.path.join(tempfile.gettempdir(), "definitely_missing_rehab_test_xyz.db")
        if os.path.exists(path):
            os.unlink(path)
        ok, msg = check_db_health(path)
        self.assertFalse(ok)
        self.assertIn("不存在", msg)

    def test_corrupted_db(self):
        """损坏库（写入垃圾字节）→ 不抛异常，返回 False。"""
        path = self._tmp_db(with_table=False)
        try:
            with open(path, "wb") as f:
                f.write(b"this is not a sqlite file at all \x00\x01\x02")
            ok, msg = check_db_health(path)
            self.assertFalse(ok)
            self.assertNotEqual(msg, "ok")
        finally:
            os.unlink(path)


class TestExecuteWithRetry(unittest.TestCase):
    """②-2 locked 重试。"""

    def test_locked_retry_success(self):
        """连接 A 持写锁 → 连接 B 用 execute_with_retry 写入 → A 释放 → B 最终成功。"""
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            conn_a = sqlite3.connect(path, timeout=0.2, check_same_thread=False)
            conn_b = sqlite3.connect(path, timeout=0.2, check_same_thread=False)
            conn_a.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
            conn_a.commit()
            try:
                # A 持有写锁
                conn_a.execute("BEGIN IMMEDIATE")
                result = {}

                def write_with_retry():
                    try:
                        execute_with_retry(conn_b, "INSERT INTO t (v) VALUES ('ok')",
                                           retries=5, base_delay=0.05)
                        conn_b.commit()
                        result["ok"] = True
                    except Exception as e:  # noqa: BLE001
                        result["error"] = e

                t = threading.Thread(target=write_with_retry)
                t.start()
                time.sleep(0.15)  # 让 B 先撞上锁并开始重试
                conn_a.execute("INSERT INTO t (v) VALUES ('a')")
                conn_a.commit()  # 释放写锁
                t.join(timeout=5)
                self.assertFalse(t.is_alive())
                self.assertNotIn("error", result, f"重试失败: {result.get('error')}")
                self.assertTrue(result.get("ok"))
                n = conn_b.execute("SELECT COUNT(*) FROM t").fetchone()[0]
                self.assertEqual(n, 2)
            finally:
                conn_a.close()
                conn_b.close()
        finally:
            os.unlink(path)

    def test_non_locked_error_no_retry(self):
        """非 locked 错误（非法 SQL）→ 立即抛错，不重试不 sleep。"""
        conn = sqlite3.connect(":memory:")
        start = time.time()
        with self.assertRaises(sqlite3.OperationalError):
            execute_with_retry(conn, "THIS IS NOT SQL", retries=3, base_delay=0.5)
        elapsed = time.time() - start
        self.assertLess(elapsed, 0.3, f"非 locked 错误不应 sleep，实际耗时 {elapsed:.2f}s")
        conn.close()

    def test_retries_exhausted_raises(self):
        """锁持续不释放 → retries 耗尽后抛原始 OperationalError。"""
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            conn_a = sqlite3.connect(path, timeout=0.2)
            conn_b = sqlite3.connect(path, timeout=0.1)
            conn_a.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
            conn_a.commit()
            try:
                conn_a.execute("BEGIN IMMEDIATE")  # 持锁不释放
                with self.assertRaises(sqlite3.OperationalError) as cm:
                    execute_with_retry(conn_b, "INSERT INTO t (v) VALUES ('x')",
                                       retries=2, base_delay=0.01)
                self.assertIn("locked", str(cm.exception))
            finally:
                conn_a.close()
                conn_b.close()
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main(verbosity=2)
