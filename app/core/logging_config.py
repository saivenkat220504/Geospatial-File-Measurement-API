import logging
import sys


def setup_logging(log_level: str = "INFO") -> None:
    """
    Configures structured logging across the application.
    Standardized format: %(asctime)s | %(levelname)s | %(name)s | %(message)s
    Sensitive file contents, geometries, and credentials are never logged.
    """
    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    if not root_logger.handlers:
        root_logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))
        root_logger.addHandler(handler)
    else:
        root_logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))
        for h in root_logger.handlers:
            h.setFormatter(formatter)
