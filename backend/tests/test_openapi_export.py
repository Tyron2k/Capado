"""The contract exporter must work without deployment configuration or startup."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


def test_export_ignores_dotenv_and_inherited_deployment_settings(tmp_path):
    source = Path(__file__).resolve().parents[1] / "app"
    shutil.copytree(
        source, tmp_path / "app", ignore=shutil.ignore_patterns("__pycache__")
    )
    # These deliberately fail normal settings validation or engine construction.
    # They are synthetic fixtures, never a copy of an operator's dotenv file.
    poison = (
        "ENVIRONMENT=production\nJWT_SECRET_KEY=secret\nDATABASE_URL=invalid://dotenv\n"
    )
    (tmp_path / ".env").write_text(poison)
    env = {
        **os.environ,
        "ENVIRONMENT": "production",
        "JWT_SECRET_KEY": "secret",
        "DATABASE_URL": "invalid://inherited",
    }
    outputs = []
    for _ in range(2):
        result = subprocess.run(
            [sys.executable, "-m", "app.openapi"],
            cwd=tmp_path,
            env=env,
            capture_output=True,
            text=True,
            check=True,
        )
        outputs.append(result.stdout)
    assert outputs[0] == outputs[1]
    schema = json.loads(outputs[0])
    assert "/api/projects" in schema["paths"]
    assert "invalid://dotenv" not in outputs[0]
    assert "invalid://inherited" not in outputs[0]


def test_response_defaults_are_required_but_nullable_inputs_stay_optional():
    from app.schemas.project import ProjectCreate, ProjectResponse, ProjectUpdate

    output = ProjectResponse.model_json_schema(mode="serialization")
    assert {"folder_id", "position", "priority", "customer_name"} <= set(
        output["required"]
    )
    assert {"type": "null"} in output["properties"]["folder_id"]["anyOf"]
    assert "folder_id" not in ProjectCreate.model_json_schema()["required"]
    assert "folder_id" not in ProjectUpdate.model_json_schema().get("required", [])
