#!/usr/bin/env bash
# Fail a deploy unless the newly built revision is actually serving traffic.
#
# Azure Container Apps keeps serving the previous revision when a new one cannot
# start, and azure/container-apps-deploy-action reports success as soon as the
# revision is *created* rather than when it is healthy. A stale alembic_version
# stamp once crashed every startup for three weeks while each workflow run
# stayed green and production quietly ran an old image.
#
# This lives in a file rather than inline in the workflow so it can be exercised
# by verify-backend-deploy.test.sh — an earlier inline version shipped a parsing
# bug that failed a perfectly healthy deploy, which no test could have caught.
#
# Required environment:
#   APP_NAME         Container App name
#   RESOURCE_GROUP   its resource group
#   EXPECTED_IMAGE   the image tag built from this commit
#   TIMEOUT_SECONDS  how long to wait for the revision to take traffic
set -euo pipefail

: "${APP_NAME:?APP_NAME is required}"
: "${RESOURCE_GROUP:?RESOURCE_GROUP is required}"
: "${EXPECTED_IMAGE:?EXPECTED_IMAGE is required}"
TIMEOUT_SECONDS="${TIMEOUT_SECONDS:-600}"

az extension add --name containerapp --upgrade --only-show-errors >/dev/null 2>&1 || true

dump_logs() {
  az containerapp logs show --name "$APP_NAME" --resource-group "$RESOURCE_GROUP" \
    --revision "$1" --tail 200 --type console || true
}

deadline=$(( SECONDS + TIMEOUT_SECONDS ))
revision=""

# Find the revision created from this commit's image.
while [ -z "$revision" ]; do
  revision=$(az containerapp revision list \
    --name "$APP_NAME" --resource-group "$RESOURCE_GROUP" \
    --query "[?properties.template.containers[0].image=='$EXPECTED_IMAGE'].name | [-1]" \
    --output tsv 2>/dev/null || true)
  [ -n "$revision" ] && break
  if [ "$SECONDS" -ge "$deadline" ]; then
    echo "::error::No revision was created for $EXPECTED_IMAGE"
    exit 1
  fi
  sleep 10
done
echo "Waiting for revision $revision"

# Each field is queried on its own. A combined array query returned an output
# shape the field splitting could not parse on the runner, leaving running and
# traffic empty and timing the gate out against a healthy revision.
revision_state() {
  az containerapp revision show \
    --name "$APP_NAME" --resource-group "$RESOURCE_GROUP" --revision "$revision" \
    --query "$1" --output tsv 2>/dev/null || true
}

while :; do
  health=$(revision_state "properties.healthState")
  running=$(revision_state "properties.runningState")
  traffic=$(revision_state "properties.trafficWeight")
  echo "health='${health}' running='${running}' traffic='${traffic}'"

  if [ "$health" = "Healthy" ] && [ "$traffic" = "100" ]; then
    break
  fi
  # Terminal failure states — no point waiting out the full timeout.
  case "$running" in
    Failed|Degraded)
      echo "::error::Revision $revision entered state '$running'"
      dump_logs "$revision"
      exit 1
      ;;
  esac
  if [ "$SECONDS" -ge "$deadline" ]; then
    echo "::error::Revision $revision did not become healthy and take traffic within ${TIMEOUT_SECONDS}s (health='${health}' running='${running}' traffic='${traffic}')"
    dump_logs "$revision"
    exit 1
  fi
  sleep 10
done

# Confirm the app itself answers, not just that the platform is happy.
fqdn=$(az containerapp show --name "$APP_NAME" --resource-group "$RESOURCE_GROUP" \
  --query "properties.configuration.ingress.fqdn" --output tsv)
for attempt in $(seq 1 10); do
  code=$(curl -sS -o /dev/null -w '%{http_code}' --max-time 20 "https://$fqdn/health" || echo 000)
  echo "attempt $attempt: GET /health -> $code"
  [ "$code" = "200" ] && break
  if [ "$attempt" -eq 10 ]; then
    echo "::error::Backend health check never returned 200 (last: $code)"
    dump_logs "$revision"
    exit 1
  fi
  sleep 10
done

echo "Revision $revision is healthy, holds 100% of traffic and answers /health."
