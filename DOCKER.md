# Docker Compose

The Compose stack builds the FastAPI backend with Tesseract and the configured
spaCy model, starts PostgreSQL 17 with the pgvector extension, and waits for the
database health check before starting the API.

## Start the stack

```bash
cp .env_example .env
docker compose up --build --detach
docker compose ps
curl --fail http://localhost:8000/health
```

If port `8000` is already in use, select another host port without changing
the container configuration:

```bash
API_PORT=18000 docker compose up --build --detach
curl --fail http://localhost:18000/health
```

Verify that pgvector was initialized in the application database:

```bash
docker compose exec postgres sh -c \
  'psql --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  --command "\dx vector"'
```

Configuration and development-only database credentials are listed in
`.env_example`. Replace the password for any non-local deployment. Data is kept
in the `postgres_data` volume when the containers stop:

```bash
docker compose logs --follow backend
docker compose down
```

`docker compose down --volumes` also deletes the PostgreSQL data and should be
used only when a full local reset is intended.
