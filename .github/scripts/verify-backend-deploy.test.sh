#!/usr/bin/env bash
# Tests for verify-backend-deploy.sh, driven by a stubbed az CLI and curl.
#
# The gate has to do two things, and an earlier version got the second wrong:
#   1. fail when a revision does not take over traffic (silent bad deploys), and
#   2. pass when it does (a gate that cries wolf gets switched off).
#
# Run: bash .github/scripts/verify-backend-deploy.test.sh
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
SCRIPT="$HERE/verify-backend-deploy.sh"
STUB="$(mktemp -d)"
trap 'rm -rf "$STUB"' EXIT

cat >"$STUB/curl" <<'EOF'
#!/usr/bin/env bash
echo -n "${FAKE_HEALTH_CODE-200}"
EOF

# Note the ${VAR-default} form (no colon): an empty value must stay empty so the
# unreadable-field case is reproducible.
cat >"$STUB/az" <<'EOF'
#!/usr/bin/env bash
args="$*"
case "$args" in
  *"extension add"*) exit 0 ;;
  *"revision list"*)
    [ "${FAKE_REVISION_EXISTS-1}" = "1" ] && echo "portfolio-backend--0000155"
    exit 0 ;;
  *"properties.healthState"*)   echo "${FAKE_HEALTH-Healthy}" ; exit 0 ;;
  *"properties.runningState"*)  echo "${FAKE_RUNNING-RunningAtMaxScale}" ; exit 0 ;;
  *"properties.trafficWeight"*) echo "${FAKE_TRAFFIC-100}" ; exit 0 ;;
  *"containerapp show"*) echo "backend.example.net" ; exit 0 ;;
  *"logs show"*) echo "<container logs>" ; exit 0 ;;
esac
exit 0
EOF
chmod +x "$STUB/curl" "$STUB/az"
export PATH="$STUB:$PATH"
export APP_NAME=portfolio-backend
export RESOURCE_GROUP=rg-portfolio-agent
export EXPECTED_IMAGE=registry/portfolio-backend:abc123

pass=0
fail=0
check() {
  local name="$1" expected="$2" out rc
  out=$(bash "$SCRIPT" 2>&1)
  rc=$?
  if [ "$rc" -eq "$expected" ]; then
    echo "PASS  $name"
    pass=$((pass + 1))
  else
    echo "FAIL  $name (exit $rc, expected $expected)"
    printf '%s\n' "$out" | sed 's/^/      /'
    fail=$((fail + 1))
  fi
}

echo "--- passes only when the revision truly serves ---"
TIMEOUT_SECONDS=30 \
  check "healthy, 100% traffic, /health 200" 0

echo
echo "--- fails on every silently-green deploy ---"
TIMEOUT_SECONDS=5 FAKE_HEALTH=None FAKE_RUNNING=Activating FAKE_TRAFFIC=0 \
  check "stuck activating, old revision still serving" 1
TIMEOUT_SECONDS=5 FAKE_HEALTH=None FAKE_RUNNING=Failed FAKE_TRAFFIC=0 \
  check "revision failed to start" 1
TIMEOUT_SECONDS=5 FAKE_REVISION_EXISTS=0 \
  check "no revision built from this commit" 1
TIMEOUT_SECONDS=30 FAKE_HEALTH_CODE=503 \
  check "platform healthy but app returns 503" 1
TIMEOUT_SECONDS=5 FAKE_HEALTH=Healthy FAKE_TRAFFIC=0 \
  check "healthy but not taking traffic" 1

echo
echo "--- does not cry wolf (regression: unparsed fields failed a good deploy) ---"
TIMEOUT_SECONDS=5 FAKE_HEALTH=Healthy FAKE_RUNNING="" FAKE_TRAFFIC="" \
  check "unreadable state fails rather than passing blindly" 1
TIMEOUT_SECONDS=30 FAKE_HEALTH=Healthy FAKE_RUNNING=RunningAtMaxScale FAKE_TRAFFIC=100 \
  check "a genuinely healthy revision is not failed" 0

echo
echo "passed=$pass failed=$fail"
[ "$fail" -eq 0 ]
