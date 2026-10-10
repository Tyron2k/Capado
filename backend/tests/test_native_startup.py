"""Keep native startup on the same migration path as the Docker runtime."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.main import run_migrations


def test_migrations_use_backend_directory():
    with patch("subprocess.run", return_value=SimpleNamespace(returncode=0)) as run:
        run_migrations()
    root = Path(__file__).resolve().parents[1]
    assert run.call_args.kwargs["cwd"] == str(root)
    assert run.call_args.kwargs["env"]["PYTHONPATH"] == str(root)


def test_test_runtime_ignores_dotenv(tmp_path):
    import os
    import subprocess
    import sys

    (tmp_path / ".env").write_text(
        "JWT_SECRET_KEY=dotenv-canary-that-must-not-be-loaded\n"
    )
    env = {
        "PATH": os.environ["PATH"],
        "PYTHONPATH": str(Path(__file__).resolve().parents[1]),
        "ENVIRONMENT": "test",
    }
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from app.config import settings; assert settings.jwt_secret_key != 'dotenv-canary-that-must-not-be-loaded'",
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr


def test_reset_rejects_existing_or_remote_databases():
    import pytest

    from tests.e2e_server import guarded_url

    for value in (
        "postgresql+asyncpg://localhost/production",
        "postgresql+asyncpg://remote.example/capado_e2e_fake",
        "postgresql+asyncpg://127.0.0.1/capado",
    ):
        with pytest.raises(ValueError, match="disposable"):
            guarded_url(value)
    assert (
        guarded_url("postgresql+asyncpg://127.0.0.1/capado_e2e_owned").database
        == "capado_e2e_owned"
    )
