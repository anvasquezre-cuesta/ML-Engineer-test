# Docker command reference

Run these commands from the repository root.

## Start or update the stack

Build changed images and start all services in the background:

```bash
docker compose up --build --detach
```

For a complete restart while preserving PostgreSQL data:

```bash
docker compose down
docker compose up --build --detach
```

Do not add `--volumes` or `-v` to `docker compose down` unless you intentionally
want to delete the PostgreSQL data volume.

## Service URLs

Show the published backend address:

```bash
docker compose port backend 8000
```

The default backend URL is `http://localhost:8000`, and its interactive API
documentation is at `http://localhost:8000/docs`.

Show the published frontend address:

```bash
docker compose port frontend 8080
```

The default frontend URL is `http://localhost:3000`.

## Service logs

Follow backend logs:

```bash
docker compose logs --follow backend
```

Follow frontend logs:

```bash
docker compose logs --follow frontend
```

Press `Ctrl+C` to stop following logs without stopping the containers.

## Health checks

Verify the backend directly and through the frontend gateway:

```bash
curl http://localhost:8000/health
curl http://localhost:3000/health
```

Both commands should return `{"status":"ok"}`.
