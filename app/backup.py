# -*- coding: utf-8 -*-
"""
数据备份与恢复（并行第一批线③：PRD P4 功能 6 单机版）。

用 SQLite 官方 backup API（sqlite3.Connection.backup()），保证 WAL 模式下
未 checkpoint 的数据也一致入库——不能用文件复制（WAL 下复制会丢最近数据）。
"""
import os
import sqlite3
from datetime import datetime

# 备份目录：相对项目根，经 db._default_path 解析
DEFAULT_BACKUP_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "backups"
)

DEFAULT_MAX_BACKUPS = 7


def _resolve_dir(backup_dir):
    return backup_dir or DEFAULT_BACKUP_DIR


def backup_db(source_path: str, backup_dir: str = None, max_backups: int = DEFAULT_MAX_BACKUPS) -> str:
    """一致性备份数据库。

    用 sqlite3 backup API（src.backup(dst)），WAL 安全。
    文件名：rehab_backup_YYYYMMDD_HHMMSS.db
    备份后调用 prune_backups 清理超出 max_backups 的旧备份。
    返回备份文件完整路径。
    """
    d = _resolve_dir(backup_dir)
    os.makedirs(d, exist_ok=True)
    # 毫秒级时间戳：防止同一秒内多次备份互相覆盖
    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
    dst_path = os.path.join(d, f"rehab_backup_{ts}.db")
    src = sqlite3.connect(source_path)
    dst = sqlite3.connect(dst_path)
    try:
        src.backup(dst)  # 在线备份：期间源库可被其他连接继续读写
    finally:
        dst.close()
        src.close()
    prune_backups(d, max_backups)
    return dst_path


def list_backups(backup_dir: str = None) -> list:
    """列出备份文件。每项 {path, filename, size_bytes, mtime}，按 mtime 降序。"""
    d = _resolve_dir(backup_dir)
    if not os.path.isdir(d):
        return []
    items = []
    for fn in sorted(os.listdir(d)):
        if not fn.startswith("rehab_backup_") or not fn.endswith(".db"):
            continue
        fp = os.path.join(d, fn)
        try:
            st = os.stat(fp)
        except OSError:
            continue
        items.append({
            "path": fp,
            "filename": fn,
            "size_bytes": st.st_size,
            "mtime": st.st_mtime,
        })
    items.sort(key=lambda x: x["mtime"], reverse=True)
    return items


def prune_backups(backup_dir: str = None, max_backups: int = DEFAULT_MAX_BACKUPS) -> list:
    """保留最新的 max_backups 个，删除更旧的。返回被删除文件路径列表。"""
    d = _resolve_dir(backup_dir)
    items = list_backups(d)
    if len(items) <= max_backups:
        return []
    removed = []
    for it in items[max_backups:]:
        try:
            os.unlink(it["path"])
            removed.append(it["path"])
        except OSError:
            pass
    return removed


def restore_db(backup_path: str, target_path: str = None) -> None:
    """恢复：目标库已存在则先备份为 target_path.bak_before_restore_<ts>.db，
    再用 backup_path 覆盖 target_path。

    恢复前校验 backup_path 是合法 SQLite 文件（可打开）。
    """
    if not os.path.exists(backup_path):
        raise ValueError(f"备份文件不存在: {backup_path}")
    # 校验备份文件是合法 SQLite（connect 是惰性的，需执行查询真正打开文件）
    try:
        chk = sqlite3.connect(backup_path)
        try:
            chk.execute("SELECT 1").fetchone()
        finally:
            chk.close()
    except sqlite3.Error as e:
        raise ValueError(f"备份文件不是合法 SQLite 数据库: {e}") from e

    if target_path is None:
        from db import DB_PATH  # 延迟导入避免循环
        target_path = DB_PATH

    # 医疗数据底线：恢复前先备份当前库（防止误恢复覆盖现有数据）
    if os.path.exists(target_path):
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        before = f"{target_path}.bak_before_restore_{ts}.db"
        src_cur = sqlite3.connect(target_path)
        dst_before = sqlite3.connect(before)
        try:
            src_cur.backup(dst_before)
        finally:
            dst_before.close()
            src_cur.close()

    src = sqlite3.connect(backup_path)
    dst = sqlite3.connect(target_path)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
