"""Logging configuration with secret redaction."""

import logging
import re
import sys
from typing import Any

# Sensitive keys to scrub if present in log strings or record attributes
SENSITIVE_PATTERNS = [
    re.compile(r'(?i)(client_secret["\']?\s*[:=]\s*["\']?)([^"\'&\s]+)'),
    re.compile(r'(?i)(access_token["\']?\s*[:=]\s*["\']?)([^"\'&\s]+)'),
    re.compile(r'(?i)(refresh_token["\']?\s*[:=]\s*["\']?)([^"\'&\s]+)'),
    re.compile(r'(?i)(code["\']?\s*[:=]\s*["\']?)([^"\'&\s]+)'),
    re.compile(r'(?i)(bearer\s+)([a-zA-Z0-9_\-\.]+)', re.IGNORECASE),
]


class SecretMaskingFilter(logging.Filter):
    """Logging filter that scrubs sensitive secrets from log records."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = self.mask_secrets(record.msg)
        if record.args:
            if isinstance(record.args, dict):
                record.args = {
                    k: self.mask_value(k, v) for k, v in record.args.items()
                }
            elif isinstance(record.args, tuple):
                record.args = tuple(
                    self.mask_secrets(str(arg)) if isinstance(arg, str) else arg
                    for arg in record.args
                )
        return True

    @classmethod
    def mask_secrets(cls, text: str) -> str:
        """Replace occurrences of sensitive patterns with redacted placeholder."""
        for pattern in SENSITIVE_PATTERNS:
            text = pattern.sub(r"\1[REDACTED]", text)
        return text

    @classmethod
    def mask_value(cls, key: str, value: Any) -> Any:
        """Mask specific values if key is known to be sensitive."""
        lower_key = str(key).lower()
        if any(s in lower_key for s in ("secret", "token", "code", "password")):
            return "[REDACTED]"
        if isinstance(value, str):
            return cls.mask_secrets(value)
        return value


def setup_logging(log_level: str = "INFO") -> logging.Logger:
    """Set up structured root logger with secret redaction."""
    logger = logging.getLogger("integration_aggregator")
    logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))

    # Avoid duplicate handlers if called multiple times
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        formatter = logging.Formatter(
            fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%SZ",
        )
        handler.setFormatter(formatter)
        handler.addFilter(SecretMaskingFilter())
        logger.addHandler(handler)

    logger.propagate = False
    return logger
