# -*- coding: utf-8 -*-
"""
安全基础设施（P3-T1）：AES-256-CBC 加密 + bcrypt 密码哈希 + 会话 token。
设计来源：docs/分阶段开发设计与任务列表.md §4.3.3

密钥来源（按优先级）：
  1. 环境变量 REHAB_ENCRYPT_KEY（base64 编码的 32 字节）
  2. 本地密钥文件 data/.secret_key（首次运行自动生成，gitignore 不入库）
config.ini 不再存放密钥明文（移除 encrypt_key）。
"""
import base64
import os
import secrets

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives import padding
import bcrypt

_KEY_ENV = "REHAB_ENCRYPT_KEY"
_KEY_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", ".secret_key")


def _load_or_create_key(key_path: str = _KEY_FILE) -> bytes:
    """环境变量优先，否则读取/生成本地密钥文件（32 字节）。"""
    env = os.environ.get(_KEY_ENV)
    if env:
        key = base64.b64decode(env)
        if len(key) != 32:
            raise ValueError("REHAB_ENCRYPT_KEY 必须为 base64 编码的 32 字节密钥")
        return key
    if os.path.exists(key_path):
        return base64.b64decode(open(key_path, encoding="utf-8").read().strip())
    key = os.urandom(32)
    os.makedirs(os.path.dirname(key_path), exist_ok=True)
    # 写入密钥文件（本机权限保护；Windows 无 chmod 语义，依赖用户目录隔离）
    with open(key_path, "w", encoding="utf-8") as f:
        f.write(base64.b64encode(key).decode())
    return key


class SecurityManager:
    """AES-256-CBC 加密 + bcrypt 密码哈希 + 会话 token（内存会话，关闭即失效）。"""

    def __init__(self, key: bytes = None):
        self._key = key if key is not None else _load_or_create_key()
        if len(self._key) != 32:
            raise ValueError("AES 密钥必须为 32 字节（AES-256）")
        self._sessions = {}  # token -> user_id（进程内会话）

    # ---------- AES-256-CBC 加密/解密 ----------

    def encrypt(self, plaintext: str) -> str:
        """AES-256-CBC + PKCS7，输出 base64(iv + 密文)。"""
        if not plaintext:
            return ""
        iv = os.urandom(16)
        padder = padding.PKCS7(128).padder()
        data = padder.update(plaintext.encode("utf-8")) + padder.finalize()
        cipher = Cipher(algorithms.AES(self._key), modes.CBC(iv))
        enc = cipher.encryptor()
        ct = enc.update(data) + enc.finalize()
        return base64.b64encode(iv + ct).decode("ascii")

    def decrypt(self, ciphertext: str) -> str:
        """AES-256-CBC 解密（输入 base64(iv + 密文)）。"""
        if not ciphertext:
            return ""
        raw = base64.b64decode(ciphertext)
        iv, ct = raw[:16], raw[16:]
        cipher = Cipher(algorithms.AES(self._key), modes.CBC(iv))
        dec = cipher.decryptor()
        data = dec.update(ct) + dec.finalize()
        unpadder = padding.PKCS7(128).unpadder()
        return (unpadder.update(data) + unpadder.finalize()).decode("utf-8")

    # ---------- bcrypt 密码哈希 ----------

    def hash_password(self, password: str) -> str:
        """bcrypt 哈希（自动含盐）。"""
        return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("ascii")

    def verify_password(self, password: str, password_hash: str) -> bool:
        """验证密码。"""
        try:
            return bcrypt.checkpw(
                password.encode("utf-8"), password_hash.encode("ascii"))
        except (ValueError, TypeError):
            return False

    # ---------- 会话 token（内存） ----------

    def generate_token(self, user_id: int) -> str:
        """生成会话 token（内存保存，关闭应用即失效）。"""
        token = secrets.token_hex(32)
        self._sessions[token] = user_id
        return token

    def verify_token(self, token: str) -> int | None:
        """验证 token，返回 user_id 或 None。"""
        return self._sessions.get(token)

    def revoke_token(self, token: str) -> None:
        """登出：清除会话。"""
        self._sessions.pop(token, None)


# 模块级单例（应用内共享密钥与会话）
_default = None


def get_security() -> SecurityManager:
    global _default
    if _default is None:
        _default = SecurityManager()
    return _default
