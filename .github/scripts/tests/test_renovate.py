"""Exercise the real workflow's selection logic with isolated GitHub API fixtures."""

import json
import os
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

WORKFLOW = Path(__file__).resolve().parents[2] / "workflows/renovate.yml"


def pull(branch, *, author="tyron2k-renovate[bot]", repo="Tyron2k/Capado", auto=True):
    return {
        "head": {"ref": branch, "sha": "a" * 40, "repo": {"full_name": repo}},
        "user": {"login": author},
        "auto_merge": {} if auto else None,
        "draft": False,
    }


class RenovateSelectionTests(unittest.TestCase):
    def select(self, pulls, *, event="schedule", behind=0, api_error=False):
        step = WORKFLOW.read_text().split("      - name: Select pending update work\n")[
            1
        ]
        script = textwrap.dedent(
            step.split("        run: |\n")[1].split("\n      - ")[0]
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            gh = root / "gh"
            gh.write_text(
                "#!/usr/bin/env bash\n"
                'if [ "$API_ERROR" = true ]; then exit 7; fi\n'
                'case "$*" in\n'
                '  *"/compare/"*) printf "%s\\n" "$BEHIND" ;;\n'
                '  *) printf "%s\\n" "$PULLS" ;;\n'
                "esac\n"
            )
            gh.chmod(0o755)
            output = root / "output"
            completed = subprocess.run(
                ["bash", "-c", script],
                cwd=root,
                capture_output=True,
                text=True,
                env=os.environ
                | {
                    "PATH": f"{root}:{os.environ['PATH']}",
                    "GITHUB_OUTPUT": str(output),
                    "GITHUB_STEP_SUMMARY": str(root / "summary"),
                    "REPOSITORY": "Tyron2k/Capado",
                    "EVENT_NAME": event,
                    "PULLS": json.dumps([pulls]),
                    "BEHIND": str(behind),
                    "API_ERROR": str(api_error).lower(),
                },
            )
            values = (
                dict(line.split("=", 1) for line in output.read_text().splitlines())
                if output.exists()
                else {}
            )
            return completed, values

    def test_empty_daily_run_keeps_native_fallback_eligible(self):
        completed, output = self.select([])
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(output, {"run": "true", "force": "{}"})

    def test_open_group_suppresses_parallel_maintenance(self):
        completed, output = self.select([pull("renovate/all-minor-patch")])
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertFalse(json.loads(output["force"])["lockFileMaintenance"]["enabled"])

    def test_existing_fallback_finishes_before_another_automatic_branch(self):
        completed, output = self.select([pull("renovate/lock-file-maintenance")])
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(json.loads(output["force"]), {"prConcurrentLimit": 1})

    def test_manual_runtime_review_does_not_suppress_fallback(self):
        completed, output = self.select([pull("renovate/python-runtime", auto=False)])
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(json.loads(output["force"]), {})

    def test_main_push_without_stale_automatic_work_skips_bot(self):
        for pulls in ([], [pull("renovate/all-minor-patch")]):
            with self.subTest(pulls=pulls):
                completed, output = self.select(pulls, event="push")
                self.assertEqual(completed.returncode, 0, completed.stderr)
                self.assertEqual(output["run"], "false")

    def test_main_push_restarts_bot_for_behind_auto_merge_pr(self):
        completed, output = self.select(
            [pull("renovate/all-minor-patch")], event="push", behind=1
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(output["run"], "true")

    def test_forks_other_authors_drafts_and_manual_prs_do_not_trigger_writes(self):
        draft = pull("renovate/all-minor-patch") | {"draft": True}
        for candidate in (
            pull("renovate/all-minor-patch", repo="someone/Capado"),
            pull("renovate/all-minor-patch", author="someone"),
            pull("renovate/python-runtime", auto=False),
            draft,
        ):
            with self.subTest(candidate=candidate):
                completed, output = self.select([candidate], event="push", behind=1)
                self.assertEqual(completed.returncode, 0, completed.stderr)
                self.assertEqual(output["run"], "false")

    def test_api_failure_is_not_a_successful_noop(self):
        completed, output = self.select([], api_error=True)
        self.assertNotEqual(completed.returncode, 0)
        self.assertNotIn("run", output)

    def test_invalid_compare_response_does_not_silently_skip_rebase(self):
        completed, output = self.select(
            [pull("renovate/all-minor-patch")], event="push", behind="null"
        )
        self.assertNotEqual(completed.returncode, 0)
        self.assertNotIn("run", output)
