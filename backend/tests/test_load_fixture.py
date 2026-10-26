"""The local fixture command must reject other targets before any migration/write."""

from unittest.mock import Mock

import pytest

from app.config import settings
from tests import seed_load_test


@pytest.mark.parametrize(
    ("environment", "url"),
    [
        ("production", "postgresql+asyncpg://load_test:local@db/capado_load_test"),
        ("test", "postgresql+asyncpg://load_test:local@localhost/capado_load_test"),
        ("test", "postgresql+asyncpg://load_test:local@db/capado"),
        ("test", "postgresql+asyncpg://postgres:local@db/capado_load_test"),
    ],
)
async def test_load_fixture_rejects_other_targets_before_migrations(
    monkeypatch, environment, url
):
    monkeypatch.setattr(settings, "environment", environment)
    monkeypatch.setattr(settings, "database_url", url)
    migrate = Mock()
    monkeypatch.setattr(seed_load_test.subprocess, "run", migrate)

    with pytest.raises(ValueError, match="isolated load-test database"):
        await seed_load_test.main()

    migrate.assert_not_called()
