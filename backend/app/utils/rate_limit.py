"""Simple in-memory rate limiter for auth endpoints.

Uses a sliding window approach with per-IP tracking. Not suitable for
multi-process deployments without shared state (Redis), but sufficient
for single-instance local/dev use and Docker Compose setups.

The client IP is derived from ``X-Forwarded-For`` only when the app is
configured to sit behind a known number of trusted proxies
(:attr:`app.config.settings.trusted_proxy_count`). Otherwise the header is
ignored so clients cannot spoof it to bypass the limit.
"""

import time
from collections import defaultdict

from fastapi import HTTPException, Request, status

from app.config import settings


class RateLimiter:
    """Sliding-window rate limiter keyed by client IP.

    Args:
        max_requests: Maximum number of requests allowed in the window.
        window_seconds: Duration of the sliding window in seconds.

    """

    def __init__(self, max_requests: int = 10, window_seconds: int = 60) -> None:
        """Initialize the rate limiter with request limit and window size."""
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._requests: dict[str, list[float]] = defaultdict(list)

    def _cleanup(self, key: str) -> None:
        """Remove expired timestamps and drop the key if it becomes empty.

        Dropping empty keys prevents unbounded growth of the tracking dict
        from one-off clients that never return.
        """
        cutoff = time.time() - self.window_seconds
        kept = [t for t in self._requests[key] if t > cutoff]
        if kept:
            self._requests[key] = kept
        else:
            self._requests.pop(key, None)

    def check(self, key: str) -> None:
        """Check if the key has exceeded the rate limit.

        Args:
            key: Identifier for the client (typically IP address).

        Raises:
            HTTPException: 429 if rate limit is exceeded.

        """
        self._cleanup(key)
        if len(self._requests[key]) >= self.max_requests:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many requests. Please try again later.",
                headers={"Retry-After": str(self.window_seconds)},
            )
        self._requests[key].append(time.time())


# Shared limiter for auth endpoints (configurable via settings).
auth_rate_limiter = RateLimiter(
    max_requests=settings.auth_rate_limit_max_requests,
    window_seconds=settings.auth_rate_limit_window_seconds,
)


def get_client_ip(request: Request) -> str:
    """Extract the client IP, honoring X-Forwarded-For only behind proxies.

    When ``trusted_proxy_count`` is greater than zero the app is assumed to
    sit behind that many trusted reverse proxies. The real client IP is then
    the entry ``trusted_proxy_count`` positions from the right of the
    ``X-Forwarded-For`` chain (each trusted proxy appends one entry). When it
    is zero the header is ignored entirely, because an untrusted client could
    otherwise forge it to evade the per-IP limit.

    Args:
        request: The incoming FastAPI request.

    Returns:
        The client's IP address as a string.

    """
    peer_ip = request.client.host if request.client else "unknown"

    trusted = settings.trusted_proxy_count
    if trusted <= 0:
        return peer_ip

    forwarded = request.headers.get("X-Forwarded-For")
    if not forwarded:
        return peer_ip

    chain = [part.strip() for part in forwarded.split(",") if part.strip()]
    if not chain:
        return peer_ip

    # The rightmost entry is added by the closest proxy. Skip the trusted
    # proxies to reach the IP the outermost trusted proxy observed.
    index = len(chain) - trusted
    if index < 0:
        # Fewer entries than expected proxies — fall back to the leftmost.
        index = 0
    return chain[index]


def rate_limit_auth(request: Request) -> None:
    """FastAPI dependency that applies rate limiting to auth endpoints.

    Args:
        request: The incoming request.

    Raises:
        HTTPException: 429 if the client has exceeded the rate limit.

    """
    client_ip = get_client_ip(request)
    auth_rate_limiter.check(client_ip)
