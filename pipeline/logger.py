"""
Centralised rotating-file logger shared across all pipeline modules.

Usage:
    from pipeline.logger import log
    log.info("message")
    log.warning("warn")
    log.error("err")
"""
import logging
import sys
from logging.handlers import RotatingFileHandler

from config import LOG_DIR

_fmt = logging.Formatter(
    "%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

# Rotating file: 5 MB per file, keep 7 days of history
_file_handler = RotatingFileHandler(
    LOG_DIR / "pipeline.log",
    maxBytes=5 * 1024 * 1024,
    backupCount=7,
    encoding="utf-8",
)
_file_handler.setFormatter(_fmt)

_stdout_handler = logging.StreamHandler(sys.stdout)
_stdout_handler.setFormatter(_fmt)

log = logging.getLogger("yt_poster")
log.setLevel(logging.DEBUG)
log.addHandler(_file_handler)
log.addHandler(_stdout_handler)
# Prevent duplicate lines if root logger also has handlers
log.propagate = False
