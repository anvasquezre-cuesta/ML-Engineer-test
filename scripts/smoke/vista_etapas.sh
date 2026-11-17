#!/bin/bash
# Real OCR/NER, authenticated preview, and temporary page overlays; no Compose resources.
set -euo pipefail
CHECKS="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$CHECKS/../.." && pwd)"
IMAGE="${SMOKE_IMAGE:-document-intelligence-smoke:local}"
AUTO=0
if [ "$#" -eq 1 ] && [ "$1" = "--automatico" ]; then AUTO=1
elif [ "$#" -eq 1 ] && { [ "$1" = "--help" ] || [ "$1" = "-h" ]; }; then
  echo "Uso: bash scripts/smoke/vista_etapas.sh [--automatico]"
  exit 0
elif [ "$#" -ne 0 ]; then
  echo "Uso: bash scripts/smoke/vista_etapas.sh [--automatico]" >&2
  exit 2
fi
if [ "$AUTO" = 0 ] && [ ! -t 0 ]; then
  echo "Se necesita una terminal; usa --automatico para verificar sin pausa." >&2
  exit 2
fi

CONTAINER=""
OUTPUT=""
cleanup() {
  local result=$? stage
  trap - EXIT
  if [ -n "$CONTAINER" ]; then docker stop "$CONTAINER" >/dev/null || result=1; fi
  if [ -n "$OUTPUT" ]; then
    rm -f -- "$OUTPUT/stages.json" || result=1
    for stage in ocr ner recovery_1 final; do rm -f -- "$OUTPUT/$stage.pdf" || result=1; done
    rmdir -- "$OUTPUT" 2>/dev/null || { echo "Revisa el directorio temporal: $OUTPUT" >&2; result=1; }
  fi
  exit "$result"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

docker image inspect "$IMAGE" >/dev/null
if [ ! -f "$ROOT/sample_pdfs/meeting_minutes.pdf" ]; then
  echo "Falta sample_pdfs/meeting_minutes.pdf" >&2
  exit 1
fi
umask 077
OUTPUT="$(mktemp -d "${TMPDIR:-/tmp}/extraction-stages.XXXXXX")"
# This value is public test data, not an operational secret.
TEST_TOKEN="synthetic-preview-token-0123456789-abcdef"
CONTAINER="$(docker run --rm -d --network none \
  -v "$ROOT/sample_pdfs:/samples:ro" -v "$CHECKS:/checks:ro" \
  -e PYTHONPATH=/app -e HF_HUB_OFFLINE=1 -e NER_NAME_RECOVERY_PASSES=1 \
  -e EXTRACT_PREVIEW_ENABLED=true -e EXTRACT_PREVIEW_TOKEN="$TEST_TOKEN" \
  --entrypoint uvicorn "$IMAGE" app.main:app --host 127.0.0.1 --port 8000)"
if ! docker exec "$CONTAINER" python /checks/verificar_vista_etapas.py collect > "$OUTPUT/stages.json"; then
  docker logs --tail 30 "$CONTAINER" >&2 || true
  exit 1
fi
echo "[OK] API protegida, documento temporal, etapas y reemplazo comprobados."
for stage in ocr ner recovery_1 final; do
  docker exec -i "$CONTAINER" python /checks/verificar_vista_etapas.py render "$stage" \
    < "$OUTPUT/stages.json" > "$OUTPUT/$stage.pdf"
  echo "  $stage: $OUTPUT/$stage.pdf"
done
echo "Rojo: OCR o NER; verde: ubicaciones recuperadas. Las copias son temporales."
if [ "$AUTO" = 0 ]; then
  read -r -p "Pulsa Enter para limpiar los archivos y terminar (Ctrl-C también limpia): " _
fi
echo "Revisión de etapas terminada; eliminando únicamente recursos propios."
