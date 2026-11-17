#!/bin/bash
# Hito 5 E2E: isolated HTTP/OCR/embeddings/SQLite/Qdrant, no Compose changes.
# By default the answer generator is simulated. --gemini explicitly calls Google.
set -euo pipefail
CHECKS="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$CHECKS/../.." && pwd)"
IMAGE="${SMOKE_IMAGE:-document-intelligence-stage-preview:local}"
QDRANT_IMAGE="${SMOKE_QDRANT_IMAGE:-qdrant/qdrant:v1.13.6}"
MODE="simulado"
if [ "$#" -eq 1 ] && [ "$1" = "--gemini" ]; then
  MODE="gemini"
elif [ "$#" -eq 1 ] && [ "$1" = "--simulado" ]; then
  MODE="simulado"
elif [ "$#" -eq 1 ] && { [ "$1" = "--help" ] || [ "$1" = "-h" ]; }; then
  echo "Uso: bash scripts/smoke/rag_e2e.sh [--simulado|--gemini]"
  echo "Sin argumentos usa un generador simulado. --gemini envía datos sintéticos a Google."
  exit 0
elif [ "$#" -ne 0 ]; then
  echo "Uso: bash scripts/smoke/rag_e2e.sh [--simulado|--gemini]" >&2
  exit 2
fi

PREFIX="rag-e2e-$(date +%Y%m%d%H%M%S)-$$-$RANDOM"
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

docker image inspect "$IMAGE" >/dev/null
docker image inspect "$QDRANT_IMAGE" >/dev/null
set --
if [ "$MODE" = "gemini" ]; then
  if [ ! -f "$ROOT/.env" ]; then
    echo "Falta .env con Gemini configurado; no se mostrará ni creará automáticamente." >&2
    exit 1
  fi
  set -- --env-file "$ROOT/.env"
  APP_MODULE="app.main:app"
  # A bridge permits egress; it is not a domain-level firewall.
  NETWORK="$(docker network create "$PREFIX")"
  echo "Modo Gemini real: se enviarán datos sintéticos a Google y puede consumirse cuota."
  echo "No se imprime la clave; usuarios privilegiados de Docker pueden inspeccionar el entorno."
else
  APP_MODULE="serve_ask_fake:app"
  NETWORK="$(docker network create --internal "$PREFIX")"
  echo "Modo simulado: OCR, embeddings, HTTP, SQLite y Qdrant reales; sin llamadas a LLM."
fi

QDRANT="$(docker run --rm -d --network "$NETWORK" --network-alias qdrant "$QDRANT_IMAGE")"
API="$(docker run --rm -d --network "$NETWORK" "$@" \
  -v "$ROOT/app:/app/app:ro" -v "$CHECKS:/checks:ro" \
  -e PYTHONPATH=/app:/checks -e QDRANT_URL=http://qdrant:6333 \
  -e INGESTION_LEDGER_PATH=/app/data/ingestion/ledger.sqlite3 -e HF_HUB_OFFLINE=1 \
  -e EXTRACT_PREVIEW_ENABLED=false \
  --entrypoint uvicorn "$IMAGE" "$APP_MODULE" --host 127.0.0.1 --port 8000)"

docker exec "$API" python -u /checks/verificar_rag_e2e.py "$MODE"
echo "Comprobación terminada; se limpiarán únicamente sus contenedores y red."
