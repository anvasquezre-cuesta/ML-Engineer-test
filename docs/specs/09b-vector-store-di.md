# 09b - Almacén vectorial inyectable

**Objetivo:** que el servicio RAG dependa de dos callables (`ChunkStore`, `ChunkSearch`) inyectados con `Depends`, igual que `Embedder` y `LLM`, y no de las funciones de Chroma importadas directamente.

**Fuera de alcance:**
- cambiar Chroma, los IDs, el borrado y el `add`, o las respuestas de la API;
- una clase o un adaptador nuevo: las funciones actuales ya cumplen los Protocols;
- reescribir los tests que usan Chroma en un directorio temporal (siguen valiendo).

**Contrato:**
- `app/services/vector_service.py`: `ChunkStore` (`(chunks, metadata, embed) -> None`) y `ChunkSearch` (`(query_embedding, top_k) -> list[dict]`) como `Protocol`, junto a las funciones que los cumplen. `metadata` pasa a ser obligatorio (hoy `None` revienta en la línea del `for`).
- `app/dependencies.py`: `get_chunk_store()` y `get_chunk_search()`.
- `rag_service.ingest(..., store=store_document_chunks)` y `generate_answer(..., search=search_similar)`: el valor por defecto mantiene las llamadas actuales.
- `app/api/rag.py` los inyecta con `Depends`. Sin cambios en `schemas.py`.

## Criterios de aceptación
- **AC-VEC-DI-01** Given `get_chunk_store` sobrescrito con un falso que guarda lo recibido, When `POST /api/ingest` de un PDF con texto, Then el falso recibe los chunks y su metadata, y la colección de Chroma sigue vacía. _Test: unitario (TestClient)_
- **AC-VEC-DI-02** Given `get_chunk_search` sobrescrito con un falso que devuelve un hit con score ≥ `MIN_SCORE`, y un LLM falso, When `POST /api/ask`, Then `sources` es el ID de ese hit y Chroma no se consulta. _Test: unitario (TestClient)_

## Tareas
1. Tests en rojo en `tests/unit/test_ingest_api.py` y `tests/unit/test_ask_api.py`.
2. Protocols en `vector_service.py`; `metadata` obligatorio.
3. Parámetros con valor por defecto en `rag_service.py`; `Depends` en `api/rag.py` y `dependencies.py`.
4. El test que hoy hace `monkeypatch` de `rag_service.store_document_chunks` pasa a `dependency_overrides`.
5. DESIGN.md:30 añade `ChunkStore` y `ChunkSearch` a la lista de Protocols.

## Explicación (JM)
En `tasks/09-final-eval/explicacion-ac.md`.
