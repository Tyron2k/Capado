"""Centralized application configuration via pydantic-settings.

All environment-driven configuration is defined here in a single validated
:class:`Settings` model. Modules import the shared :data:`settings` singleton
instead of calling ``os.getenv`` directly, which gives one source of truth,
type coercion, and fail-fast validation of insecure production setups.

Environment variables map to fields case-insensitively (e.g. ``JWT_SECRET_KEY``
sets :attr:`Settings.jwt_secret_key`).
"""

import logging
import secrets
from functools import cached_property
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

logger = logging.getLogger(__name__)

# Values that must never be used as a real secret in production.
INSECURE_SECRETS: frozenset[str] = frozenset(
    {
        "",
        "change-me-to-a-random-secret",
        "fallback-secret-change-me",
        "secret",
        "changeme",
    }
)


class Settings(BaseSettings):
    """Validated application settings loaded from the environment.

    Attributes:
        environment: Deployment environment. In ``production`` a strong
            ``jwt_secret_key`` is mandatory and the app refuses to start
            without one.
        database_url: SQLAlchemy async database URL.
        jwt_secret_key: Secret used to sign JWT access tokens and OIDC state
            cookies. Auto-generated (per-process) outside production when
            unset or insecure.
        jwt_algorithm: JWT signing algorithm.
        access_token_expire_minutes: Access token lifetime in minutes.
        refresh_token_expire_days: Refresh token lifetime in days.
        bcrypt_work_factor: bcrypt cost factor (minimum 10, enforced).
        cors_origins: Allowed CORS origins. Wildcards are rejected because
            they are incompatible with ``allow_credentials=True``.
        trusted_proxy_count: Number of trusted reverse proxies in front of the
            app. Controls how the client IP is derived from
            ``X-Forwarded-For`` for rate limiting (0 = header ignored).
        auth_rate_limit_max_requests: Max auth requests per window per client.
        auth_rate_limit_window_seconds: Rate-limit window length in seconds.
        oidc_issuer_url: OIDC issuer base URL (empty disables OIDC).
        oidc_client_id: OIDC client identifier.
        oidc_client_secret: OIDC client secret.
        oidc_redirect_uri: OIDC redirect URI registered with the provider.
        oidc_scopes: Space-separated OIDC scopes.
        oidc_auto_create_users: Whether to auto-provision users on first OIDC
            login.
        oidc_require_verified_email: Refuse to link or create an account when the
            provider does not assert ``email_verified: true``. On by default: the
            email claim is what links an SSO login to an existing account, so an
            unverified one is an account-takeover path. Set false only for a
            provider that omits the claim entirely and whose addresses you trust.
        frontend_url: Base URL of the frontend for post-login redirects.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    environment: Literal["development", "test", "production"] = "development"

    # Database
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/capado"

    # JWT / auth
    jwt_secret_key: str = ""
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 7
    bcrypt_work_factor: int = 12

    # Refresh-token cookie (httpOnly). The refresh token is transported in a
    # cookie rather than JS-readable storage to reduce XSS exposure.
    refresh_cookie_name: str = "refresh_token"
    refresh_cookie_path: str = "/api/auth"
    # SameSite=lax blocks the cookie on cross-site POSTs (CSRF defense) while
    # still allowing same-site XHR and the OIDC top-level redirect.
    refresh_cookie_samesite: Literal["lax", "strict", "none"] = "lax"
    # None → derive from environment (Secure in production). Override to force.
    cookie_secure: bool | None = None

    # Grace window (seconds) during which a just-rotated refresh token that is
    # replayed is treated as a benign concurrent refresh (e.g. two browser
    # tabs) rather than theft. Outside the window, replay revokes the family.
    refresh_reuse_grace_seconds: int = 10

    # CORS. NoDecode disables pydantic-settings' automatic JSON decoding of the
    # env value so a plain comma-separated string (not JSON) is accepted and
    # split by the validator below.
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: [
            "http://localhost:3000",
            "http://localhost:5173",
        ]
    )

    # Reverse-proxy / rate limiting
    trusted_proxy_count: int = 0
    auth_rate_limit_max_requests: int = 10
    auth_rate_limit_window_seconds: int = 60

    # OIDC
    oidc_issuer_url: str = ""
    oidc_client_id: str = ""
    oidc_client_secret: str = ""
    oidc_redirect_uri: str = ""
    oidc_scopes: str = "openid email profile"
    oidc_auto_create_users: bool = False
    oidc_require_verified_email: bool = True

    # Frontend
    frontend_url: str = "http://localhost:5173"

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_cors_origins(cls, value: object) -> object:
        """Allow ``CORS_ORIGINS`` to be a comma-separated string."""
        if isinstance(value, str):
            return [o.strip() for o in value.split(",") if o.strip()]
        return value

    @field_validator("cors_origins")
    @classmethod
    def _reject_wildcard_origins(cls, value: list[str]) -> list[str]:
        """Reject wildcard origins, which are unsafe with credentials."""
        if "*" in value:
            logger.warning(
                "CORS_ORIGINS contains wildcard '*'. This is insecure with "
                "allow_credentials=True. Falling back to localhost-only origins."
            )
            return ["http://localhost:3000", "http://localhost:5173"]
        return value

    @field_validator("bcrypt_work_factor")
    @classmethod
    def _enforce_min_work_factor(cls, value: int) -> int:
        """Enforce a minimum bcrypt work factor of 10."""
        if value < 10:
            logger.warning(
                "BCRYPT_WORK_FACTOR=%d is below the minimum of 10. Using 10.",
                value,
            )
            return 10
        return value

    @model_validator(mode="after")
    def _resolve_jwt_secret(self) -> "Settings":
        """Validate or auto-generate the JWT secret depending on environment.

        In production an insecure or missing secret is a fatal error. Outside
        production a random per-process secret is generated so local and test
        runs work without configuration (tokens do not survive restarts).

        Raises:
            RuntimeError: If ``environment`` is ``production`` and no strong
                ``jwt_secret_key`` is configured.
        """
        if self.jwt_secret_key in INSECURE_SECRETS:
            if self.environment == "production":
                raise RuntimeError(
                    "JWT_SECRET_KEY must be set to a strong random value in "
                    "production. Refusing to start with an insecure secret."
                )
            logger.warning(
                "JWT_SECRET_KEY is unset or insecure. Generating a random "
                "per-process secret; tokens will not survive restarts and this "
                "is unsafe across multiple workers. Set JWT_SECRET_KEY."
            )
            # Assign via object.__setattr__ to bypass validation re-entry.
            object.__setattr__(self, "jwt_secret_key", secrets.token_urlsafe(64))
        return self

    @cached_property
    def oidc_enabled(self) -> bool:
        """Whether OIDC login is fully configured and enabled."""
        return bool(
            self.oidc_issuer_url and self.oidc_client_id and self.oidc_client_secret
        )

    @property
    def refresh_cookie_secure(self) -> bool:
        """Whether the refresh cookie should carry the Secure flag.

        Defaults to True in production and False elsewhere unless
        ``cookie_secure`` is explicitly set.
        """
        if self.cookie_secure is not None:
            return self.cookie_secure
        return self.environment == "production"


settings = Settings()
