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
import time
from logging.handlers import RotatingFileHandler

from config import LOG_DIR

_fmt = logging.Formatter(
    "%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


class _SharedRotatingFileHandler(RotatingFileHandler):
    """
    The API server, scheduler and Short subprocesses all append to the same
    pipeline.log. On Windows a rename of a file another process has open fails
    (WinError 32); the stock handler then retried the rollover on every record
    and dropped each one, so logging silently stopped at 5 MB. Here a failed
    rollover just keeps appending to the current file and retries in 10 minutes.
    """

    _retry_after = 0.0

    def shouldRollover(self, record):
        if time.time() < self._retry_after:
            return False
        return super().shouldRollover(record)

    def doRollover(self):
        try:
            super().doRollover()
        except OSError:
            self._retry_after = time.time() + 600
            if self.stream is None:
                self.stream = self._open()


# Rotating file: 5 MB per file, keep 7 days of history
_file_handler = _SharedRotatingFileHandler(
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
