# ---------------------------------------------------------------------------
# Frontend Dockerfile — multi-stage (dev + production)
# ---------------------------------------------------------------------------

# --- Dependencies stage: install node_modules ------------------------------
FROM node:26-alpine AS deps

WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

# --- Development (default target for docker compose) -----------------------
FROM node:26-alpine AS dev

WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .

EXPOSE 3000
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "3000"]

# --- Build stage: produce static assets -----------------------------------
FROM node:26-alpine AS build

ARG VITE_APP_VERSION=dev
ENV VITE_APP_VERSION=$VITE_APP_VERSION

WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build

# --- Production: serve static files with nginx ----------------------------
FROM nginx:alpine AS production

# PATCH THE OS PACKAGES THE BASE IMAGE BRINGS.
#
# The first Trivy scan of this image reported 7 fixable HIGH advisories, all seven in `util-linux`
# (CVE-2026-53612/53613/53614/76642/78408/78409/78410): present at 2.42.1-r0, fixed upstream in
# 2.42.3. None of it comes from this application — `util-linux` arrives with `nginx:alpine` as a
# transitive dependency of the base.
#
# Pinning the base tag would not help: `nginx:alpine` is already floating, so the vulnerable version
# is simply whatever the tag resolved to at build time, and we cannot make Docker Hub rebuild it.
# Upgrading at build time is what we can actually control.
#
# The cost, stated: image contents now depend on build date, so two builds of the same commit can
# differ. That is the accepted trade for OS patching, and this image was never byte-reproducible
# anyway — the base tag floats.
RUN apk upgrade --no-cache

COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh

EXPOSE 3000
ENTRYPOINT ["/docker-entrypoint.sh"]
