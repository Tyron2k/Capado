#!/usr/bin/env python3
"""Deterministic scheduled HTTP load generator for local/test environments."""

import argparse
import asyncio
import statistics
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import List, Tuple

DEFAULT_TARGET = "http://localhost:3001/api/health"
DURATION_SECONDS = 300
TARGET_RPS = 50
CONCURRENT_REQUESTS = 10
TIMEOUT_SECONDS = 10


@dataclass
class TestResult:
    endpoint: str
    requests_offered: int
    requests_started: int
    requests_completed: int
    saturation_count: int
    requests_succeeded: int
    requests_failed: int
    total_duration_ms: float
    avg_latency_ms: float
    p50_latency_ms: float
    p95_latency_ms: float
    p99_latency_ms: float
    error_rate: float
    rps: float


def percentile(values: List[float], p: float) -> float:
    if not values:
        return 0.0
    position = (len(values) - 1) * p / 100
    low = int(position)
    high = min(low + 1, len(values) - 1)
    return values[low] * (1 - position + low) + values[high] * (position - low)


def validate_results(result: TestResult, min_success_rate: float = 0.95,
                     max_p50_latency_ms: float = 50, max_p95_latency_ms: float = 500,
                     max_p99_latency_ms: float = 1000, min_requests: int = 1) -> Tuple[bool, List[str]]:
    failures = []
    if result.requests_completed < min_requests:
        failures.append(f"Completed requests {result.requests_completed} below minimum {min_requests}")
    if result.requests_completed == 0:
        failures.append("No requests completed")
    if result.error_rate > 1 - min_success_rate:
        failures.append(f"Error rate {result.error_rate:.1%} exceeds threshold {1 - min_success_rate:.1%}")
    for name, value, threshold in (("p50", result.p50_latency_ms, max_p50_latency_ms),
                                   ("p95", result.p95_latency_ms, max_p95_latency_ms),
                                   ("p99", result.p99_latency_ms, max_p99_latency_ms)):
        if value > threshold:
            failures.append(f"{name} latency {value:.0f}ms exceeds threshold {threshold}ms")
    return not failures, failures


def _request(url: str, timeout: int) -> Tuple[float, bool]:
    start = time.monotonic()
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return (time.monotonic() - start) * 1000, 200 <= response.status < 300
    except (urllib.error.URLError, TimeoutError, OSError):
        return (time.monotonic() - start) * 1000, False


async def execute_test(target: str, duration_seconds: float, target_rps: int,
                       concurrent_requests: int, timeout: int) -> TestResult:
    if duration_seconds <= 0 or target_rps <= 0 or concurrent_requests <= 0 or timeout <= 0:
        raise ValueError("duration, rps, concurrency, and timeout must be positive")
    interval = 1.0 / target_rps
    started_at = time.monotonic()
    semaphore = asyncio.Semaphore(concurrent_requests)
    active = saturation = started = completed = successes = failures = 0
    latencies: List[float] = []

    async def send():
        nonlocal active, started, completed, successes, failures
        async with semaphore:
            active += 1
            started += 1
            try:
                latency, success = await asyncio.to_thread(_request, target, timeout)
                latencies.append(latency)
                if success:
                    successes += 1
                else:
                    failures += 1
            finally:
                completed += 1
                active -= 1

    tasks = []
    offered = 0
    while True:
        deadline = started_at + offered * interval
        remaining = deadline - time.monotonic()
        if remaining > 0:
            await asyncio.sleep(remaining)
        if time.monotonic() >= started_at + duration_seconds:
            break
        if active >= concurrent_requests:
            saturation += 1
        offered += 1
        tasks.append(asyncio.create_task(send()))
    await asyncio.gather(*tasks)
    elapsed = time.monotonic() - started_at
    ordered = sorted(latencies)
    return TestResult(target, offered, started, completed, saturation, successes, failures,
                      elapsed * 1000, statistics.mean(latencies) if latencies else 0,
                      statistics.median(latencies) if latencies else 0, percentile(ordered, 95),
                      percentile(ordered, 99), failures / completed if completed else 0,
                      offered / duration_seconds)


async def main() -> int:
    parser = argparse.ArgumentParser(description="Load test for Capado backend")
    parser.add_argument("--target", default=DEFAULT_TARGET)
    parser.add_argument("--duration", type=float, default=DURATION_SECONDS)
    parser.add_argument("--rps", type=int, default=TARGET_RPS)
    parser.add_argument("--concurrent", type=int, default=CONCURRENT_REQUESTS)
    parser.add_argument("--timeout", type=int, default=TIMEOUT_SECONDS)
    parser.add_argument("--validate", action="store_true")
    parser.add_argument("--min-success", type=float, default=0.95)
    parser.add_argument("--max-p50", type=float, default=50)
    parser.add_argument("--max-p95", type=float, default=500)
    parser.add_argument("--max-p99", type=float, default=1000)
    parser.add_argument("--min-requests", type=int, default=1)
    args = parser.parse_args()
    if not 0 <= args.min_success <= 1 or min(args.max_p50, args.max_p95, args.max_p99) < 0 or args.min_requests < 1:
        print("Load test failed: invalid validation thresholds")
        return 2
    try:
        result = await execute_test(args.target, args.duration, args.rps, args.concurrent, args.timeout)
    except ValueError as exc:
        print(f"Load test failed: {exc}")
        return 2
    print(f"Endpoint: {result.endpoint}")
    print(f"Duration: {result.total_duration_ms / 1000:.3f}s")
    print(f"Offered: {result.requests_offered}; started: {result.requests_started}; completed: {result.requests_completed}")
    print(f"Succeeded: {result.requests_succeeded}; failed: {result.requests_failed}; saturated offers: {result.saturation_count}")
    print(f"Error rate: {result.error_rate:.1%}; offered RPS: {result.rps:.1f}")
    print(f"Latency p50/p95/p99: {result.p50_latency_ms:.1f}/{result.p95_latency_ms:.1f}/{result.p99_latency_ms:.1f} ms")
    if not args.validate:
        return 0
    passed, issues = validate_results(result, args.min_success, args.max_p50, args.max_p95,
                                      args.max_p99, args.min_requests)
    if not passed:
        print("Validation failed:")
        for issue in issues:
            print(f"- {issue}")
        print("Acceptance: FAIL")
        return 1
    print("All validation criteria passed!")
    print("Acceptance: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
