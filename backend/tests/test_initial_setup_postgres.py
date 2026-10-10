"""Initial administrator claim and refresh issuance in independent transactions."""

import asyncio
from contextlib import asynccontextmanager

import httpx
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.main import app
from app.models.audit import AuditLog
from app.models.user import RefreshToken, User
from app.utils.rate_limit import rate_limit_auth
from tests.test_resource_group_orm import resource_database  # noqa: F401
from tests.test_utc_migration_postgres import legacy_database  # noqa: F401

PASSWORD = "Synthetic-setup-password-123"


@asynccontextmanager
async def setup_client(engine):
    async def sessions():
        async with AsyncSession(engine, expire_on_commit=False) as session:
            yield session

    old = dict(app.dependency_overrides)
    app.dependency_overrides[get_session] = sessions
    app.dependency_overrides[rate_limit_auth] = lambda: None
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://test",
        ) as client:
            yield client
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(old)


async def claim(client, email):
    return await client.post(
        "/api/auth/setup",
        json={"name": "Initial admin", "email": email, "password": PASSWORD},
    )


async def counts(engine):
    async with AsyncSession(engine) as session:
        return tuple(
            [
                await session.scalar(sa.select(sa.func.count()).select_from(model))
                for model in (User, RefreshToken)
            ]
        )


async def test_first_setup_second_claim_and_normal_login(resource_database):
    async with setup_client(resource_database) as client:
        assert (await client.get("/api/auth/setup-status")).json() == {"required": True}
        first = await claim(client, "first@example.test")
        assert first.status_code == 201, first.text
        assert first.json()["user"]["role"] == "admin"
        assert "refresh_token" not in first.json()
        assert "httponly" in first.headers["set-cookie"].lower()
        assert (await claim(client, "second@example.test")).status_code == 403
        assert (await client.get("/api/auth/setup-status")).json() == {
            "required": False
        }
        assert await counts(resource_database) == (1, 1)
        login = await client.post(
            "/api/auth/login",
            json={"email": "first@example.test", "password": PASSWORD},
        )
        assert login.status_code == 200, login.text
        assert login.json()["user"]["id"] == first.json()["user"]["id"]
    assert await counts(resource_database) == (1, 2)


async def test_two_simultaneous_setup_claims_create_one_admin(
    resource_database, monkeypatch
):
    original = AsyncSession.execute
    held, contender_seen, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    owner = None
    pid = None

    async def executing(self, statement, *args, **kwargs):
        nonlocal owner, pid
        sql = str(statement)
        if owner is not None and self is not owner and "pg_advisory_xact_lock" in sql:
            pid = (
                await original(self, sa.text("SELECT pg_backend_pid()"))
            ).scalar_one()
            contender_seen.set()
        result = await original(self, statement, *args, **kwargs)
        if "count(*)" in sql and "FROM users" in sql:
            if owner is None:
                owner = self
                held.set()
                await asyncio.wait_for(release.wait(), timeout=10)
            else:
                contender_seen.set()
        return result

    monkeypatch.setattr(AsyncSession, "execute", executing)
    tasks = []
    async with setup_client(resource_database) as client:
        try:
            tasks.append(asyncio.create_task(claim(client, "first@example.test")))
            await asyncio.wait_for(held.wait(), timeout=10)
            tasks.append(asyncio.create_task(claim(client, "second@example.test")))
            await asyncio.wait_for(contender_seen.wait(), timeout=10)
            if pid is not None:
                async with AsyncSession(resource_database) as observer:
                    async with asyncio.timeout(5):
                        while not await observer.scalar(
                            sa.text(
                                "SELECT EXISTS (SELECT 1 FROM pg_locks WHERE pid=:pid AND locktype='advisory' AND NOT granted)"
                            ),
                            {"pid": pid},
                        ):
                            await asyncio.sleep(0.01)
                assert not any(task.done() for task in tasks)
            release.set()
            responses = await asyncio.wait_for(asyncio.gather(*tasks), timeout=15)
        finally:
            release.set()
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
    assert sorted(response.status_code for response in responses) == [201, 403]
    assert await counts(resource_database) == (1, 1)
    async with AsyncSession(resource_database) as session:
        users = (await session.scalars(sa.select(User))).all()
        tokens = (await session.scalars(sa.select(RefreshToken))).all()
        assert users[0].role == "admin"
        assert all(token.user_id == users[0].id for token in tokens)


async def test_token_insert_failure_rolls_back_user_audit_and_claim_lock(
    resource_database, monkeypatch
):
    original = AsyncSession.commit

    async def failing(self):
        if any(isinstance(row, RefreshToken) for row in self.new):
            await self.flush()
            raise RuntimeError("Synthetic failure before setup commit")
        return await original(self)

    async with setup_client(resource_database) as client:
        with monkeypatch.context() as patch:
            patch.setattr(AsyncSession, "commit", failing)
            failed = await claim(client, "retry@example.test")
        assert failed.status_code == 500
        assert "set-cookie" not in failed.headers
        assert await counts(resource_database) == (0, 0)
        async with AsyncSession(resource_database) as session:
            assert (
                await session.scalar(
                    sa.select(sa.func.count())
                    .select_from(AuditLog)
                    .where(AuditLog.entity_type == "users")
                )
                == 0
            )
        retry = await asyncio.wait_for(claim(client, "retry@example.test"), timeout=5)
        assert retry.status_code == 201, retry.text
    assert await counts(resource_database) == (1, 1)
