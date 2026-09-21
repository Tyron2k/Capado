"""Helpers for safely representing untrusted values in text logs."""


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
