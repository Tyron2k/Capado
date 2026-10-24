import asyncio
import importlib.util
import threading
import time
import subprocess
import sys
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "test_load_50rps.py"
spec = importlib.util.spec_from_file_location("load_runner", SCRIPT)
runner = importlib.util.module_from_spec(spec)
assert spec and spec.loader
import sys
sys.modules[spec.name] = runner
spec.loader.exec_module(runner)


class ControlledHandler(BaseHTTPRequestHandler):
    request_times = []

    def do_GET(self):
        type(self).request_times.append(time.monotonic())
        if self.path in ("/slow", "/slow-error"):
            time.sleep(0.15)
        self.send_response(503 if self.path in ("/error", "/slow-error") else 200)
        self.end_headers()

    def log_message(self, *_args):
        pass


class LoadRunnerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), ControlledHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def setUp(self):
        ControlledHandler.request_times.clear()

    def test_constant_offer_rate_and_counts_with_slow_and_failed_responses(self):
        result = asyncio.run(runner.execute_test(
            target=self.base + "/slow-error", duration_seconds=0.8, target_rps=20,
            concurrent_requests=2, timeout=2,
        ))
        self.assertEqual(result.requests_offered, 16)
        self.assertEqual(result.requests_started, 16)
        self.assertEqual(result.requests_completed, 16)
        self.assertEqual(result.requests_failed, 16)
        self.assertGreaterEqual(result.saturation_count, 1)

    def test_request_starts_follow_monotonic_rate_schedule(self):
        asyncio.run(runner.execute_test(
            target=self.base, duration_seconds=0.8, target_rps=10,
            concurrent_requests=2, timeout=2,
        ))
        starts = ControlledHandler.request_times
        gaps = [b - a for a, b in zip(starts, starts[1:])]
        self.assertTrue(all(0.07 <= gap <= 0.13 for gap in gaps), gaps)

    def test_validation_fails_for_tail_latency_and_too_few_requests(self):
        result = runner.TestResult(
            endpoint="local", requests_offered=2, requests_started=2,
            requests_completed=2, saturation_count=0, requests_succeeded=2,
            requests_failed=0, total_duration_ms=1, avg_latency_ms=1,
            p50_latency_ms=1, p95_latency_ms=600, p99_latency_ms=1200,
            error_rate=0, rps=2,
        )
        passed, _ = runner.validate_results(result, min_requests=3)
        self.assertFalse(passed)

    def test_validation_fails_for_p95_without_minimum_request_violation(self):
        result = runner.TestResult(
            endpoint="local", requests_offered=100, requests_started=100,
            requests_completed=100, saturation_count=0, requests_succeeded=100,
            requests_failed=0, total_duration_ms=1000, avg_latency_ms=10,
            p50_latency_ms=10, p95_latency_ms=600, p99_latency_ms=700,
            error_rate=0, rps=100,
        )
        passed, failures = runner.validate_results(result, min_requests=100)
        self.assertFalse(passed)
        self.assertTrue(any("p95" in failure.lower() for failure in failures), failures)
        self.assertFalse(any("minimum request" in failure.lower() for failure in failures), failures)

    def test_validation_fails_for_p99_without_minimum_request_violation(self):
        result = runner.TestResult(
            endpoint="local", requests_offered=100, requests_started=100,
            requests_completed=100, saturation_count=0, requests_succeeded=100,
            requests_failed=0, total_duration_ms=1000, avg_latency_ms=10,
            p50_latency_ms=10, p95_latency_ms=20, p99_latency_ms=1200,
            error_rate=0, rps=100,
        )
        passed, failures = runner.validate_results(result, min_requests=100)
        self.assertFalse(passed)
        self.assertTrue(any("p99" in failure.lower() for failure in failures), failures)
        self.assertFalse(any("minimum request" in failure.lower() for failure in failures), failures)

    def test_no_validate_cli_does_not_crash(self):
        command = [sys.executable, str(SCRIPT), "--target", self.base,
                   "--duration", "0.1", "--rps", "2", "--concurrent", "1"]
        completed = subprocess.run(command, text=True, capture_output=True, check=False)
        self.assertEqual(completed.returncode, 0, completed.stderr + completed.stdout)

    def test_validate_cli_returns_failure_without_pass_on_too_few_requests(self):
        command = [sys.executable, str(SCRIPT), "--target", self.base,
                   "--duration", "0.1", "--rps", "2", "--concurrent", "1",
                   "--validate", "--min-requests", "2"]
        completed = subprocess.run(command, text=True, capture_output=True, check=False)
        self.assertEqual(completed.returncode, 1, completed.stderr + completed.stdout)
        self.assertIn("Acceptance: FAIL", completed.stdout)
        self.assertNotIn("Acceptance: PASS", completed.stdout)


if __name__ == "__main__":
    unittest.main()
