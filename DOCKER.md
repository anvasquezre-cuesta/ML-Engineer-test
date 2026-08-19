# Run the application with Docker

Docker Compose starts the complete application:

| Service | Purpose | Default address |
|---|---|---|
| `frontend` | EvidenceDesk UI and API gateway | [http://localhost:3000](http://localhost:3000) |
| `backend` | FastAPI and API documentation | [http://localhost:8000](http://localhost:8000) |
| `postgres` | PostgreSQL with pgvector | `localhost:5432` |

The frontend uses Nginx to forward `/api/*` and `/health` to the backend. The
browser therefore uses one origin and the backend does not need CORS changes.

## First run

Create your local configuration once. Skip the copy if `.env` already exists:

```bash
cp .env_example .env
```

Add the API keys needed for ingestion and RAG to `.env`, then build and start
the stack:

```bash
docker compose up --build --detach
```

Check that all three containers are running and healthy:

```bash
docker compose ps
curl --fail http://localhost:8000/health
curl --fail http://localhost:3000/health
```

Open the UI at [http://localhost:3000](http://localhost:3000). FastAPI's
interactive documentation is available at
[http://localhost:8000/docs](http://localhost:8000/docs).

## Choose the operation you need

### Start or apply code changes

Build changed images and start or recreate services as needed:

```bash
docker compose up --build --detach
```

This is the normal command after pulling or changing code. Existing PostgreSQL
data is preserved.

### Restart without rebuilding

Restart the currently built containers:

```bash
docker compose restart
```

### Stop everything without losing data

```bash
docker compose down
```

Start it again later with:

```bash
docker compose up --detach
```

`docker compose down` removes containers and the Compose network, but keeps the
named PostgreSQL volume.

### Rebuild only the frontend

Use this after a frontend-only change when the backend is already running:

```bash
docker compose build frontend
docker compose up --detach --no-deps --force-recreate frontend
```

### Completely reset local data

> Warning: this permanently deletes the PostgreSQL volume and all indexed
> documents.

```bash
docker compose down --volumes
docker compose up --build --detach
```

Do not use `--volumes` or `-v` during a normal stop or restart.

## URLs and published ports

Ask Compose which host address is currently published:

```bash
docker compose port backend 8000
docker compose port frontend 8080
```

The defaults can be changed in `.env`:

```dotenv
API_PORT=8000
FRONTEND_PORT=3000
POSTGRES_PORT=5432
```

You can also override a port for one command:

```bash
API_PORT=18000 FRONTEND_PORT=13000 docker compose up --build --detach
```

The resulting addresses are `http://localhost:18000` for the backend and
`http://localhost:13000` for the frontend.

## Logs

Follow one service in real time:

```bash
docker compose logs --follow backend
docker compose logs --follow frontend
docker compose logs --follow postgres
```

Press `Ctrl+C` to stop following logs; the containers continue running. To see
only recent messages:

```bash
docker compose logs --tail 100 frontend
```

## Useful checks

Show container health and published ports:

```bash
docker compose ps
```

Verify the backend directly and through the frontend gateway:

```bash
curl --fail http://localhost:8000/health
curl --fail http://localhost:3000/health
```

Verify that the pgvector extension is installed:

```bash
docker compose exec postgres sh -c \
  'psql --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  --command "\dx vector"'
```

If the browser still shows an older frontend after rebuilding, use a hard
refresh with `Ctrl+Shift+R`.

For a compact command-only reminder, see
[`docs/docker-commands.md`](docs/docker-commands.md).
