"""Recover the sole active administrator through trusted local operator access.

Run interactively with the API stopped; never pass passwords as command arguments.
"""

import argparse
import asyncio
import getpass
import sys
import warnings
from datetime import UTC, datetime

from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User, UserRole
from app.services.audit import register_audit_listener, set_actor, set_reason
from app.services.auth_service import hash_password, revoke_user_refresh_tokens


async def recover_admin(
    session: AsyncSession, email: str, temporary_password: str
) -> None:
    """Reset an existing sole active admin and revoke refresh tokens atomically.

    Container/database control is the authority, not an application identity.
    PostgreSQL table locks serialize recovery and block concurrent account/token
    writes, including inserts that a row lock would not prevent.
    """
    if len(temporary_password) < 8:
        raise ValueError("The temporary password must contain at least 8 characters.")
    if session.get_bind().dialect.name != "postgresql":
        raise ValueError("Administrator recovery requires PostgreSQL.")
    password_hash = await asyncio.to_thread(hash_password, temporary_password)
    register_audit_listener()
    async with session.begin():
        await session.execute(text("SET LOCAL statement_timeout = '15s'"))
        await session.execute(
            text("LOCK TABLE users, refresh_tokens IN EXCLUSIVE MODE NOWAIT")
        )
        admins = list(
            await session.scalars(
                select(User).where(User.role == UserRole.admin, User.is_active)
            )
        )
        if len(admins) != 1 or admins[0].email != email:
            raise ValueError(
                "Recovery requires the exact email of the sole active administrator. "
                "Use normal account management when another administrator is available."
            )
        user = admins[0]
        now = datetime.now(UTC)
        set_actor(session, None)
        set_reason(session, "Local operator: last-administrator credential recovery")
        await revoke_user_refresh_tokens(session, user.id)
        user.password_hash = password_hash
        user.must_change_password = True
        user.updated_at = now


async def _run(email: str, password: str) -> None:
    from app.database import async_session_factory, engine

    try:
        async with async_session_factory() as session:
            await recover_admin(session, email, password)
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    """Require a terminal, explicit account confirmation and hidden password input."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--email", required=True, help="Existing sole active admin email"
    )
    args = parser.parse_args(argv)
    if not sys.stdin.isatty() or not sys.stderr.isatty():
        print(
            "Recovery requires an interactive terminal (docker compose run -it).",
            file=sys.stderr,
        )
        return 1
    try:
        confirmation = input("Stop the API first. Confirm the administrator email: ")
        if confirmation != args.email:
            raise ValueError("Email confirmation did not match; recovery cancelled.")
        with warnings.catch_warnings():
            warnings.simplefilter("error", getpass.GetPassWarning)
            password = getpass.getpass("Temporary password (at least 8 characters): ")
            repeated = getpass.getpass("Repeat temporary password: ")
        if password != repeated:
            raise ValueError("Passwords did not match; recovery cancelled.")
        asyncio.run(_run(args.email, password))
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except (EOFError, KeyboardInterrupt, getpass.GetPassWarning):
        print("Recovery cancelled; secure terminal input is required.", file=sys.stderr)
        return 1
    except SQLAlchemyError:
        # Database exceptions can contain connection details or bound values.
        print(
            "Recovery failed: database unavailable, busy or incompatible. Inspect the audit before retrying.",
            file=sys.stderr,
        )
        return 1
    print(
        "Administrator recovered. Refresh tokens revoked; change the temporary password after login."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
