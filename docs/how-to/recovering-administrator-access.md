# Recovering administrator access

Use this only when the **sole active administrator** has lost their local password.
If another administrator can sign in, use normal user management. If the administrator's
verified OIDC identity still works, signing in through that provider keeps the existing role.

The recovery command requires trusted access to the backend container and its database
credentials. There is no public recovery endpoint, default password, account creation,
role promotion or account reactivation. Anyone who controls that container/database already
controls the installation; protect that access independently of Capado accounts.

## Procedure

1. Keep a [verified backup](upgrading.md#1-back-up-without-exception). Confirm the deployment
   and the exact email of the existing active administrator.
2. Stop **all API replicas** and external account/token writers. For the standard Compose
   installation, keep PostgreSQL running:

   ```bash
   docker compose -f docker-compose.prod.yml stop backend
   docker compose -f docker-compose.prod.yml run --rm --no-deps -it \
     --entrypoint python backend -m app.scripts.recover_admin \
     --email admin@example.test
   ```

   Replace the fictional email with the existing administrator's exact login email. Use
   the deployment's normal Compose project and environment. The command must come from an
   image containing this feature; do not run newer code against an older database schema.
   For a development image, use `--entrypoint uv backend run python -m
   app.scripts.recover_admin` with the development Compose file instead.

3. Confirm the email when prompted. Enter the temporary password twice; input is hidden.
   Use a fresh unique password of at least eight characters. Do not pass it through command
   arguments, environment variables, pipes, screenshots or terminal recordings. The command
   refuses noninteractive input or a terminal that cannot hide the password.
4. A successful exit (`0`) means the password, forced-password-change flag, refresh-token
   revocations and redacted audit events committed together. Account identity, OIDC link,
   role, scopes and resource link are preserved. No other user's tokens are changed.
5. Start the API and sign in normally, then replace the temporary password when requested:

   ```bash
   docker compose -f docker-compose.prod.yml start backend
   ```

   Verify access and review the user's audit history. The recovery event has no application
   actor and the reason `Local operator: last-administrator credential recovery`. Password
   hashes and plaintext passwords are not included in that audit record. Retain the operator
   intervention in your normal operational log without recording credentials.

## Failure and concurrency

An unknown email, inactive/non-admin account, multiple active administrators, mismatched
confirmation or invalid password does not reset an account. Busy database tables fail
immediately rather than waiting behind another recovery or account writer. Retry only after
checking that all writers are stopped and confirming the intended account.

The database transaction locks the user and refresh-token tables, including against concurrent
inserts, and has a 15-second statement timeout. A failed write/audit rolls back the changes.
The process exits nonzero on cancellation or a database error and does not print database
exception details. If the connection fails during commit, inspect the audit and attempt normal
login before retrying; a lost acknowledgement does not prove that nothing committed.

This command does not run migrations, start the scheduler, bypass normal login, change OIDC
configuration or enable initial setup again. Fix an incompatible schema through the documented
upgrade procedure, not by deleting users or altering roles directly.

## Session limits

The command revokes all stored refresh tokens for the recovered account, including
recently rotated predecessors and concurrent-refresh branches. Existing short-lived
access JWTs retain their normal expiry: they are blocked by the password-change gate until
the temporary password is changed, but are not individually revoked. This procedure is for
forgotten credentials. For suspected account/token compromise, also rotate the deployment's
`JWT_SECRET_KEY` consistently across all API replicas before restarting; that invalidates
**all users'** existing access tokens. Other accounts' stored refresh sessions remain
valid; the recovered account's revoked refresh tokens require a new sign-in.

Password input uses Python's [getpass](https://docs.python.org/3/library/getpass.html), with
its insecure echo fallback disabled. Session invalidation follows the recovery considerations
in the [OWASP guidance](https://cheatsheetseries.owasp.org/cheatsheets/Forgot_Password_Cheat_Sheet.html).
