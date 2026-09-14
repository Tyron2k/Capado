"""Tests for the auth rate limiter and trusted-proxy client-IP resolution.

Covers the sliding-window limit, empty-key eviction, and the
``X-Forwarded-For`` handling that only trusts the header when the app is
configured to sit behind a known number of proxies (anti-spoofing).

All data is inline and clearly fictional; no database is used.
"""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.config import settings
from app.utils.rate_limit import RateLimiter, get_client_ip


def _request(peer: str | None, xff: str | None = None) -> SimpleNamespace:
    """Build a fake request with a peer IP and optional X-Forwarded-For."""
    headers = {}
    if xff is not None:
        headers["X-Forwarded-For"] = xff
    client = SimpleNamespace(host=peer) if peer is not None else None
    return SimpleNamespace(client=client, headers=headers)


# ---------------------------------------------------------------------------
# Sliding window
# ---------------------------------------------------------------------------


class TestRateLimiter:
    """Sliding-window behavior of the limiter."""

    def test_allows_up_to_limit_then_blocks(self):
        """Requests are allowed up to the limit, then raise 429."""
        limiter = RateLimiter(max_requests=3, window_seconds=60)
        for _ in range(3):
            limiter.check("client-a")
        with pytest.raises(HTTPException) as exc_info:
            limiter.check("client-a")
        assert exc_info.value.status_code == 429

    def test_limits_are_per_key(self):
        """Distinct keys have independent budgets."""
        limiter = RateLimiter(max_requests=1, window_seconds=60)
        limiter.check("client-a")
        # Different key is unaffected.
        limiter.check("client-b")

    def test_empty_keys_are_evicted(self):
        """Keys whose timestamps all expire are removed from the tracker."""
        limiter = RateLimiter(max_requests=5, window_seconds=0)
        limiter.check("ephemeral")
        # With a zero-second window the next cleanup drops the stale key.
        limiter._cleanup("ephemeral")
        assert "ephemeral" not in limiter._requests


# ---------------------------------------------------------------------------
# Client IP resolution (anti-spoofing)
# ---------------------------------------------------------------------------


class TestClientIpResolution:
    """X-Forwarded-For is only trusted behind configured proxies."""

    def test_header_ignored_without_trusted_proxies(self, monkeypatch):
        """With no trusted proxies the peer IP wins, header is ignored."""
        monkeypatch.setattr(settings, "trusted_proxy_count", 0)
        req = _request(peer="10.0.0.1", xff="1.2.3.4, 5.6.7.8")
        assert get_client_ip(req) == "10.0.0.1"

    def test_single_trusted_proxy_uses_rightmost_client(self, monkeypatch):
        """Behind one proxy, the last XFF entry is the real client."""
        monkeypatch.setattr(settings, "trusted_proxy_count", 1)
        req = _request(peer="10.0.0.1", xff="9.9.9.9, 8.8.8.8")
        assert get_client_ip(req) == "8.8.8.8"

    def test_two_trusted_proxies_ignore_spoofable_leftmost(self, monkeypatch):
        """Behind two proxies, the client-supplied leftmost entry is ignored.

        The two rightmost entries were appended by our trusted proxies; the
        leftmost (1.1.1.1) is client-controlled and must not be trusted. The
        real observed client IP is the leftmost trusted entry (2.2.2.2).
        """
        monkeypatch.setattr(settings, "trusted_proxy_count", 2)
        req = _request(peer="10.0.0.1", xff="1.1.1.1, 2.2.2.2, 3.3.3.3")
        assert get_client_ip(req) == "2.2.2.2"

    def test_missing_header_falls_back_to_peer(self, monkeypatch):
        """When the header is absent the peer IP is used."""
        monkeypatch.setattr(settings, "trusted_proxy_count", 1)
        req = _request(peer="10.0.0.1", xff=None)
        assert get_client_ip(req) == "10.0.0.1"

    def test_more_proxies_than_entries_falls_back_to_leftmost(self, monkeypatch):
        """Fewer XFF entries than configured proxies uses the leftmost entry."""
        monkeypatch.setattr(settings, "trusted_proxy_count", 5)
        req = _request(peer="10.0.0.1", xff="7.7.7.7, 6.6.6.6")
        assert get_client_ip(req) == "7.7.7.7"

    def test_unknown_peer_without_client(self, monkeypatch):
        """A request without client info returns the 'unknown' sentinel."""
        monkeypatch.setattr(settings, "trusted_proxy_count", 0)
        req = _request(peer=None)
        assert get_client_ip(req) == "unknown"
