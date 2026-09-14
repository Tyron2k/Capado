# ---------------------------------------------------------------------------
# Backend Dockerfile — multi-stage (dev + production)
# ---------------------------------------------------------------------------
#
# THE BASE IMAGE IS UPGRADED AND DELIBERATELY NOT PINNED, and the second half is the
# part worth explaining, because pinning by digest is the reflex and it was tried here.
#
# Why the upgrade exists, measured rather than assumed: the newest `python:3.12-slim` in
# September 2026 had been built two weeks earlier and shipped gzip 1.13-1, libpcre2
# 10.46-1~deb13u1, libsqlite3 3.46.1-7+deb13u1 and perl-base 5.40.1-6. Debian had
# already published +deb13u1/u2 point updates for all four, carrying three CRITICAL and
# nine HIGH fixes, and the Trivy gate in .github/workflows/build-images.yml failed the
# build on exactly those. `apt-get upgrade` closes the window between a Debian point
# release and the upstream image being rebuilt against it — days to weeks, and not ours
# to control. frontend/Dockerfile does the same with `apk upgrade`, which is precisely
# why the frontend image passed the scan the backend failed.
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
# Dependabot will occasionally propose a MAJOR bump (3.12 -> 3.14). That is a judgement
# call and has been declined before; declining one is not a maintenance failure.
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

# --- Production: minimal runtime image ------------------------------------
FROM python:3.14-slim AS production

WORKDIR /app

RUN apt-get update && apt-get upgrade -y --no-install-recommends \
    && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
COPY --from=builder /app/.venv /app/.venv
COPY . .

ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONPATH="/app"

EXPOSE 3001
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "3001", "--workers", "4"]
