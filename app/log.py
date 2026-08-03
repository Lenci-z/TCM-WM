# -*- coding: utf-8 -*-
"""
统一日志（步骤 1.2）：引擎/GUI/DB 异常落 data/logs/ 文件，可追溯
用法：
  from log import get_logger
  logger = get_logger("view.prescription")
  logger.error("保存处方失败: %s", e)
"""
import logging
import os

from config import get_config

_LOGGER_NAME = "rehab"
_initialized = False


def setup_logging(log_dir: str = None, level: str = None) -> logging.Logger:
    """初始化根日志（幂等）：文件 + 控制台。返回根 logger。"""
    global _initialized
    cfg = get_config()
    log_dir = log_dir or cfg.log_dir
    level = level or cfg.log_level
    os.makedirs(log_dir, exist_ok=True)

    logger = logging.getLogger(_LOGGER_NAME)
    if _initialized and logger.handlers:
        return logger

    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    fh = logging.FileHandler(os.path.join(log_dir, "rehab.log"), encoding="utf-8")
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    ch = logging.StreamHandler()
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    _initialized = True
    logger.info("日志系统初始化: %s", os.path.join(log_dir, "rehab.log"))
    return logger


def get_logger(name: str = "") -> logging.Logger:
    """获取子 logger（未初始化时自动初始化）。"""
    if not _initialized:
        setup_logging()
    return logging.getLogger(f"{_LOGGER_NAME}.{name}" if name else _LOGGER_NAME)
