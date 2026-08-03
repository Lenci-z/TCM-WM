# -*- coding: utf-8 -*-
"""
配置加载（步骤 1.1：config.ini 消除硬编码）
所有路径/密钥/医院名从 config.ini 读取；缺省时使用内置默认值（兼容测试与无配置文件场景）。
"""
import configparser
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(BASE_DIR, "config.ini")


class AppConfig:
    """项目配置的惰性单例。"""

    def __init__(self, path: str = None):
        self.path = path or CONFIG_PATH
        self._parser = configparser.ConfigParser()
        self._parser.read(self.path, encoding="utf-8")

    def _get(self, section, key, default=None):
        try:
            return self._parser.get(section, key)
        except (configparser.NoSectionError, configparser.NoOptionError):
            return default

    # ---- app ----
    @property
    def db_path(self):
        v = self._get("app", "db_path")
        return os.path.join(BASE_DIR, v) if v and not os.path.isabs(v) else v

    @property
    def seed_dir(self):
        v = self._get("app", "seed_dir")
        return os.path.join(BASE_DIR, v) if v and not os.path.isabs(v) else v

    @property
    def hospital_name(self):
        return self._get("app", "hospital_name", "心血管康复中心")

    @property
    def department(self):
        return self._get("app", "department", "心脏康复门诊")

    # ---- security ----
    @property
    def encrypt_key(self):
        return self._get("security", "encrypt_key", "CR-Rehab-MVP-2026").encode("utf-8")

    # ---- fonts ----
    @property
    def pdf_font(self):
        return self._get("fonts", "pdf_font", r"C:\Windows\Fonts\msyh.ttc")

    # ---- logging ----
    @property
    def log_dir(self):
        v = self._get("logging", "log_dir", "data/logs")
        return os.path.join(BASE_DIR, v) if v and not os.path.isabs(v) else v

    @property
    def log_level(self):
        return self._get("logging", "log_level", "INFO")


_config = None


def get_config(path: str = None) -> AppConfig:
    """获取配置单例（可注入路径便于测试）。"""
    global _config
    if _config is None or path:
        _config = AppConfig(path)
    return _config
