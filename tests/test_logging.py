"""Unit tests for secret masking in logs."""

import logging
from app.logging_config import SecretMaskingFilter


def test_mask_secrets_in_strings():
    text = (
        'Registered client_secret="my_super_secret" '
        'and access_token=gho_123456789 '
        'and code=abc_code_value '
        'and Authorization: Bearer secret_bearer_token'
    )
    masked = SecretMaskingFilter.mask_secrets(text)

    assert "my_super_secret" not in masked
    assert "gho_123456789" not in masked
    assert "abc_code_value" not in masked
    assert "secret_bearer_token" not in masked
    assert "[REDACTED]" in masked


def test_filter_log_record():
    log_filter = SecretMaskingFilter()
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg="Writing client_secret=very_secret_key to OpenBao",
        args=(),
        exc_info=None,
    )
    log_filter.filter(record)
    assert "very_secret_key" not in record.msg
    assert "[REDACTED]" in record.msg
