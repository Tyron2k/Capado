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

# --- Production: serve static files with nginx (non-root) -----------------
#
# nginxinc/nginx-unprivileged is the stock nginx image rebuilt to run as an unprivileged user
# (uid 101) with its pid, cache and temp paths under locations a non-root process can write.
# Using it instead of hardening plain nginx:alpine by hand avoids getting the writable-path set
# subtly wrong, and it is the upstream-supported way to run nginx rootless.
FROM nginxinc/nginx-unprivileged:alpine AS production

# Back to root only for the build-time steps (package upgrade, copying files); the base image
# switches back to uid 101 at the end, and nothing below runs at runtime as root.
USER root

# PATCH THE OS PACKAGES THE BASE IMAGE BRINGS.
#
# The first Trivy scan of this image reported 7 fixable HIGH advisories, all seven in `util-linux`
# (CVE-2026-53612/53613/53614/76642/78408/78409/78410): present at 2.42.1-r0, fixed upstream in
# 2.42.3. None of it comes from this application — `util-linux` arrives with the nginx base as a
# transitive dependency.
#
# Pinning the base tag would not help: the tag is already floating, so the vulnerable version is
# simply whatever it resolved to at build time, and we cannot make Docker Hub rebuild it.
# Upgrading at build time is what we can actually control.
#
# The cost, stated: image contents now depend on build date, so two builds of the same commit can
# differ. That is the accepted trade for OS patching, and this image was never byte-reproducible
# anyway — the base tag floats.
RUN apk upgrade --no-cache

COPY --from=build /app/dist /usr/share/nginx/html
# Use the nginx image's own envsubst-on-templates entrypoint to render the complete nginx config
# into /tmp at startup. That is the only writable location under the production read-only root
# filesystem, and Nginx is started explicitly with the rendered config.
COPY nginx.conf /etc/nginx/templates/nginx.conf.template
ENV NGINX_ENVSUBST_OUTPUT_DIR=/tmp
RUN rm -f /etc/nginx/conf.d/default.conf \
    && chown -R 101:101 /usr/share/nginx/html

# Back to the unprivileged user the base image ships. Everything at runtime runs as uid 101.
USER 101

EXPOSE 3000
CMD ["nginx", "-c", "/tmp/nginx.conf", "-g", "daemon off;"]
