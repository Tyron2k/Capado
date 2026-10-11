"""Execute the real release gate with isolated Actions API responses."""

import json
import os
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

SHA = "1" * 40


@pytest.mark.parametrize(
    "event,sha,status,conclusion,gate,accepted",
    [
        ("workflow_dispatch", SHA, "completed", "success", "success", True),
        ("push", SHA, "completed", "success", "success", False),
        ("pull_request", SHA, "completed", "success", "success", False),
        ("workflow_dispatch", "2" * 40, "completed", "success", "success", False),
        ("workflow_dispatch", SHA, "completed", "failure", "success", False),
        ("workflow_dispatch", SHA, "completed", "cancelled", "success", False),
        ("workflow_dispatch", SHA, "in_progress", None, "success", False),
        ("workflow_dispatch", SHA, "completed", "success", "skipped", False),
        ("workflow_dispatch", SHA, "completed", "success", "failure", False),
        ("workflow_dispatch", SHA, "completed", "success", None, False),
    ],
)
def test_release_requires_full_success_on_exact_sha(
    tmp_path, event, sha, status, conclusion, gate, accepted
):
    if not shutil.which("jq"):
        pytest.skip("The Actions runner's jq is needed to exercise the shell gate")
    workflow = Path(__file__).resolve().parents[2] / ".github/workflows/release.yml"
    step = workflow.read_text().split(
        "      - name: Require successful full validation\n", 1
    )[1]
    script = textwrap.dedent(
        step.split("        run: |\n", 1)[1].split("\n  publish:", 1)[0]
    )
    fixture = {
        "runs": [
            {
                "workflow_runs": [
                    {
                        "id": 123,
                        "event": event,
                        "head_sha": sha,
                        "status": status,
                        "conclusion": conclusion,
                    }
                ]
            }
        ],
        # Two pages exercise the real pagination handling, including a missing gate.
        "jobs": [
            {"jobs": [{"name": "Unrelated job", "conclusion": "success"}]},
            {"jobs": [{"name": "CI passed", "conclusion": gate}] if gate else []},
        ],
    }
    fixture_file = tmp_path / "responses.json"
    fixture_file.write_text(json.dumps(fixture))
    fake_gh = tmp_path / "gh"
    fake_gh.write_text("""#!/usr/bin/env python3
import json, os, sys
endpoint = sys.argv[-1]
with open(os.environ['API_CALLS'], 'a') as calls:
    calls.write(endpoint + '\\n')
data = json.load(open(os.environ['API_FIXTURE']))
key = 'runs' if '/workflows/ci.yml/runs?' in endpoint else 'jobs'
for page in data[key]:
    print(json.dumps(page))
""")
    fake_gh.chmod(0o700)
    output = tmp_path / "summary"
    calls = tmp_path / "calls"
    env = os.environ | {
        "PATH": str(tmp_path) + os.pathsep + os.environ["PATH"],
        "API_FIXTURE": str(fixture_file),
        "API_CALLS": str(calls),
        "GITHUB_REPOSITORY": "test-owner/test-repo",
        "SOURCE_SHA": SHA,
        "GITHUB_STEP_SUMMARY": str(output),
        "GH_TOKEN": "synthetic-offline-only",
    }
    result = subprocess.run(
        ["bash", "-c", script], env=env, capture_output=True, text=True
    )
    assert (result.returncode == 0) == accepted, result.stdout + result.stderr
    requests = calls.read_text().splitlines()
    assert requests[0].endswith(
        f"head_sha={SHA}&event=workflow_dispatch&status=success&per_page=100"
    )
    if accepted:
        assert requests[1].endswith("/runs/123/jobs?filter=latest&per_page=100")
        assert f"Source: {SHA}" in output.read_text()
    else:
        assert not output.exists()
