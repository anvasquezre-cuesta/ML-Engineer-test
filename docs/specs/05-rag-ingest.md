# 05 - Ingesta RAG `POST /api/ingest`

**Objetivo:** indexar un PDF escaneado para RAG: OCR por página → chunks que no cortan palabras → embeddings MiniLM → Chroma, con IDs únicos entre documentos y re-ingesta idempotente.
**Fuera de alcance:**
- `/api/ask`, el cliente LLM, `MIN_SCORE`, el prompt y `top_k` de la respuesta (spec 06);
- Chroma como servicio (`HttpClient`) con reintentos, compose, varios workers, `embedding_device="auto"` y `revision` fija del modelo (bonus 08);
- estrategias de chunking alternativas (por oraciones, recursiva, página entera), normalización del texto OCR y otro modelo de embeddings: medidos en el NB05, sin diferencia pareada con la estrategia elegida;
- `upsert`, un Protocol para el vector store y lifespan.

**Contrato** (`schemas.py` no se cambia; responde `IngestResponse(status="ingested", chunks_stored=n)`):
- `POST /api/ingest`, `multipart/form-data` con `pdf_file: UploadFile`. Misma lectura con tope y los mismos errores que `/api/extract`. El tope se comparte en `read_pdf(pdf_file) -> bytes` de `app/dependencies.py`, que los dos routers inyectan con `Depends`.
- `app/services/rag_service.py`:
  - `chunk_text(text: str, chunk_size: int = 500, overlap: int = 60) -> list[str]`: recorre `text.split()` acumulando palabras y cierra el chunk cuando la siguiente palabra lo haría pasar de `chunk_size`. El siguiente chunk empieza con las últimas palabras enteras del anterior que sumen como mucho `overlap` caracteres **y que, con la palabra siguiente, quepan en `chunk_size`**. Sin esta segunda condición, una cola de 20 más una palabra de 60 pasan de 50 (medido por el crítico: 1638 chunks fuera del límite en 300 textos). `ValueError` si no se cumple `0 <= overlap < chunk_size`. Una palabra más larga que `chunk_size` queda entera y sola en su chunk: ninguna cola de overlap cabe con ella.
  - `ingest(pdf_bytes: bytes, filename: str, engine: OcrEngine, embed: Embedder) -> IngestResponse`: `ocr_pages` + `page_text` por página, `chunk_text` con `chunk_size` y `chunk_overlap` de la config, metadata `{"doc_id", "filename", "page", "chunk"}` por chunk, `store_document_chunks` y `log_event(pages=..., chunks=...)` (conteos; ni nombres ni texto). Sin clase: no hay estado.
  - `doc_id = hashlib.sha256(pdf_bytes).hexdigest()`: el mismo contenido da el mismo id, aunque cambie el nombre del archivo.
- `app/services/embedding_service.py`:
  - `Embedder` (Protocol, `__call__(texts: list[str]) -> list[list[float]]`);
  - `_load_model(name, device)` con `lru_cache`: el modelo se carga una vez por proceso, como `ner_service._load_model`;
  - `get_embeddings(texts)`: `encode(texts, normalize_embeddings=True).tolist()`;
  - `get_query_embedding(text)`: `get_embeddings([text])[0]`.
- `app/services/vector_service.py`:
  - `class VectorStoreError(RuntimeError)`.
  - `_collection()` con `lru_cache`: un `PersistentClient(path=chroma_path, Settings(anonymized_telemetry=False))` por proceso, y `get_or_create_collection(chroma_collection, configuration={"hnsw": {"space": "cosine"}}, metadata={"embedding_model": embedding_model}, embedding_function=None)`. Si la colección ya existe con otro `embedding_model` (`(col.metadata or {}).get("embedding_model")`), lanza `VectorStoreError`: dos modelos de 384 dimensiones se mezclarían sin error (medido: `get_or_create` conserva la metadata original).
  - `init_collection()` llama a `_collection()`.
  - `store_document_chunks(chunks, metadata=None, embed=get_embeddings)`: `metadata` lleva un dict por chunk (solo la llama `ingest`). Si `chunks` está vacío, no hace nada: `add([])` y `delete($in=[])` lanzan `ValueError`, que no es `ChromaError` (medido). Embebe primero y luego `delete(where={"doc_id": {"$in": [...]}})` + `add(ids=[f"{doc_id}:{page}:{chunk}"], ...)`. El delete es necesario porque un `add` con un ID repetido se descarta en silencio (medido), y `upsert` dejaría chunks sobrantes si la versión nueva tiene menos.
  - `search_similar(query_embedding, top_k=5) -> list[dict]`: `query(query_embeddings=[...], include=["documents", "metadatas", "distances"])` → `{"text", "score": 1 - distance, "filename", "page", "chunk"}`. Nunca `query_texts`: con ella Chroma descarga su modelo ONNX (medido).
  - Todo error `chromadb.errors.ChromaError` (la base de `InternalError`, `NotFoundError` e `InvalidArgumentError`, medido) → `VectorStoreError` (`from err`).
- `app/dependencies.py`: `get_embedder() -> Embedder` (devuelve `get_embeddings`).
- `app/main.py`: `VectorStoreError: 503` en `ERROR_STATUS`.
- `app/config.py` y `.env.example`:
  - `embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"`;
  - `chunk_size: int = Field(500, gt=0)`;
  - `chunk_overlap: int = Field(60, ge=0)`;
  - `chroma_path: str = "data/chroma"` (fuera de git: `.gitignore`);
  - `chroma_collection: str = "documents"`.

**Tabla de errores** (la de 04 más una fila):
| Condición | Excepción | HTTP |
|---|---|---|
| vacío, no PDF, corrupto, cifrado | `InvalidPdfError` | 422 |
| > `max_upload_mb` o > `max_pages` | `DocumentTooLargeError` | 413 |
| Tesseract: timeout o binario ausente | `OcrEngineError` | 503 |
| Chroma: ruta no escribible, error interno, colección con otro modelo | `VectorStoreError` | 503 |

PDF sin texto (OCR vacío) → 200 con `chunks_stored=0`, igual que `/extract` con una página en blanco.

**Presupuesto de líneas** (sin tests; cada pieza responde a una línea del README:54-56, 78-98):
| Pieza | Líneas | Por qué hace falta |
|---|---|---|
| `chunk_text` | ~13 | no cortar palabras (README:95) |
| `ingest` + `doc_id` | ~18 | OCR → chunk → embed → store (README:54-56); IDs únicos (README:97) |
| `embedding_service` | ~12 | modelo cargado una vez (stub) |
| `vector_service` | ~41 | IDs únicos, re-ingesta, errores con sentido (README:97, stub) |
| router + `read_pdf` + dependencia | ~14 | router delgado (README:78) |
| config + `ERROR_STATUS` | ~6 | sin valores fijos (README:80) |
| **Total** | **~104** | |

**Por qué así:** `tasks/05-rag-ingest/reviews/` (auditoría de paquetes, literatura, NB05, decisiones del crítico). El NB05 compara 6 estrategias pregunta por pregunta: ninguna se distingue de la elegida (McNemar p ≥ 0.45). El overlap se elige por robustez de diseño: un nombre de persona en el borde de un chunk no se parte. Chroma embebido va con un solo worker: con varios procesos, un lector ve `count` nuevo, pero su `query` devuelve el índice viejo (medido).

**Datos de prueba:**
- **Unitarios:** un `Embedder` falso y determinista (vector de 384 dimensiones derivado del texto, normalizado). Chroma real en `tmp_path`: fixture con `monkeypatch.setenv("CHROMA_PATH", ...)`, `get_settings.cache_clear()` y `_collection.cache_clear()` antes y después. Fake de OCR como en `test_extract_api.py`. Sin modelos ni red.
- **Integración:** MiniLM real (`skipif` si el modelo no está en la caché de HF) y `PersistentClient` en `tmp_path`.

## Criterios de aceptación
- **AC-CHK-01** Given texto aleatorio con palabras de 1 a 60 letras (semilla fija) y `chunk_size=50`, `overlap=20`, When `chunk_text`, Then cada chunk está formado solo por palabras enteras del texto, en orden, mide ≤ 50 salvo que contenga una palabra de más de 50, y toda palabra de `text.split()` aparece en algún chunk, en orden. _Test: unitario_
- **AC-CHK-02** Given "Richard Hernandez called the meeting to order. Jennifer Liu confirmed quorum." y `chunk_size=50`, `overlap=20`, When `chunk_text`, Then el segundo chunk empieza con palabras enteras del final del primero (≤ 20 caracteres) y algún chunk contiene "Jennifer Liu" completo. _Test: unitario_
- **AC-CHK-03** Given `""`, `"   \n "`, una palabra de 600 caracteres y `overlap >= chunk_size`, When `chunk_text`, Then `[]`, `[]`, `[palabra]` y `ValueError`. _Test: unitario_
- **AC-VEC-01** Given dos documentos distintos con un chunk cada uno en la página 0, When `store_document_chunks` de los dos, Then `count == 2` y existen `"{doc_a}:0:0"` y `"{doc_b}:0:0"`: la segunda ingesta no pisa la primera. _Test: unitario_
- **AC-VEC-02** Given el documento A guardado con 3 chunks, When se re-ingesta A con 2 chunks, Then quedan solo los 2 nuevos de A y B no cambia. _Test: unitario_
- **AC-VEC-03** Given chunks guardados con el embedder falso, When `search_similar(embed(text_x), top_k=2)`, Then el primero es `text_x` con `score ≈ 1.0` y trae `filename`, `page` y `chunk`, y el segundo tiene `score` igual al coseno entre los dos vectores falsos (±1e-6). Con L2 saldría `2·cos − 1`, así que el AC detecta que falte `space: cosine`. _Test: unitario_
- **AC-VEC-04** Given `CHROMA_PATH` apuntando a un archivo existente (no se puede usar como carpeta: `InternalError` en Windows, medido), y aparte una colección creada con `EMBEDDING_MODEL=A` y reabierta con `EMBEDDING_MODEL=B` (`_collection.cache_clear()` entre las dos), When `init_collection`, Then `VectorStoreError` en los dos casos (con `ChromaError` como causa en el primero). Igual si `store_document_chunks` o `search_similar` reciben vectores de otra dimensión que la colección. _Test: unitario_
- **AC-ING-01** Given el fake de OCR con dos páginas de texto y el embedder falso por `dependency_overrides`, When POST `/api/ingest`, Then 200 con `status == "ingested"` y `chunks_stored` igual al número de chunks de `chunk_text` sobre las dos páginas, los IDs llevan el sha256 del PDF, y el log tiene un evento con `pages` y `chunks` sin el `filename`. _Test: unitario_
- **AC-ING-02** Given un PDF cuyo OCR no devuelve palabras, When POST, Then 200 con `chunks_stored == 0` y la colección no cambia. _Test: unitario_
- **AC-ING-03** Given `b"not a pdf"`, 1 MiB + 1 byte con `max_upload_mb=1`, y aparte un `store_document_chunks` que lanza `VectorStoreError`, When POST, Then 422, 413 y 503 con `detail`, y en los dos primeros el embedder no se llama. _Test: unitario_
- **AC-INT-01** Given MiniLM real y `PersistentClient` en `tmp_path`, When se ingestan A, B y otra vez los mismos bytes de A con un texto OCR más corto (menos chunks; con el texto idéntico, un `add` sin `delete` pasaría porque Chroma descarta en silencio los IDs repetidos), Then `count` = chunks(A) + chunks(B) tras cada paso, con los chunks de la última versión de A, y `search_similar` con una pregunta sobre B devuelve primero un chunk de B. _Test: integración_
- **AC-EMB-01** Given MiniLM real, When `get_embeddings(["a", "b"])` y `get_query_embedding("a")`, Then 2 vectores de 384 dimensiones con norma 1 ± 1e-6, y el de la consulta es igual al primero con tolerancia 1e-5 (dentro de un lote difiere en ~1e-7, medido). _Test: integración_

## Tareas (máx. 6)
1. Config (`embedding_model`, `chunk_size`, `chunk_overlap`, `chroma_path`, `chroma_collection`), `.env.example` y `.gitignore` (`data/`).
2. Tests en rojo AC-CHK-01..03; `chunk_text`.
3. Tests en rojo AC-VEC-01..04; `vector_service.py` y `VectorStoreError: 503`.
4. Tests en rojo AC-ING-01..03; `embedding_service.py`, `ingest`, `get_embedder`, `read_pdf` y el router `/api/ingest`.
5. AC-INT-01 y AC-EMB-01 en `tests/integration/`.
6. `verify.ps1` en verde; NB05 "Desde `app/`": la métrica de recuperación con `app.services.rag_service.chunk_text` frente a la del proto.

## Explicación (JM)
_Por cada AC, en 3 a 5 líneas: qué líneas lo cumplen y por qué. Respuestas a 3 preguntas de entrevistador. Se firma solo cuando Jeison puede explicarlo sin mirar._

_Estará en el notebook local de la tarea 05 (`05_rag.ipynb`, sección «Explicación de los AC de la spec 05»), que no llega al repo._
