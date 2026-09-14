#!/bin/sh
# Replace the API backend URL placeholder in the nginx config at container startup.
# Default: http://capado_backend:3001 (works when frontend + backend share a Docker network)
API_BACKEND_URL="${API_BACKEND_URL:-http://capado_backend:3001}"

sed -i "s|__API_BACKEND_URL__|${API_BACKEND_URL}|g" /etc/nginx/conf.d/default.conf

exec nginx -g "daemon off;"
