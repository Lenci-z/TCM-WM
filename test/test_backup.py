# -*- coding: utf-8 -*-
"""
备份恢复测试（并行第一批线③：PRD P4 功能 6 单机版）。
覆盖：backup_db（成功/WAL 完整）、prune_backups（保留最新 N）、
restore_db（恢复一致/先备份当前库/非法文件拒绝）。
"""
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "app"))

from backup import backup_db, list_backups, prune_backups, restore_db  # noqa: E402


class TestBackupDb(unittest.TestCase):
    def _tmp_db(self, with_data=True):
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        conn = sqlite3.connect(path)
        conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
        if with_data:
            conn.execute("INSERT INTO t (v) VALUES ('a'), ('b'), ('c')")
            conn.commit()
        conn.close()
        return path

    def _tmp_dir(self):
        return tempfile.mkdtemp(prefix="rehab_backup_test_")

    def test_backup_success_file_exists(self):
        src = self._tmp_db()
        d = self._tmp_dir()
        try:
            path = backup_db(src, d)
            self.assertTrue(os.path.exists(path))
            self.assertGreater(os.path.getsize(path), 0)
            # 备份内容与源一致
            conn = sqlite3.connect(path)
            n = conn.execute("SELECT COUNT(*) FROM t").fetchone()[0]
            conn.close()
            self.assertEqual(n, 3)
        finally:
            os.unlink(src)
            shutil.rmtree(d, ignore_errors=True)

    def test_wal_data_integrity(self):
        """WAL 有未 checkpoint 数据 → backup API 仍完整备份。"""
        src = self._tmp_db(with_data=False)
        d = self._tmp_dir()
        try:
            # 写数据不 commit（WAL 模式下的未 checkpoint 数据）
            conn = sqlite3.connect(src)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("INSERT INTO t (v) VALUES ('wal-data')")
            conn.commit()  # WAL 模式下 commit 后数据在 WAL 文件中，未 checkpoint
            conn.close()
            path = backup_db(src, d)
            chk = sqlite3.connect(path)
            n = chk.execute("SELECT COUNT(*) FROM t WHERE v='wal-data'").fetchone()[0]
            chk.close()
            self.assertEqual(n, 1, "backup API 应包含 WAL 未 checkpoint 数据")
        finally:
            os.unlink(src)
            for f in (src + "-wal", src + "-shm"):
                if os.path.exists(f):
                    os.unlink(f)
            shutil.rmtree(d, ignore_errors=True)

    def test_prune_keeps_latest_n(self):
        src = self._tmp_db()
        d = self._tmp_dir()
        try:
            paths = []
            for _ in range(5):
                paths.append(backup_db(src, d, max_backups=10))
            removed = prune_backups(d, max_backups=3)
            self.assertEqual(len(removed), 2)
            items = list_backups(d)
            self.assertEqual(len(items), 3)
            # 剩余的是最新的 3 个（mtime 降序前 3 个的路径 = 最后生成的 3 个）
            latest3 = paths[-3:]
            remaining = {it["path"] for it in items}
            self.assertEqual(remaining, set(latest3))
        finally:
            os.unlink(src)
            shutil.rmtree(d, ignore_errors=True)

    def test_restore_recovers_data_and_backs_up_current(self):
        """库 A 写数据 → 备份 → 删数据 → restore → 数据恢复，且恢复前原库先被 .bak 备份。"""
        src = self._tmp_db(with_data=True)  # 3 行数据
        d = self._tmp_dir()
        try:
            bak = backup_db(src, d)
            # 模拟数据丢失：删掉一行
            conn = sqlite3.connect(src)
            conn.execute("DELETE FROM t WHERE v='a'")
            conn.commit()
            conn.close()
            conn = sqlite3.connect(src)
            n_before = conn.execute("SELECT COUNT(*) FROM t").fetchone()[0]
            conn.close()
            self.assertEqual(n_before, 2)

            restore_db(bak, src)

            conn = sqlite3.connect(src)
            n_after = conn.execute("SELECT COUNT(*) FROM t").fetchone()[0]
            conn.close()
            self.assertEqual(n_after, 3, "restore 后应恢复为 3 行")
            # 恢复前原库被备份为 .bak_before_restore_*
            baks = [f for f in os.listdir(os.path.dirname(src))
                    if f.startswith(os.path.basename(src) + ".bak_before_restore_")]
            self.assertEqual(len(baks), 1, "restore 前应先备份当前库")
        finally:
            os.unlink(src)
            for f in os.listdir(os.path.dirname(src)):
                if f.startswith(os.path.basename(src) + ".bak_before_restore_"):
                    os.unlink(os.path.join(os.path.dirname(src), f))
            shutil.rmtree(d, ignore_errors=True)

    def test_restore_invalid_file_rejected(self):
        """传非 SQLite 文件 → 抛 ValueError，不覆盖目标库。"""
        src = self._tmp_db(with_data=True)
        d = self._tmp_dir()
        bad = os.path.join(d, "bad.db")
        with open(bad, "wb") as f:
            f.write(b"not a sqlite file")
        try:
            with self.assertRaises(ValueError):
                restore_db(bad, src)
            # 目标库未被覆盖
            conn = sqlite3.connect(src)
            n = conn.execute("SELECT COUNT(*) FROM t").fetchone()[0]
            conn.close()
            self.assertEqual(n, 3)
        finally:
            os.unlink(src)
            os.unlink(bad)
            shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
