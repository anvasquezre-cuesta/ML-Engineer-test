#!/bin/bash
# Real HTTP/OCR/NER comparison with disposable, network-isolated API containers.
set -euo pipefail
CHECKS="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$CHECKS/../.." && pwd)"
IMAGE="${SMOKE_IMAGE:-document-intelligence-smoke:local}"
AUTO=0
if [ "$#" -eq 1 ] && [ "$1" = "--automatico" ]; then
  AUTO=1
elif [ "$#" -eq 1 ] && { [ "$1" = "--help" ] || [ "$1" = "-h" ]; }; then
  echo "Usage: bash scripts/smoke/recuperacion_nombres.sh [--automatico]"
  exit 0
elif [ "$#" -ne 0 ]; then
  echo "Usage: bash scripts/smoke/recuperacion_nombres.sh [--automatico]" >&2
  exit 2
fi
if [ "$AUTO" = 0 ] && [ ! -t 0 ]; then
  echo "Interactive terminal required; use --automatico to run without a pause." >&2
  exit 2
fi

CONTAINER=""
OUTPUT=""
cleanup() {
  local result=$? level
  trap - EXIT
  if [ -n "$CONTAINER" ]; then docker stop "$CONTAINER" >/dev/null || result=1; fi
  if [ -n "$OUTPUT" ]; then
    for level in 0 1 2 3; do
      rm -f -- "$OUTPUT/level-$level.json" "$OUTPUT/level-$level.pdf" || result=1
    done
    rmdir -- "$OUTPUT" 2>/dev/null || { echo "Inspect temporary directory: $OUTPUT" >&2; result=1; }
  fi
  exit "$result"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

docker image inspect "$IMAGE" >/dev/null
if [ ! -f "$ROOT/sample_pdfs/meeting_minutes.pdf" ]; then
  echo "Missing sample_pdfs/meeting_minutes.pdf" >&2
  exit 1
fi
umask 077
OUTPUT="$(mktemp -d "${TMPDIR:-/tmp}/name-recovery-smoke.XXXXXX")"

for level in 0 1 2 3; do
  echo "Testing recovery level $level with real Uvicorn, OCR and NER..."
  CONTAINER="$(docker run --rm -d --network none \
    -v "$ROOT/sample_pdfs:/samples:ro" -v "$CHECKS:/checks:ro" \
    -e PYTHONPATH=/app -e NER_NAME_RECOVERY_PASSES="$level" -e HF_HUB_OFFLINE=1 \
    --entrypoint uvicorn "$IMAGE" app.main:app --host 127.0.0.1 --port 8000)"
  if ! docker exec "$CONTAINER" python /checks/verificar_recuperacion_nombres.py collect > "$OUTPUT/level-$level.json"; then
    docker logs --tail 30 "$CONTAINER" >&2 || true
    exit 1
  fi
  if [ "$level" != 0 ]; then
    { cat "$OUTPUT/level-0.json"; cat "$OUTPUT/level-$level.json"; } | \
      docker exec -i "$CONTAINER" python /checks/verificar_recuperacion_nombres.py compare "$level"
  fi
  docker exec -i "$CONTAINER" python /checks/verificar_recuperacion_nombres.py render \
    < "$OUTPUT/level-$level.json" > "$OUTPUT/level-$level.pdf"
  docker stop "$CONTAINER" >/dev/null
  CONTAINER=""
done

echo "Temporary PDFs with red boxes, ready for side-by-side visual review:"
for level in 0 1 2 3; do echo "  Level $level: $OUTPUT/level-$level.pdf"; done
echo "The comparisons use separate real OCR/NER requests; visual approval remains a human decision."
if [ "$AUTO" = 0 ]; then
  read -r -p "Press Enter to delete the temporary PDFs and finish (Ctrl-C also cleans up): " _
fi
echo "Real HTTP comparison finished; removing only its temporary files and containers."
