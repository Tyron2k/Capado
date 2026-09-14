# ---------------------------------------------------------------------------
# Backend Dockerfile — multi-stage (dev + production)
# ---------------------------------------------------------------------------
#
# THE BASE IMAGE IS UPGRADED AND DELIBERATELY NOT PINNED, and the second half is the
# part worth explaining, because pinning by digest is the reflex and it was tried here.
#
# Why the upgrade exists, measured rather than assumed: a freshly published `python:3.14-slim`
# still lags the Debian point releases by days to weeks — the base is rebuilt against a new
# Debian security update only after Debian ships it. `apt-get upgrade` closes that window, and
# has caught real CRITICAL/HIGH fixes here before (gzip, libpcre2, libsqlite3, perl-base on the
# 3.12 base). frontend/Dockerfile does the same with `apk upgrade`, which is precisely why the
# frontend image passed the scan the backend once failed.
#
# WHY NO DIGEST PIN. One was added and then removed, once the reasoning was followed
# through rather than stopped at "pinning is good practice":
#
#   Security does not come from the pin, it comes from apt. A pinned digest WITHOUT an
#   upgrade is strictly worse than no pin: it freezes a vulnerable package set, which is
#   what the failing build was. With the upgrade in place, the pin adds nothing to it.
#
#   The one thing a pin does buy — reproducibility — it only half buys. The upgraded
#   package set is whatever Debian currently serves, so a rebuild is not byte-identical
#   either way. A pin bounds the base, not the image.
#
#   It costs size, and the cost GROWS. The older the pinned digest, the more `upgrade`
#   has to fetch: measured at +56MB against a two-week-old base. On the floating tag the
#   layer stays near zero, because a freshly rebuilt base has nothing left to upgrade.
#   Pinning therefore preserves exactly the state that inflates the image.
#
#   Dependabot watches this file (.github/dependabot.yml, ecosystem docker, /backend,
#   weekly) and reads plain `FROM` instructions — it has raised a base-image PR here
#   before. A pin hidden behind `ARG` + `FROM ${VAR}` risks being invisible to it, which
#   is the worst of the options: a pin nobody refreshes accumulates the very upgrade it
#   was meant to make unnecessary.
#
# WHAT THIS TRADES AWAY: two builds a month apart start from different operating
# systems. Accepted knowingly — the alternative is carrying a base we do not update, and
# a security update we do not take is a security update we do not have.
#
# Dependabot will occasionally propose the next MAJOR bump (e.g. 3.14 -> 3.15). That is a
# judgement call; taking or declining one is deliberate, not automatic.
#
# --- Builder stage: compile native extensions (asyncpg, etc.) --------------
#
# DELIBERATELY NOT UPGRADED. Nothing from this stage's operating system reaches the
# final image: only /app/.venv is copied out, and the compilers that made it stay
# behind. Upgrading here would add a minute to every build and change nothing that
# ships.
FROM python:3.14-slim AS builder

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# --- Development (default target for docker compose) -----------------------
FROM python:3.14-slim AS dev

WORKDIR /app

# Upgraded in the same layer as the install, so the package index is fetched once and
# discarded once. A separate RUN would leave the pre-upgrade layer in the image.
RUN apt-get update && apt-get upgrade -y --no-install-recommends \
    && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

COPY pyproject.toml uv.lock ./
COPY . .

ENV UV_LINK_MODE=copy

EXPOSE 3001
CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "3001", "--reload"]

# --- Production: minimal, hardened runtime image --------------------------
FROM python:3.14-slim AS production

WORKDIR /app

# libpq5 is the one runtime OS dependency (asyncpg links only glibc, but keeping libpq5
# covers any libpq-backed tooling). curl is intentionally NOT installed: the container's
# health check runs through Python (see HEALTHCHECK below), so no shell HTTP client needs
# to exist in the image — one less binary for anything that gets a foothold to use.
RUN apt-get update && apt-get upgrade -y --no-install-recommends \
    && apt-get install -y --no-install-recommends \
    libpq5 \
    && rm -rf /var/lib/apt/lists/* \
    # Remove the base image's system pip. The app runs entirely from /app/.venv and never
    # invokes pip at runtime, but python:3.14-slim ships pip, and pip vendors a CycloneDX SBOM
    # (pip/_vendor/bom.cdx.json) declaring setuptools 70.3.0 — which Trivy reports as
    # CVE-2025-47273 even though nothing installable or importable is present. Uninstalling pip
    # deletes that vendored metadata, so the finding goes at the root rather than being patched.
    # --break-system-packages: the base marks the system python externally-managed (PEP 668).
    && python3 -m pip uninstall -y pip --break-system-packages \
    # A non-root user to run as. --system: no password, no home clutter; a fixed uid keeps the
    # numeric identity stable across rebuilds, which matters when the read-only root filesystem
    # and any mounted volumes need predictable ownership.
    && groupadd --system --gid 10001 capado \
    && useradd --system --uid 10001 --gid capado --no-create-home capado

COPY --from=builder /app/.venv /app/.venv
COPY . .

# Owned by the runtime user so an EXEC into the container cannot write app files as root, and
# so the image works under a read-only root filesystem (nothing here is written at runtime).
RUN chown -R capado:capado /app

ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONPATH="/app"

# Drop root. Everything below and at runtime runs as the unprivileged user; combined with the
# compose-side read_only + no-new-privileges, a compromised process cannot escalate or persist.
USER capado

EXPOSE 3001

# Python health check instead of curl: the interpreter is already here, so the image needs no
# HTTP client binary. Hits the app's own /api/health; a non-200 or a connection error exits
# non-zero and marks the container unhealthy.
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:3001/api/health', timeout=4).status==200 else 1)"]

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "3001", "--workers", "4"]
