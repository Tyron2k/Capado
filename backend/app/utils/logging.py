"""Helpers for safely representing untrusted values in text logs."""

import logging


class AuthQueryFilter(logging.Filter):
    """Keep credentials and provider errors out of Uvicorn auth access logs."""

    def filter(self, record: logging.LogRecord) -> bool:
        """Remove auth query strings from Uvicorn's structured request argument."""
        args = record.args
        if isinstance(args, tuple) and len(args) == 5:
            path = args[2]
            if isinstance(path, str) and path.startswith("/api/auth/"):
                record.args = (*args[:2], path.partition("?")[0], *args[3:])
        return True


def quote_log_value(value: object | None) -> str:
    """Return a quoted value whose control characters cannot forge log lines."""
    if value is None:
        return '"<none>"'

    escaped = (
        str(value)
        .replace("\\", r"\\")
        .replace("\r", r"\r")
        .replace("\n", r"\n")
        .replace('"', r"\"")
    )
    return f'"{escaped}"'
