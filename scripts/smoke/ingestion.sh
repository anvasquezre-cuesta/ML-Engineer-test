#!/bin/bash
# Real, isolated ingestion and persistence checks; no existing Compose resources.
set -euo pipefail
CHECKS="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$CHECKS/../.." && pwd)"
IMAGE="${SMOKE_IMAGE:-document-intelligence-smoke:local}"
QDRANT_IMAGE="${SMOKE_QDRANT_IMAGE:-qdrant/qdrant:v1.13.6}"
PACKAGED_APP="${SMOKE_PACKAGED_APP:-0}"
ASK_FAKE="${SMOKE_ASK_FAKE:-0}"
PREFIX="ingest-smoke-$(date +%Y%m%d%H%M%S)-$$-$RANDOM"
NETWORK=""
VECTOR_VOLUME=""
LEDGER_VOLUME=""
API=""
QDRANT=""

cleanup() {
  local result=$?
  trap - EXIT
  for id in "$API" "$QDRANT"; do
    if [ -n "$id" ]; then docker stop "$id" >/dev/null || result=1; fi
  done
  for volume in "$LEDGER_VOLUME" "$VECTOR_VOLUME"; do
    if [ -n "$volume" ]; then
      if [ "$(docker volume inspect --format '{{index .Labels "io.document-intelligence.smoke.owner"}}' "$volume" 2>/dev/null)" = "$PREFIX" ]; then
        docker volume rm "$volume" >/dev/null || result=1
      else
        echo "Cannot confirm test ownership; refusing to remove volume: $volume" >&2
        result=1
      fi
    fi
  done
  if [ -n "$NETWORK" ]; then docker network rm "$NETWORK" >/dev/null || result=1; fi
  exit "$result"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

docker image inspect "$IMAGE" >/dev/null
docker image inspect "$QDRANT_IMAGE" >/dev/null
if [ "$PACKAGED_APP" != 0 ] && [ "$PACKAGED_APP" != 1 ]; then
  echo "SMOKE_PACKAGED_APP must be 0 or 1" >&2
  exit 2
fi
if [ "$ASK_FAKE" != 0 ] && [ "$ASK_FAKE" != 1 ]; then
  echo "SMOKE_ASK_FAKE must be 0 or 1" >&2
  exit 2
fi
# Fail rather than adopt any pre-existing resource, even on a name collision.
for suffix in vectors ledger; do
  if docker volume inspect "$PREFIX-$suffix" >/dev/null 2>&1; then
    echo "Resource already exists; refusing to reuse it: $PREFIX-$suffix" >&2
    exit 1
  fi
done
NETWORK="$(docker network create --internal "$PREFIX")"
create_owned_volume() {
  local volume
  volume="$(docker volume create --label "io.document-intelligence.smoke.owner=$PREFIX" "$1")"
  if [ "$(docker volume inspect --format '{{index .Labels "io.document-intelligence.smoke.owner"}}' "$volume")" != "$PREFIX" ]; then
    echo "Refusing to use or remove a volume not created by this test: $volume" >&2
    return 1
  fi
  printf '%s\n' "$volume"
}
VECTOR_VOLUME="$(create_owned_volume "$PREFIX-vectors")"
LEDGER_VOLUME="$(create_owned_volume "$PREFIX-ledger")"

start_qdrant() {
  QDRANT="$(docker run --rm -d --network "$NETWORK" --network-alias qdrant \
    -v "$VECTOR_VOLUME:/qdrant/storage" "$QDRANT_IMAGE")"
}
start_api() {
  local -a args=(run --rm -d --network "$NETWORK")
  local app_module="app.main:app"
  if [ "$ASK_FAKE" = 1 ]; then app_module="serve_ask_fake:app"; fi
  if [ "$PACKAGED_APP" = 0 ]; then args+=(-v "$ROOT/app:/app/app:ro"); fi
  API="$(docker "${args[@]}" -v "$ROOT/sample_pdfs:/samples:ro" \
    -v "$CHECKS:/checks:ro" -v "$LEDGER_VOLUME:/app/data/ingestion" \
    -e PYTHONPATH=/app:/checks -e QDRANT_URL=http://qdrant:6333 -e HF_HUB_OFFLINE=1 -e SMOKE_ASK_FAKE="$ASK_FAKE" \
    --entrypoint uvicorn "$IMAGE" "$app_module" --host 127.0.0.1 --port 8000)"
}
check_stage() {
  if ! docker exec "$API" python -u /checks/verificar_ingestion.py "$1"; then
    docker logs --tail 30 "$API" >&2 || true
    return 1
  fi
}

echo "Isolated ingestion check: internal network, dedicated temporary volumes, no host ports."
start_qdrant
start_api
check_stage seed
docker stop "$API" >/dev/null
API=""
docker stop "$QDRANT" >/dev/null
QDRANT=""
echo "Recreating only the test API and Qdrant with the same temporary volumes..."
start_qdrant
start_api
check_stage verify
echo "Real ingestion, scoped cleanup and persistence verified; removing only test resources."
