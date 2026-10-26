#!/usr/bin/env bash
# Own only this run's Compose project. Docker is the only host dependency.
set -euo pipefail
cd "$(dirname "$0")"
case "${1:-full}" in
  full|smoke) export LOAD_PROFILE="${1:-full}" ;;
  *) echo 'Usage: bash tests/load/run.sh [full|smoke]' >&2; exit 2 ;;
esac
CAPADO_LOAD_RUN_ID="capado-load-$(date +%s)-$$"
export CAPADO_LOAD_RUN_ID
compose=(docker compose --env-file /dev/null -p "$CAPADO_LOAD_RUN_ID" -f compose.yml)
mkdir -p results
# Avoid mixing reports or sharing a bind mount between concurrent runs.
if ! mkdir results/.running 2>/dev/null; then
  echo 'Another load test is running (results/.running). Stop it first.' >&2
  exit 2
fi
cleanup() {
  result=$?
  trap - EXIT INT TERM
  "${compose[@]}" logs --no-color > results/containers.log 2>&1 || true
  "${compose[@]}" down --volumes --remove-orphans || result=1
  docker image rm "$CAPADO_LOAD_RUN_ID-backend" >/dev/null 2>&1 || true
  rmdir results/.running
  echo "Load-test reports: $(pwd)/results"
  exit "$result"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
rm -f results/summary.json
{
  git rev-parse HEAD
  git status --short
  docker info --format 'Docker: {{.OSType}}/{{.Architecture}} CPUs={{.NCPU}} Memory={{.MemTotal}}'
  printf 'Profile=%s p95=%sms p99=%sms\n' "$LOAD_PROFILE" "${LOAD_P95_MS:-1000}" "${LOAD_P99_MS:-2000}"
} > results/environment.txt
"${compose[@]}" build backend
"${compose[@]}" up -d --wait --wait-timeout 180 db
"${compose[@]}" run --rm --no-deps -T seed
"${compose[@]}" up -d --wait --wait-timeout 180 backend
"${compose[@]}" run --rm --no-deps -T --user "$(id -u):$(id -g)" load 2>&1 | tee results/k6.log
