"""One log format for every project: UTC timestamp, level, logger, message.

Plain key=value text rather than JSON, because these logs are read by people
in a terminal far more often than by a log shipper.
"""
from __future__ import annotations

import logging
import time


def setup_logging(level: int = logging.INFO) -> None:
    fmt = logging.Formatter("%(asctime)sZ %(levelname)-5s %(name)s %(message)s", "%Y-%m-%dT%H:%M:%S")
    fmt.converter = time.gmtime
    handler = logging.StreamHandler()
    handler.setFormatter(fmt)
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
