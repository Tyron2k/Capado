"""Export the HTTP contract without operator settings or application startup.

Run ``python -m app.openapi``. A fresh interpreter in an empty working directory
imports the real app with a fixed, non-operational environment. This keeps local
dotenv files and inherited credentials out of schema generation without adding
a configuration bypass to the production application.
"""

import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory


def main() -> None:
    """Write deterministic OpenAPI JSON to stdout; never enter the lifespan."""
    backend = Path(__file__).resolve().parents[1]
    with TemporaryDirectory(prefix="capado-openapi-") as directory:
        subprocess.run(
            [
                sys.executable,
                "-c",
                "import json, sys; from app.main import app; "
                "json.dump(app.openapi(), sys.stdout, sort_keys=True); print()",
            ],
            cwd=directory,
            env={
                "PYTHONPATH": str(backend),
                "ENVIRONMENT": "test",
                "DATABASE_URL": (
                    "postgresql+asyncpg://schema-only:schema-only@localhost/schema-only"
                ),
                "JWT_SECRET_KEY": "offline-schema-generation-only-never-used-for-auth",
            },
            check=True,
        )


if __name__ == "__main__":
    main()
