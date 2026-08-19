\set ON_ERROR_STOP on

-- The application creates its chunk table idempotently so the configured
-- embedding dimension remains the source of truth.
CREATE EXTENSION IF NOT EXISTS vector;
