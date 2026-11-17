#!/bin/bash
# Run real checks in disposable containers; never stop existing Compose services.
set -euo pipefail

SMOKE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SMOKE_DIR/../.." && pwd)"
IMAGE="${SMOKE_IMAGE:-document-intelligence-smoke:local}"
PACKAGED_APP="${SMOKE_PACKAGED_APP:-0}"
CONTAINER=""
CLIENT_PID=""

usage() {
  echo "Usage: bash scripts/smoke/ejecutar.sh components|http|all"
  echo "Default image: document-intelligence-smoke:local (alternative: SMOKE_IMAGE)."
}

if [ "$#" -ne 1 ]; then
  usage >&2
  exit 2
fi
case "$1" in
  components|http|all) MODE="$1" ;;
  componentes) MODE=components ;;
  todo) MODE=all ;;
  -h|--help) usage; exit 0 ;;
  *) usage >&2; exit 2 ;;
esac

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker is not available. See the project README." >&2
  exit 1
fi
if ! docker info >/dev/null 2>&1; then
  echo "Cannot connect to Docker. Check that the engine is running." >&2
  exit 1
fi
if ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
  echo "Local image not found: $IMAGE" >&2
  echo "From the repository root, build the image: docker build -t document-intelligence-smoke:local ." >&2
  echo "If you use another image, set its name with SMOKE_IMAGE." >&2
  exit 1
fi
if [ ! -f "$ROOT/sample_pdfs/meeting_minutes.pdf" ]; then
  echo "sample_pdfs/meeting_minutes.pdf is missing from the repository." >&2
  exit 1
fi
if [ "$PACKAGED_APP" != 0 ] && [ "$PACKAGED_APP" != 1 ]; then
  echo "SMOKE_PACKAGED_APP must be 0 or 1" >&2
  exit 2
fi

cleanup() {
  local result=$?
  local stopped=0
  trap - EXIT
  if [ -n "$CONTAINER" ]; then
    echo "Stopping only the temporary HTTP container: ${CONTAINER:0:12}"
    if docker stop "$CONTAINER" >/dev/null; then
      stopped=1
    else
      echo "Could not stop the temporary container $CONTAINER; check its status." >&2
      if [ "$result" -eq 0 ]; then
        result=1
      fi
    fi
  fi
  if [ "$stopped" -eq 1 ] && [ -n "$CLIENT_PID" ]; then
    wait "$CLIENT_PID" 2>/dev/null || true
  fi
  exit "$result"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

components() {
  echo "=== Real components: OCR → NER → bounding boxes → fuzzy matching ==="
  echo "Temporary container without network access; scripts and PDFs mounted read-only."
  local -a args=(run --rm --network none)
  if [ "$PACKAGED_APP" = 0 ]; then args+=(-v "$ROOT/app:/app/app:ro"); fi
  docker "${args[@]}" \
    -v "$ROOT/sample_pdfs:/samples:ro" \
    -v "$SMOKE_DIR:/smoke:ro" \
    -e PYTHONPATH=/app --entrypoint python "$IMAGE" -u /smoke/verificar_componentes.py
}

http() {
  echo "=== Real HTTP: Uvicorn → endpoint → OCR → NER → bounding boxes → fuzzy matching ==="
  echo "Starting a temporary API without external network access or host-published ports..."
  local -a args=(run --rm -d --network none)
  if [ "$PACKAGED_APP" = 0 ]; then args+=(-v "$ROOT/app:/app/app:ro"); fi
  CONTAINER="$(docker "${args[@]}" \
    -v "$ROOT/sample_pdfs:/samples:ro" \
    -v "$SMOKE_DIR:/smoke:ro" \
    -e PYTHONPATH=/app --entrypoint uvicorn "$IMAGE" \
    app.main:app --host 127.0.0.1 --port 8000)"
  echo "Temporary container: ${CONTAINER:0:12}"
  # Waiting on a background client lets Bash handle INT/TERM before it finishes.
  docker exec "$CONTAINER" python -u /smoke/verificar_http.py &
  CLIENT_PID=$!
  if ! wait "$CLIENT_PID"; then
    CLIENT_PID=""
    echo "HTTP verification failed. Last messages from the temporary server:" >&2
    docker logs --tail 30 "$CONTAINER" >&2 || true
    return 1
  fi
  CLIENT_PID=""
}

echo "Local image: $IMAGE"
case "$MODE" in
  components) components ;;
  http) http ;;
  all) components; http ;;
esac
