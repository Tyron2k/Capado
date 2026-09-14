"""OIDC service: handles OpenID Connect authorization code flow with Authentik.

This service manages OIDC discovery, authorization URL generation, token exchange,
and userinfo retrieval. It uses the external_id field on the User model to link
OIDC subjects to local user accounts.
"""

import logging
import secrets
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration (sourced from the centralized settings object)
# ---------------------------------------------------------------------------

OIDC_ISSUER_URL: str = settings.oidc_issuer_url
OIDC_CLIENT_ID: str = settings.oidc_client_id
OIDC_CLIENT_SECRET: str = settings.oidc_client_secret
OIDC_REDIRECT_URI: str = settings.oidc_redirect_uri
OIDC_SCOPES: str = settings.oidc_scopes
OIDC_ENABLED: bool = settings.oidc_enabled

# Frontend URL for post-login redirect
FRONTEND_URL: str = settings.frontend_url


@dataclass
class OIDCDiscovery:
    """Cached OIDC discovery document endpoints."""

    authorization_endpoint: str
    token_endpoint: str
    userinfo_endpoint: str
    end_session_endpoint: str | None = None


@dataclass
class OIDCUserInfo:
    """User information extracted from the OIDC provider.

    ``email_verified`` is the provider's own statement about the address, and it is kept as a
    tri-state on purpose: ``True`` and ``False`` are assertions, ``None`` means the provider said
    nothing. Those are three different situations for a caller that links accounts by email, and
    collapsing the missing case into ``False`` would hide which one occurred from the log.
    """

    sub: str
    email: str
    name: str
    email_verified: bool | None = None


# Module-level cache for discovery document
_discovery_cache: OIDCDiscovery | None = None


async def get_discovery() -> OIDCDiscovery:
    """Fetch and cache the OIDC discovery document from the issuer.

    Returns:
        Parsed discovery document with relevant endpoints.

    Raises:
        RuntimeError: If the discovery document cannot be fetched.

    """
    global _discovery_cache
    if _discovery_cache is not None:
        return _discovery_cache

    discovery_url = f"{OIDC_ISSUER_URL.rstrip('/')}/.well-known/openid-configuration"
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(discovery_url)
        response.raise_for_status()
        data = response.json()

    _discovery_cache = OIDCDiscovery(
        authorization_endpoint=data["authorization_endpoint"],
        token_endpoint=data["token_endpoint"],
        userinfo_endpoint=data["userinfo_endpoint"],
        end_session_endpoint=data.get("end_session_endpoint"),
    )
    return _discovery_cache


def generate_state() -> str:
    """Generate a cryptographically secure random state parameter.

    Returns:
        URL-safe random string for CSRF protection.

    """
    return secrets.token_urlsafe(32)


async def build_authorization_url(state: str) -> str:
    """Build the OIDC authorization URL for redirecting the user to Authentik.

    Args:
        state: CSRF state parameter to include in the request.

    Returns:
        Full authorization URL with query parameters.

    """
    discovery = await get_discovery()
    params = {
        "client_id": OIDC_CLIENT_ID,
        "response_type": "code",
        "scope": OIDC_SCOPES,
        "redirect_uri": OIDC_REDIRECT_URI,
        "state": state,
    }
    return f"{discovery.authorization_endpoint}?{urlencode(params)}"


async def exchange_code_for_tokens(code: str) -> dict:
    """Exchange an authorization code for tokens at the OIDC token endpoint.

    Args:
        code: The authorization code received from the callback.

    Returns:
        Token response dictionary containing access_token, id_token, etc.

    Raises:
        httpx.HTTPStatusError: If the token exchange fails.

    """
    discovery = await get_discovery()
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(
            discovery.token_endpoint,
            data={
                "grant_type": "authorization_code",
                "client_id": OIDC_CLIENT_ID,
                "client_secret": OIDC_CLIENT_SECRET,
                "code": code,
                "redirect_uri": OIDC_REDIRECT_URI,
            },
        )
        response.raise_for_status()
        return response.json()


async def get_userinfo(access_token: str) -> OIDCUserInfo:
    """Fetch user information from the OIDC provider's userinfo endpoint.

    Args:
        access_token: The access token obtained from the token exchange.

    Returns:
        Parsed user information (sub, email, name).

    Raises:
        httpx.HTTPStatusError: If the userinfo request fails.
        ValueError: If required fields are missing from the response.

    """
    discovery = await get_discovery()
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(
            discovery.userinfo_endpoint,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        response.raise_for_status()
        data = response.json()

    sub = data.get("sub")
    email = data.get("email")
    name = data.get("name") or data.get("preferred_username") or email

    # Absent stays absent rather than becoming False: the caller distinguishes "the provider says
    # this address is unverified" from "the provider does not report verification at all".
    raw_verified = data.get("email_verified")
    email_verified = bool(raw_verified) if raw_verified is not None else None

    if not sub or not email:
        raise ValueError("OIDC userinfo response missing required fields (sub, email)")

    return OIDCUserInfo(sub=sub, email=email, name=name, email_verified=email_verified)
