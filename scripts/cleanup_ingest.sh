#!/bin/bash
# Use the already running application with its configured ledger volume/network.
# Does not create, start or restart any Compose service.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [ "$#" -eq 0 ]; then
  echo "Usage: bash scripts/cleanup_ingest.sh --pending | --id UUID [--execute] [--confirm-quiescent]" >&2
  exit 2
fi
exec docker compose --project-directory "$ROOT" -f "$ROOT/docker-compose.yml" exec -T app \
  python -m app.maintenance.cleanup_ingest "$@"
