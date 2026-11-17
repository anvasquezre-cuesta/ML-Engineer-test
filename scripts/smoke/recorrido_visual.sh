#!/bin/bash
# Step-by-step inspection in disposable resources, never existing Compose services.
set -euo pipefail
CHECKS="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$CHECKS/../.." && pwd)"
IMAGE="${SMOKE_IMAGE:-document-intelligence-smoke:local}"
QDRANT_IMAGE="${SMOKE_QDRANT_IMAGE:-qdrant/qdrant:v1.13.6}"
AUTO=0
if [ "$#" -eq 1 ] && [ "$1" = "--automatico" ]; then
  AUTO=1
elif [ "$#" -eq 1 ] && { [ "$1" = "--help" ] || [ "$1" = "-h" ]; }; then
  echo "Uso: bash scripts/smoke/recorrido_visual.sh [--automatico]"
  echo "Consulta README.md para el recorrido y las precauciones de privacidad."
  exit 0
elif [ "$#" -ne 0 ]; then
  echo "Uso: bash scripts/smoke/recorrido_visual.sh [--automatico]" >&2
  exit 2
fi
if [ "$AUTO" = 0 ] && [ ! -t 0 ]; then
  echo "Se necesita una terminal interactiva; para probar sin pausas usa --automatico." >&2
  exit 2
fi

PREFIX="visual-ingest-$(date +%Y%m%d%H%M%S)-$$-$RANDOM"
NETWORK=""
VECTOR_VOLUME=""
LEDGER_VOLUME=""
API=""
QDRANT=""
SNAPSHOT_DIR=""
SNAPSHOT=""
SYNTHETIC=""

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
        echo "No se pudo verificar el propietario; no se elimina el volumen $volume" >&2
        result=1
      fi
    fi
  done
  if [ -n "$NETWORK" ]; then docker network rm "$NETWORK" >/dev/null || result=1; fi
  if [ -n "$SNAPSHOT" ]; then rm -f -- "$SNAPSHOT" || result=1; fi
  if [ -n "$SYNTHETIC" ]; then rm -f -- "$SYNTHETIC" || result=1; fi
  if [ -n "$SNAPSHOT_DIR" ]; then
    rmdir -- "$SNAPSHOT_DIR" 2>/dev/null || { echo "Revisa el directorio temporal: $SNAPSHOT_DIR" >&2; result=1; }
  fi
  echo "Recorrido terminado: solo se limpiaron los recursos temporales propios."
  exit "$result"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

pause() {
  if [ "$AUTO" = 0 ]; then
    echo
    read -r -p "Pulsa Enter para continuar (Ctrl-C para terminar y limpiar): " _
  fi
}

create_owned_volume() {
  local volume
  if docker volume inspect "$1" >/dev/null 2>&1; then
    echo "El volumen ya existe; no se reutilizará: $1" >&2
    return 1
  fi
  volume="$(docker volume create --label "io.document-intelligence.smoke.owner=$PREFIX" "$1")"
  if [ "$(docker volume inspect --format '{{index .Labels "io.document-intelligence.smoke.owner"}}' "$volume")" != "$PREFIX" ]; then
    echo "No se reconoce el propietario; no se usará ni eliminará: $volume" >&2
    return 1
  fi
  printf '%s\n' "$volume"
}

wait_for_http() {
  local url="$1" attempt
  for attempt in {1..90}; do
    if curl --silent --show-error --fail --max-time 2 "$url" -o /dev/null 2>/dev/null; then return 0; fi
    sleep 0.5
  done
  echo "El servicio no respondió: $url" >&2
  return 1
}

docker image inspect "$IMAGE" >/dev/null
docker image inspect "$QDRANT_IMAGE" >/dev/null
command -v curl >/dev/null
if [ ! -f "$ROOT/sample_pdfs/meeting_minutes.pdf" ]; then
  echo "No se encuentra sample_pdfs/meeting_minutes.pdf" >&2
  exit 1
fi

echo "Paso 1/5 — Crear API y Qdrant aislados, con puertos aleatorios solo en 127.0.0.1."
NETWORK="$(docker network create "$PREFIX")"
VECTOR_VOLUME="$(create_owned_volume "$PREFIX-vectors")"
LEDGER_VOLUME="$(create_owned_volume "$PREFIX-ledger")"
QDRANT="$(docker run --rm -d --network "$NETWORK" --network-alias qdrant \
  -p 127.0.0.1::6333 -e QDRANT__TELEMETRY_DISABLED=true \
  -v "$VECTOR_VOLUME:/qdrant/storage" "$QDRANT_IMAGE")"
API="$(docker run --rm -d --network "$NETWORK" -p 127.0.0.1::8000 \
  -v "$ROOT/sample_pdfs:/samples:ro" -v "$CHECKS:/checks:ro" \
  -v "$LEDGER_VOLUME:/app/data/ingestion" \
  -e PYTHONPATH=/app -e QDRANT_URL=http://qdrant:6333 -e HF_HUB_OFFLINE=1 \
  --entrypoint uvicorn "$IMAGE" app.main:app --host 0.0.0.0 --port 8000)"
API_BINDING="$(docker port "$API" 8000/tcp)"
QDRANT_BINDING="$(docker port "$QDRANT" 6333/tcp)"
API_URL="http://$API_BINDING"
QDRANT_URL="http://$QDRANT_BINDING"
wait_for_http "$API_URL/health"
wait_for_http "$QDRANT_URL/readyz"
wait_for_http "$QDRANT_URL/dashboard/"
echo "[OK] API: $API_URL/docs"
echo "[OK] Qdrant Dashboard: $QDRANT_URL/dashboard/"
echo "Son servicios nuevos de prueba; NO son los contenedores Compose existentes."
pause

echo "Paso 2/5 — Ingerir el PDF de ejemplo y observar sus páginas y fragmentos."
docker exec "$API" python -u /checks/recorrido_visual.py pdf
pause

echo "Paso 3/5 — Reingerir el mismo PDF y comparar hash e identificadores."
docker exec "$API" python -u /checks/recorrido_visual.py duplicado
pause

echo "Paso 4/5 — Ingerir un escaneo sintético con la primera página vacía."
umask 077
SNAPSHOT_DIR="$(mktemp -d "${TMPDIR:-/tmp}/visual-ingest.XXXXXX")"
SYNTHETIC="$SNAPSHOT_DIR/pagina-vacia.pdf"
docker exec "$API" python /checks/recorrido_visual.py pdf-sintetico > "$SYNTHETIC"
docker exec -i "$API" python -u /checks/recorrido_visual.py pagina-vacia < "$SYNTHETIC"
echo "Abre el PDF sintético para compararlo: $SYNTHETIC"
pause

echo "Paso 5/5 — Inspeccionar Qdrant y una copia coherente del ledger SQLite."
SNAPSHOT="$SNAPSHOT_DIR/ledger.sqlite3"
docker exec "$API" python /checks/recorrido_visual.py snapshot > "$SNAPSHOT"
docker exec -i "$API" python /checks/recorrido_visual.py verificar-snapshot < "$SNAPSHOT"
echo "Qdrant Dashboard: $QDRANT_URL/dashboard/"
echo "Colección: documents_minilm_1110a243_v1 (filtra kind=chunk)."
echo "Copia SQLite para DB Browser for SQLite: $SNAPSHOT"
echo "Configuración y precauciones: README.md"
echo "Cierra el visor SQLite antes de continuar: la copia y los datos de prueba se eliminarán."
pause
