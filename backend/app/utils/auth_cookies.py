"""Helpers for the httpOnly refresh-token cookie.

The refresh token is transported in an httpOnly cookie instead of a
JS-readable location so that it cannot be exfiltrated via XSS. Cookie
attributes are sourced from the central settings object.
"""

from fastapi import Response

from app.config import settings


def set_refresh_cookie(response: Response, raw_token: str) -> None:
    """Attach the refresh token to *response* as an httpOnly cookie.

    Args:
        response: The response (or RedirectResponse) to set the cookie on.
        raw_token: The plain-text refresh token to store client-side.
    """
    response.set_cookie(
        key=settings.refresh_cookie_name,
        value=raw_token,
        max_age=settings.refresh_token_expire_days * 24 * 60 * 60,
        httponly=True,
        secure=settings.refresh_cookie_secure,
        samesite=settings.refresh_cookie_samesite,
        path=settings.refresh_cookie_path,
    )


def clear_refresh_cookie(response: Response) -> None:
    """Remove the refresh-token cookie from the client.

    Args:
        response: The response to clear the cookie on.
    """
    response.delete_cookie(
        key=settings.refresh_cookie_name,
        path=settings.refresh_cookie_path,
        httponly=True,
        secure=settings.refresh_cookie_secure,
        samesite=settings.refresh_cookie_samesite,
    )
