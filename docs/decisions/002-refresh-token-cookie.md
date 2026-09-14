# ADR-002: httpOnly Refresh-Token Cookie and Reuse-Detection Grace Window

## Status

Accepted

## Context

The refresh token — the long-lived credential that mints access tokens — was
stored in `localStorage`, which is readable by any JavaScript running on the
page. A single XSS flaw could therefore exfiltrate it and grant an attacker
durable access.

Separately, refresh-token rotation with strict reuse detection (see ADR-001)
revoked a user's entire token family whenever an already-rotated token was
replayed. Because the refresh token was shared across browser tabs, two tabs
refreshing at nearly the same time could trip this and log the user out of all
sessions.

## Decision

**Transport the refresh token in an httpOnly cookie.**

- `POST /api/auth/login`, `POST /api/auth/setup`, `POST /api/auth/refresh`, and
  the OIDC callback set the refresh token as a cookie with `HttpOnly`,
  `Secure` (in production), `SameSite=lax`, and `Path=/api/auth`. The token is
  no longer present in any response body or redirect URL.
- `POST /api/auth/refresh` and `POST /api/auth/logout` read the token from the
  cookie; logout clears it.
- The access token remains in the response body and is held only in memory on
  the client.

CSRF: `SameSite=lax` prevents the cookie from being attached to cross-site
POST requests, so a forged cross-site call to `/api/auth/refresh` or `/logout`
carries no cookie and fails. Same-site XHR from the SPA (including the
different-port dev setup, which is same-site) still sends it. `Path=/api/auth`
keeps the cookie off all other API calls. This makes a separate CSRF token
unnecessary for these endpoints.

**Add a reuse-detection grace window.**

`refresh_tokens` gains a `replaced_by_id` column, set only when a token is
rotated (not when it is revoked via logout). On replay of a revoked token:

- rotated **and** replayed within `REFRESH_REUSE_GRACE_SECONDS` (default 10s):
  treated as a benign concurrent refresh — a fresh token pair is issued and the
  family is **not** revoked;
- otherwise (outside the window, or a logged-out/never-rotated token): treated
  as theft — the entire family is revoked and the cookie cleared.

## Consequences

- The frontend no longer stores or handles the refresh token; `AuthContext`
  relies on the cookie and calls `POST /api/auth/refresh` with credentials.
  Auth API clients set `withCredentials: true`.
- Cross-origin deployments must keep frontend and backend same-site (for the
  cookie) and use exact CORS origins with credentials (already required).
- `Secure` cookies require HTTPS; local HTTP dev derives `Secure=false` from
  `ENVIRONMENT`.
- Multi-tab concurrent refreshes no longer cause spurious full logouts, at the
  cost of a small (default 10s) window in which a replayed rotated token is
  tolerated.
- Requires migration `003_add_refresh_token_replaced_by`.
