"""Local recovery on migrated PostgreSQL, including normal authentication gates."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import event, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_session
from app.main import app
from app.models.audit import AuditLog
from app.models.user import RefreshToken, User
from app.scripts import recover_admin as recovery
from app.services.auth_service import hash_password, verify_password
from tests.test_combined_planning_postgres import combined_database  # noqa: F401
from tests.test_utc_migration_postgres import legacy_database  # noqa: F401

EMAIL = "recovery@example.test"
OLD = "forgotten-test-password"
TEMPORARY = "temporary-test-password"


@pytest.fixture
async def account(combined_database):
    session, _ = combined_database
    user = User(
        email=EMAIL,
        name="Fictional admin",
        role="admin",
        is_active=True,
        password_hash=hash_password(OLD),
        must_change_password=False,
        external_id="fictional-oidc-identity",
        scope_group_ids=[uuid4()],
    )
    session.add(user)
    await session.commit()
    return user


@pytest.mark.parametrize("rotations", [0, 2], ids=["active", "rotated-and-grace-fork"])
async def test_recovery_revokes_refresh_and_preserves_normal_login_password_gate(
    combined_database,
    account,
    rotations,
    monkeypatch,
):
    session, _ = combined_database
    # Keep the grace path open even on a slow runner: expiry must not hide a
    # failed revocation and accidentally make this security regression pass.
    monkeypatch.setattr(settings, "refresh_reuse_grace_seconds", 3600)
    other = User(
        email="viewer@example.test", name="Fictional viewer", password_hash="test-only"
    )
    session.add(other)
    await session.flush()
    other_token = RefreshToken(
        user_id=other.id,
        token_hash="other-test-token",
        expires_at=datetime.now(UTC) + timedelta(days=1),
    )
    session.add(other_token)
    await session.commit()

    async def override():
        yield session

    app.dependency_overrides[get_session] = override
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            old_login = await client.post(
                "/api/auth/login", json={"email": EMAIL, "password": OLD}
            )
            assert old_login.status_code == 200
            old_access = old_login.json()["access_token"]
            old_cookies = [client.cookies.get(settings.refresh_cookie_name)]
            for _ in range(rotations):
                assert (await client.post("/api/auth/refresh")).status_code == 200
                old_cookies.append(client.cookies.get(settings.refresh_cookie_name))
            if rotations:
                # Exercise the legitimate grace path before recovery, including
                # its extra live session branch, without waiting for its expiry.
                grace = await client.post(
                    "/api/auth/refresh",
                    headers={
                        "Cookie": f"{settings.refresh_cookie_name}={old_cookies[0]}"
                    },
                )
                assert grace.status_code == 200
                old_cookies.append(client.cookies.get(settings.refresh_cookie_name))
            previously_revoked = {
                token.id: token.revoked_at
                for token in (await session.scalars(select(RefreshToken))).all()
                if token.user_id == account.id and token.revoked_at is not None
            }
            await session.commit()
            identity = (
                account.id,
                account.role,
                account.external_id,
                account.scope_group_ids,
            )
            await recovery.recover_admin(session, EMAIL, TEMPORARY)
            assert (
                account.id,
                account.role,
                account.external_id,
                account.scope_group_ids,
            ) == identity
            assert account.is_active and account.must_change_password
            assert verify_password(TEMPORARY, account.password_hash)
            tokens = list(await session.scalars(select(RefreshToken)))
            own_tokens = [t for t in tokens if t.user_id == account.id]
            assert own_tokens and all(t.revoked_at for t in own_tokens)
            assert all(
                token.revoked_at == previously_revoked[token.id]
                for token in own_tokens
                if token.id in previously_revoked
            )
            assert other_token.revoked_at is None
            entries = list(
                await session.scalars(
                    select(AuditLog).where(
                        AuditLog.reason
                        == "Local operator: last-administrator credential recovery"
                    )
                )
            )
            user_entry = next(e for e in entries if e.entity_type == "users")
            assert user_entry.actor_id is None
            assert user_entry.changes["password_hash"] == {
                "from": "<redacted>",
                "to": "<redacted>",
            }
            assert OLD not in str([e.changes for e in entries])
            assert TEMPORARY not in str([e.changes for e in entries])
            for cookie in old_cookies:
                replay = await client.post(
                    "/api/auth/refresh",
                    headers={"Cookie": f"{settings.refresh_cookie_name}={cookie}"},
                )
                assert replay.status_code == 401
            assert (
                await client.post(
                    "/api/auth/login", json={"email": EMAIL, "password": OLD}
                )
            ).status_code == 401
            login = await client.post(
                "/api/auth/login", json={"email": EMAIL, "password": TEMPORARY}
            )
            assert (
                login.status_code == 200
                and login.json()["user"]["must_change_password"]
            )
            headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
            for token in (old_access, login.json()["access_token"]):
                blocked = await client.get(
                    "/api/users/me", headers={"Authorization": f"Bearer {token}"}
                )
                assert blocked.status_code == 403
                assert blocked.headers["X-Error-Code"] == "password_change_required"
            changed = await client.post(
                "/api/auth/change-password",
                headers=headers,
                json={"old_password": TEMPORARY, "new_password": "final-test-password"},
            )
            assert changed.status_code == 204
            assert (
                await client.get("/api/users/me", headers=headers)
            ).status_code == 200
            # The password-change gate has now cleared: old refresh credentials
            # must still be unusable, rather than regaining administrator access.
            for cookie in old_cookies:
                replay = await client.post(
                    "/api/auth/refresh",
                    headers={"Cookie": f"{settings.refresh_cookie_name}={cookie}"},
                )
                assert replay.status_code == 401
    finally:
        app.dependency_overrides.pop(get_session, None)


@pytest.mark.parametrize(
    "case", ["missing", "viewer", "inactive", "second-admin", "short-password"]
)
async def test_invalid_recovery_changes_neither_account_nor_tokens(
    combined_database, account, case
):
    session, _ = combined_database
    if case == "viewer":
        account.role = "viewer"
    elif case == "inactive":
        account.is_active = False
    elif case == "second-admin":
        session.add(
            User(
                email="other@example.test",
                name="Other admin",
                role="admin",
                password_hash="test-only",
            )
        )
    token = RefreshToken(
        user_id=account.id,
        token_hash="test-only",
        expires_at=datetime.now(UTC) + timedelta(days=1),
    )
    session.add(token)
    await session.commit()
    account_id, token_id, old_hash = account.id, token.id, account.password_hash
    with pytest.raises(ValueError):
        await recovery.recover_admin(
            session,
            "missing@example.test" if case == "missing" else EMAIL,
            "short" if case == "short-password" else TEMPORARY,
        )
    await session.refresh(account)
    await session.refresh(token)
    assert account.id == account_id and account.password_hash == old_hash
    assert not account.must_change_password
    assert token.id == token_id and token.revoked_at is None
    assert not (
        await session.scalars(
            select(AuditLog).where(AuditLog.reason.like("Local operator:%"))
        )
    ).all()


async def test_audit_failure_rolls_back_password_and_token_revocation(
    combined_database, account
):
    session, engine = combined_database
    token = RefreshToken(
        user_id=account.id,
        token_hash="test-only",
        expires_at=datetime.now(UTC) + timedelta(days=1),
    )
    predecessor = RefreshToken(
        user_id=account.id,
        token_hash="rotated-test-only",
        expires_at=token.expires_at,
        revoked_at=datetime.now(UTC),
        replaced_by_id=token.id,
    )
    original_revocation = predecessor.revoked_at
    session.add_all([token, predecessor])
    await session.commit()
    old_hash = account.password_hash

    def fail_audit(conn, cursor, statement, parameters, context, executemany):
        if statement.startswith("INSERT INTO audit_log"):
            raise RuntimeError("synthetic audit failure")

    event.listen(engine.sync_engine, "before_cursor_execute", fail_audit)
    try:
        with pytest.raises(RuntimeError, match="synthetic audit failure"):
            await recovery.recover_admin(session, EMAIL, TEMPORARY)
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", fail_audit)
    await session.refresh(account)
    await session.refresh(token)
    await session.refresh(predecessor)
    assert account.password_hash == old_hash and not account.must_change_password
    assert token.revoked_at is None
    assert predecessor.revoked_at == original_revocation
    assert predecessor.replaced_by_id == token.id


async def test_concurrent_account_write_prevents_recovery_without_overwrite(
    combined_database, account
):
    session, engine = combined_database
    async with AsyncSession(engine) as concurrent, concurrent.begin():
        await concurrent.execute(text("LOCK TABLE users IN ROW EXCLUSIVE MODE"))
        with pytest.raises(DBAPIError):
            await recovery.recover_admin(session, EMAIL, TEMPORARY)
    await session.refresh(account)
    assert verify_password(OLD, account.password_hash)
    await session.rollback()
    await recovery.recover_admin(session, EMAIL, TEMPORARY)
    assert verify_password(TEMPORARY, account.password_hash)


@pytest.mark.parametrize("case", ["no-tty", "wrong-email", "mismatch", "echo-warning"])
def test_cli_cancels_before_database_or_secret_output(monkeypatch, capsys, case):
    monkeypatch.setattr(recovery.sys.stdin, "isatty", lambda: case != "no-tty")
    monkeypatch.setattr(recovery.sys.stderr, "isatty", lambda: True)
    monkeypatch.setattr(
        "builtins.input", lambda prompt: "wrong" if case == "wrong-email" else EMAIL
    )
    values = iter([TEMPORARY, "different" if case == "mismatch" else TEMPORARY])

    def password(prompt):
        if case == "echo-warning":
            recovery.warnings.warn("Echo unavailable", recovery.getpass.GetPassWarning)
        return next(values)

    monkeypatch.setattr(recovery.getpass, "getpass", password)
    run = AsyncMock()
    monkeypatch.setattr(recovery, "_run", run)
    assert recovery.main(["--email", EMAIL]) == 1
    run.assert_not_called()
    captured = capsys.readouterr()
    assert TEMPORARY not in captured.out + captured.err
