"""Run the real final gate against success, failure, cancellation and skip states."""

import json
import os
import re
import shutil
import subprocess
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

    def run_gate(self, results):
        return subprocess.run(
            ["bash", "-c", self.script],
            capture_output=True,
            env=os.environ | {"JOB_RESULTS": json.dumps(results)},
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
