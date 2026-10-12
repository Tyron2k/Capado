"""Exercise edge decisions without invoking Actions or a registry."""

import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

SHA = "1" * 40
NOW = datetime(2026, 10, 11, tzinfo=UTC)


class EdgeTests(unittest.TestCase):
    def setUp(self):
        self.runs = [
            {
                "id": 1,
                "head_sha": SHA,
                "head_branch": "main",
                "status": "completed",
                "conclusion": "success",
                "event": "schedule",
            }
        ]
        self.artifacts = [
            {
                "name": "publication-edge",
                "expired": False,
                "workflow_run": {"id": 1},
                "created_at": (NOW - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
        ]
        self.calls = []
        workflow = (
            Path(__file__).resolve().parents[2] / "workflows/build-images.yml"
        ).read_text()
        self.script = textwrap.dedent(
            workflow.split("        run: |\n", 1)[1].split("\n  publish:", 1)[0]
        )

    def decision(self, force=False, api_error=False):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for key, items in (
                ("workflow_runs", self.runs),
                ("artifacts", self.artifacts),
            ):
                pages = [
                    {key: items[i : i + 100]} for i in range(0, len(items), 100)
                ] or [{key: []}]
                (root / key).write_text(json.dumps(pages))
            gh = root / "gh"
            gh.write_text(
                f"#!{sys.executable}\n"
                + textwrap.dedent("""
                import os, sys
                from pathlib import Path
                assert '--paginate' in sys.argv and '--slurp' in sys.argv
                with open('calls', 'a') as calls:
                    calls.write(sys.argv[-1] + '\\n')
                if os.environ['API_ERROR'] == 'true':
                    sys.exit(1)
                print(Path('artifacts' if '/artifacts?' in sys.argv[-1] else 'workflow_runs').read_text())
            """)
            )
            gh.chmod(0o755)
            date = root / "date"
            date.write_text(f"#!/bin/sh\necho {int(NOW.timestamp())}\n")
            date.chmod(0o755)
            result = subprocess.run(
                ["bash", "-c", self.script],
                cwd=root,
                capture_output=True,
                text=True,
                env=os.environ
                | {
                    "PATH": directory + os.pathsep + os.environ["PATH"],
                    "FORCE": str(force).lower(),
                    "GITHUB_SHA": SHA,
                    "GITHUB_REPOSITORY": "owner/repo",
                    "GITHUB_OUTPUT": str(root / "output"),
                    "API_ERROR": str(api_error).lower(),
                },
            )
            self.calls = (
                (root / "calls").read_text().splitlines()
                if (root / "calls").exists()
                else []
            )
            if result.returncode:
                raise RuntimeError(result.stderr)
            return "build=true" in (root / "output").read_text()

    def test_force_avoids_api(self):
        self.assertTrue(self.decision(True))
        self.assertEqual(self.calls, [])

    def test_no_run_or_receipt_requires_build(self):
        self.runs = []
        self.assertTrue(self.decision())
        self.setUp()
        self.artifacts = []
        self.assertTrue(self.decision())

    def test_recent_matching_publication_skips_build(self):
        self.assertFalse(self.decision())
        self.assertTrue(all("/jobs" not in call for call in self.calls))

    def test_changed_source_requires_build(self):
        self.runs[0]["head_sha"] = "2" * 40
        self.assertTrue(self.decision())

    def test_seven_day_boundary(self):
        for age, expected in (
            (timedelta(days=7), True),
            (timedelta(days=8), True),
            (timedelta(days=7, seconds=-1), False),
        ):
            with self.subTest(age=age):
                self.artifacts[0]["created_at"] = (NOW - age).strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                )
                self.assertEqual(self.decision(), expected)

    def test_expired_or_unrelated_artifact_is_not_publication(self):
        self.artifacts[0]["expired"] = True
        self.assertTrue(self.decision())
        self.artifacts[0].update(expired=False, name="security-backend")
        self.assertTrue(self.decision())

    def test_failed_cancelled_incomplete_or_off_branch_runs_are_ignored(self):
        for update in (
            {"conclusion": "failure"},
            {"conclusion": "cancelled"},
            {"status": "in_progress"},
            {"head_branch": "feature"},
            {"event": "push"},
        ):
            with self.subTest(update=update):
                self.setUp()
                self.runs[0].update(update)
                self.assertTrue(self.decision())

    def test_receipt_time_handles_reruns_and_unordered_pages(self):
        self.runs = [self.runs[0] | {"id": i} for i in range(1, 203)]
        self.artifacts[0]["workflow_run"]["id"] = 202
        self.assertFalse(self.decision())
        self.assertEqual(len(self.calls), 2)

    def test_future_receipt_and_api_errors_fail_closed(self):
        self.artifacts[0]["created_at"] = (NOW + timedelta(days=1)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        with self.assertRaises(RuntimeError):
            self.decision()

        self.setUp()
        with self.assertRaises(RuntimeError):
            self.decision(api_error=True)


if __name__ == "__main__":
    unittest.main()
