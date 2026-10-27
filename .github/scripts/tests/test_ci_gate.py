"""Run the real final gate against success, failure, cancellation and skip states."""

import json
import os
import re
import shutil
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

WORKFLOW = Path(__file__).resolve().parents[2] / "workflows/ci.yml"


@unittest.skipUnless(shutil.which("jq"), "The Actions runner supplies jq")
class CiGateTests(unittest.TestCase):
    def setUp(self):
        workflow = WORKFLOW.read_text()
        jobs, gate = workflow.split("jobs:\n", 1)[1].split("  ci-passed:\n", 1)
        self.jobs = re.findall(r"^  ([a-z][a-z-]+):$", jobs, re.MULTILINE)
        self.dependencies = re.findall(r"^      - ([a-z][a-z-]+)$", gate, re.MULTILINE)
        self.script = textwrap.dedent(gate.split("        run: |\n", 1)[1])
        self.results = {job: {"result": "success"} for job in self.jobs}

    def run_gate(self, results, artifact_statuses=None, api_error=False):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            gh = root / "gh"
            gh.write_text(
                "#!/usr/bin/env bash\n"
                'if [ "$API_ERROR" = true ]; then exit 7; fi\n'
                'printf "%s" "$ARTIFACT_STATUSES" | jq -r "${@: -1}"\n'
            )
            gh.chmod(0o755)
            return subprocess.run(
                ["bash", "-c", self.script],
                cwd=root,
                capture_output=True,
                env=os.environ
                | {
                    "JOB_RESULTS": json.dumps(results),
                    "PATH": f"{root}:{os.environ['PATH']}",
                    "CHECK_RENOVATE_ARTIFACTS": str(
                        artifact_statuses is not None
                    ).lower(),
                    "ARTIFACT_STATUSES": json.dumps({"statuses": artifact_statuses}),
                    "REPOSITORY": "Tyron2k/Capado",
                    "PR_HEAD": "a" * 40,
                    "API_ERROR": str(api_error).lower(),
                },
            ).returncode

    def test_every_configured_check_is_required(self):
        self.assertEqual(set(self.dependencies), set(self.jobs))
        self.assertEqual(len(self.dependencies), 8)
        self.assertEqual(self.run_gate(self.results), 0)

    def test_any_failed_cancelled_or_skipped_check_blocks_merge(self):
        for job in self.jobs:
            for status in ("failure", "cancelled", "skipped"):
                with self.subTest(job=job, status=status):
                    results = self.results | {job: {"result": status}}
                    self.assertNotEqual(self.run_gate(results), 0)

    def test_empty_check_set_is_not_a_success(self):
        self.assertNotEqual(self.run_gate({}), 0)

    def test_successful_native_artifact_update_allows_renovate_merge(self):
        statuses = [{"context": "renovate/artifacts", "state": "success"}]
        self.assertEqual(self.run_gate(self.results, statuses), 0)

    def test_failed_pending_missing_or_unreadable_artifacts_block_renovate(self):
        for state in ("failure", "error", "pending"):
            with self.subTest(state=state):
                statuses = [{"context": "renovate/artifacts", "state": state}]
                self.assertNotEqual(self.run_gate(self.results, statuses), 0)
        self.assertNotEqual(self.run_gate(self.results, []), 0)
        self.assertNotEqual(
            self.run_gate(self.results, [{"context": "unrelated", "state": "success"}]),
            0,
        )
        self.assertNotEqual(self.run_gate(self.results, [], api_error=True), 0)
