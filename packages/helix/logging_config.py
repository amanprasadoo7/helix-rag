"""Logging setup.

Local and dev get readable console logs. Staging and prod get JSON so log
shippers can parse them. The level comes from ``HELIX_LOG_LEVEL``.
"""

import logging

import structlog

_LEVELS = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}


def configure_logging(level: str, *, json_logs: bool) -> None:
    numeric_level = _LEVELS[level.upper()]

    logging.basicConfig(format="%(message)s", level=numeric_level)

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            (structlog.processors.JSONRenderer() if json_logs else structlog.dev.ConsoleRenderer()),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(numeric_level),
        cache_logger_on_first_use=True,
    )
