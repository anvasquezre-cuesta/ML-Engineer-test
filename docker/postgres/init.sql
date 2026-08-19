\set ON_ERROR_STOP on

-- Keep bootstrap limited to infrastructure. The RAG tables will be managed by
-- migrations once the persistence implementation has been selected.
CREATE EXTENSION IF NOT EXISTS vector;
