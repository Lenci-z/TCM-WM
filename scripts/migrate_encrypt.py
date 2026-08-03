# -*- coding: utf-8 -*-
"""
XOR → AES 加密迁移脚本（P3-T1）。
设计来源：docs/分阶段开发设计与任务列表.md §4.4

流程：
  1. 自动备份 data/rehab.db → .bak.YYYYMMDD
  2. 用旧 XOR 密钥解密存量 patient.name_enc/contact_enc
  3. 用 SecurityManager（AES-256-CBC）重新加密写回
  4. 打印迁移统计

用法：python scripts/migrate_encrypt.py
注意：仅对存量 XOR 数据执行一次；迁移后新数据由 repo 层 AES 加密。
"""
import base64
import os
import shutil
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app"))

from db import get_conn, DB_PATH, decrypt_text as xor_decrypt
from security import get_security


def migrate(db_path: str = DB_PATH, sec=None) -> int:
    """执行迁移，返回迁移的患者数。sec 可注入（测试用固定密钥）。"""
    if not os.path.exists(db_path):
        print("数据库不存在，无需迁移")
        return 0

    # 1. 备份
    backup_path = f"{db_path}.bak.{date.today().isoformat()}"
    shutil.copy2(db_path, backup_path)
    print(f"已备份: {backup_path}")

    # 2. AES 加密器
    sec = sec or get_security()
    conn = get_conn(db_path)
    try:
        # 3. 遍历患者表，XOR 解密 → AES 重加密
        rows = conn.execute(
            "SELECT patient_id, name_enc, contact_enc FROM patient"
        ).fetchall()
        n = 0
        for r in rows:
            old_name = xor_decrypt(r["name_enc"]) if r["name_enc"] else None
            old_contact = xor_decrypt(r["contact_enc"]) if r["contact_enc"] else None
            new_name = sec.encrypt(old_name) if old_name else None
            new_contact = sec.encrypt(old_contact) if old_contact else None
            conn.execute(
                "UPDATE patient SET name_enc=?, contact_enc=? WHERE patient_id=?",
                (new_name, new_contact, r["patient_id"]),
            )
            n += 1
        conn.commit()
        print(f"迁移完成: {n} 条患者记录（XOR → AES）")
        return n
    finally:
        conn.close()


if __name__ == "__main__":
    migrate()
