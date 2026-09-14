# ADR-001: Centralized Configuration and Auth Hardening

## Status

Accepted

## Context

Configuration was read via scattered `os.getenv` calls across six modules
(`auth_service`, `oidc_service`, the OIDC router, `database`, `main`). This
allowed inconsistent, duplicated defaults for the same value — most notably
the JWT secret, where the auth service auto-generated a strong random secret
when unset while the OIDC router fell back to a weak inline literal for
signing its CSRF state cookie. Several security-relevant behaviors were also
too lax for production: the app booted with an insecure secret, the auth rate
limiter trusted a client-supplied `X-Forwarded-For` header, login timing
leaked whether an email was registered, the `must_change_password` flag was
only enforced client-side, and rotated-out refresh tokens were neither reused-
detected nor cleaned up.

## Decision

Introduce a single validated settings object,
`app.config.settings` (a pydantic-settings `BaseSettings`), as the one source
of truth for all environment-driven configuration. Every module imports the
shared `settings` singleton instead of calling `os.getenv`.

Security hardening built on top of the central config:

- **JWT / OIDC secret:** one `jwt_secret_key`. With `ENVIRONMENT=production`
  an insecure or missing secret is a fatal startup error (fail-fast). Outside
  production a random per-process secret is generated (documented as unsafe
  across workers). The OIDC state cookie signs with the same secret — no weak
  fallback.
- **Rate limiter:** the client IP is derived from `X-Forwarded-For` only when
  `TRUSTED_PROXY_COUNT > 0`, skipping that many trusted proxy entries from the
  right; otherwise the header is ignored so it cannot be spoofed to bypass the
  limit. Empty per-IP buckets are evicted to bound memory.
- **Login timing:** an unknown email is still verified against a dummy bcrypt
  hash so response time does not reveal account existence.
- **Password change:** `get_current_user` rejects users flagged
  `must_change_password` (HTTP 403, `X-Error-Code: password_change_required`);
  only the change-password endpoint uses the non-enforcing
  `get_authenticated_user`.
- **Refresh tokens:** presenting an already-revoked (rotated-out) token
  triggers family revocation of all the user's tokens (theft defense), and
  expired rows are cleaned up opportunistically on refresh.

The database engine also gained `pool_pre_ping` (plus `pool_recycle`) and now
uses the modern `async_sessionmaker`.

## Consequences

- New settings are added as typed fields on `Settings`, not ad-hoc `os.getenv`
  calls. Environment variables map case-insensitively to field names.
- `ENVIRONMENT=production` deployments must provide `JWT_SECRET_KEY`.
- Deployments behind a reverse proxy must set `TRUSTED_PROXY_COUNT` for rate
  limiting to see real client IPs.
- `main.py` imports the config as `app_settings` to avoid a name clash with the
  `settings` router module.
