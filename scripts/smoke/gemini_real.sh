#!/bin/bash
# Real external Gemini call; synthetic data, disposable containers, no Compose changes.
set -euo pipefail
CHECKS="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$CHECKS/../.." && pwd)"
IMAGE="${SMOKE_IMAGE:-document-intelligence-stage-preview:local}"
QDRANT_IMAGE="${SMOKE_QDRANT_IMAGE:-qdrant/qdrant:v1.13.6}"
PREFIX="gemini-smoke-$(date +%Y%m%d%H%M%S)-$$-$RANDOM"
NETWORK=""
API=""
QDRANT=""

cleanup() {
  local result=$? id
  trap - EXIT
  for id in "$API" "$QDRANT"; do
    if [ -n "$id" ]; then docker stop "$id" >/dev/null || result=1; fi
  done
  if [ -n "$NETWORK" ]; then docker network rm "$NETWORK" >/dev/null || result=1; fi
  exit "$result"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

if [ ! -f "$ROOT/.env" ]; then
  echo "Falta el archivo privado .env; no se mostrará ni creará automáticamente." >&2
  exit 1
fi
docker image inspect "$IMAGE" >/dev/null
docker image inspect "$QDRANT_IMAGE" >/dev/null
set --
if [ -n "${SMOKE_GEMINI_MAX_OUTPUT_TOKENS:-}" ]; then
  if ! [[ "$SMOKE_GEMINI_MAX_OUTPUT_TOKENS" =~ ^[0-9]{1,4}$ ]] || \
      [ "$SMOKE_GEMINI_MAX_OUTPUT_TOKENS" -lt 32 ] || [ "$SMOKE_GEMINI_MAX_OUTPUT_TOKENS" -gt 2048 ]; then
    echo "SMOKE_GEMINI_MAX_OUTPUT_TOKENS debe ser un entero entre 32 y 2048." >&2
    exit 2
  fi
  set -- -e "LLM_MAX_OUTPUT_TOKENS=$SMOKE_GEMINI_MAX_OUTPUT_TOKENS"
  echo "Límite de salida solo para esta prueba: $SMOKE_GEMINI_MAX_OUTPUT_TOKENS tokens."
fi

# A bridge allows outbound access to Gemini. It is not a domain-level firewall;
# neither service publishes host ports and storage is container-local and ephemeral.
NETWORK="$(docker network create "$PREFIX")"
QDRANT="$(docker run --rm -d --network "$NETWORK" --network-alias qdrant "$QDRANT_IMAGE")"
API="$(docker run --rm -d --network "$NETWORK" --env-file "$ROOT/.env" "$@" \
  -v "$ROOT/app:/app/app:ro" -v "$CHECKS:/checks:ro" \
  -e PYTHONPATH=/app:/checks -e QDRANT_URL=http://qdrant:6333 \
  -e INGESTION_LEDGER_PATH=/app/data/ingestion/ledger.sqlite3 -e HF_HUB_OFFLINE=1 \
  --entrypoint uvicorn "$IMAGE" app.main:app --host 127.0.0.1 --port 8000)"

echo "Prueba real con Gemini: solo PDF/preguntas sintéticas; puede consumir cuota."
echo "La clave no se imprime; usuarios privilegiados de Docker pueden inspeccionar el entorno."
echo "Las consultas se espacian; no se reintentan automáticamente los errores del proveedor."
if ! docker exec -e SMOKE_GEMINI_INTERVAL_SECONDS="${SMOKE_GEMINI_INTERVAL_SECONDS:-15}" \
    -e SMOKE_GEMINI_CASES="${SMOKE_GEMINI_CASES:-}" \
    -e SMOKE_GEMINI_DATASET="${SMOKE_GEMINI_DATASET:-v2}" \
    "$API" python -u /checks/verificar_gemini_real.py; then
  echo "Diagnósticos seguros disponibles (solo tipo de dependencia y estado HTTP, sin cuerpo):" >&2
  docker logs "$API" 2>&1 | grep -E 'Model provider returned HTTP status [0-9]+|Model provider returned an invalid response|Model provider request failed|Model provider timed out|Gemini completion did not finish normally: reason=|Question answering unavailable: dependency=' >&2 || true
  exit 1
fi
echo "Prueba terminada; eliminando únicamente los contenedores y red de esta ejecución."
