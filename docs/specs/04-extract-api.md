# 04 - Endpoint `POST /api/extract`

**Objetivo:** un endpoint delgado que valida el upload y `names`, delega en una función pura OCR → NER → cajas → fuzzy y traduce los errores de dominio a HTTP, con un log JSON por request.
**Fuera de alcance:**
- RAG (`/api/ingest`, `/api/ask`; specs 05-06), aunque reutilizan las dependencias, el handler de errores y el log de esta spec;
- chequeo de cabecera `%PDF-` y 415 (D-API-4: `ocr_pages` ya rechaza por contenido y mupdf acepta basura antes de `%PDF`);
- reintentos (el OCR es local; los reintentos van en las llamadas externas de RAG), lifespan, `lru_cache` en dependencias, request-id propagado a otros servicios;
- cambios a `/health` (R8: ya es liveness).

**Contrato** (`schemas.py` no se cambia; responde `ExtractionResponse`):
- `POST /api/extract`, `multipart/form-data`: `pdf_file: UploadFile`, `names: Annotated[Json[list[NamePair]], Form()]`. FastAPI parsea y valida el JSON antes de llamar al endpoint y da el 422 nativo (`json_invalid`, `string_too_short`, `list_type`, `missing`; medido con FastAPI 0.162). `[]` es válido. Sin `TypeAdapter` ni try/except.
- `app/services/ocr_service.py` (cambios):
  - `class DocumentTooLargeError(ValueError)` y `class OcrEngineError(RuntimeError)`.
  - `ocr_pages`, tras `doc.is_pdf`: `doc.needs_pass` → `InvalidPdfError`; `doc.page_count > max_pages` → `DocumentTooLargeError`, antes de renderizar (misma apertura).
  - `tesseract_data`: `except (RuntimeError, pytesseract.TesseractNotFoundError)` → `OcrEngineError` (`from err`). El timeout de pytesseract es un `RuntimeError` genérico y `TesseractError` hereda de `RuntimeError` (medido).
- `app/services/bbox_service.py`: `locate_names(pages, recognizer=None)` pasa `recognizer` a `find_person_spans`.
- `app/services/extraction_service.py`: `extract(pdf_bytes: bytes, names: list[NamePair], engine: OcrEngine, recognizer: NameRecognizer) -> ExtractionResponse`. Sin clase: no hay estado. `fuzzy_match_names` recibe dicts (`fuzzy_service.py:42`): `[n.model_dump() for n in names]`.
- `app/dependencies.py`: `get_ocr_engine() -> OcrEngine` (devuelve `tesseract_data`) y `get_recognizer() -> NameRecognizer` (devuelve `spacy_persons`). Funciones simples para `Depends` y `app.dependency_overrides`; spaCy ya se carga una vez (`ner_service.py:18`).
- `app/api/extract.py`: lee `pdf_file.file.read(limit + 1)`; si pasa de `max_upload_mb` → `DocumentTooLargeError`. (`pdf_file.size` también serviría, pero puede ser `None` si el `UploadFile` no lo crea Starlette.)
- `app/main.py`: un dict `{InvalidPdfError: 422, DocumentTooLargeError: 413, OcrEngineError: 503}` y un handler que responde `{"detail": str(exc)}`; el middleware de log.
- `app/log.py`: `log_event(**fields)` escribe `json.dumps({"request_id": request_id.get(), **fields})` con el logger stdlib `"app"`, sin clase formatter. `main.py` hace `basicConfig(format="%(message)s")` y sube solo `"app"` a INFO (las librerías, p. ej. httpx, siguen en WARNING). Un middleware asigna `request_id` (contextvar; reutiliza `X-Request-ID` si llega), lo devuelve en la cabecera y llama a `log_event` con `method`, `path`, `status`, `ms`. La contextvar llega al endpoint `def` (medido). `extract` registra `pages`, `names_in`, `names_found`, `matches`: conteos, **nunca nombres** (PII).
- `app/config.py`: `max_upload_mb: int = 20` y `max_pages: int = 50` (positivos), en `.env.example`.

**Tabla de errores** (D-API-4, decidida por JM):
| Condición | Excepción | HTTP |
|---|---|---|
| `pdf_file` o `names` ausentes; `names` no es JSON o no cumple `NamePair` | `RequestValidationError` | 422 |
| vacío, no PDF, imagen, corrupto, cifrado con contraseña de usuario | `InvalidPdfError` | 422 |
| > `max_upload_mb` o > `max_pages` | `DocumentTooLargeError` | 413 |
| timeout de Tesseract o binario ausente | `OcrEngineError` | 503 |

**Presupuesto de líneas** (sin tests; cada pieza responde a una línea del README:78-89):
| Pieza | Líneas | Por qué hace falta |
|---|---|---|
| router + lectura con tope (`names` lo valida FastAPI) | ~10 | validación (README:84) y router delgado (README:78) |
| `extract` | ~12 | lógica testeable sin HTTP (README:79) |
| `dependencies.py` | ~6 | DI con Protocols (README:78), fakes en tests |
| errores + handler | ~10 | fallos con sentido, sin `except: pass` (README:82) |
| cifrado + `max_pages` + engine | ~8 | validación y recursos (README:84-85), R7 |
| `log.py` + 1 llamada | ~14 | logging estructurado con contexto (README:86) |
| config | 2 | sin valores fijos (README:80) |
| **Total** | **~62** | |

**Por qué así:** ver `tasks/04-extract-api/reviews/2026-10-29-decisions-critic.md` (D-API-1..4). El tope de tamaño solo rechaza: Starlette ya recibió el archivo (spool a disco > 1 MB) y lo cierra al terminar (medido).

**Datos de prueba:**
- **Unitarios:** `TestClient(app)` con `dependency_overrides` (fake engine de `test_ocr_service.py` y un recognizer lambda) y un fake que cuenta llamadas; PDF en blanco en memoria; PDF cifrado con `doc.tobytes(encryption=PDF_ENCRYPT_AES_256, user_pw=...)`. Config: `get_settings` se importa en cada módulo y tiene `lru_cache`, así que en los tests de API se usa una fixture con `monkeypatch.setenv(...)` y `get_settings.cache_clear()` antes y después. Sin Tesseract ni spaCy.
- **E2E:** `company_memo.pdf` con la lista del NB03 (Robert Chen, María García, Mario Garcia, Robert Chen duplicado, Juan Pérez) y `FUZZY_THRESHOLD=0.90` fijado (0.9167 depende del umbral). Esperado, escrito a mano en el test (no se lee `notebooks/`): los 8 nombres de `02a_name_boxes.csv` en su orden, todos en la página 0, y los 3 matches (`Maria Garcia`~`María García` 1.0, `Robert Chen`~`Robert Chen` 1.0, `Maria Garcia`~`Mario Garcia` 0.9167). `skipif` sin Tesseract o sin `en_core_web_sm`.

## Criterios de aceptación
- **AC-OCR-07** Given un PDF con contraseña de usuario, When `ocr_pages`, Then `InvalidPdfError` y el engine no se llama. _Test: unitario_
- **AC-OCR-08** Given `max_pages=1` y un PDF de 2 páginas, When `ocr_pages`, Then `DocumentTooLargeError` y el engine no se llama. _Test: unitario_
- **AC-OCR-09** Given `pytesseract.image_to_data` parcheado para lanzar `RuntimeError("Tesseract process timeout")` y `TesseractNotFoundError`, When `tesseract_data`, Then `OcrEngineError` con la causa encadenada. _Test: unitario_
- **AC-API-01** Given `ocr_dpi=72` (escala 1), un PDF de 1 página, un fake con "Ann" (`left=10, top=5, width=20, height=10`) y "Lee" (`left=35, top=7, width=15, height=10`) en `(1, 1, 1)`, un recognizer que devuelve `("Ann Lee", 0, 7)` y `names=[{"first_name": "ann", "last_name": "lee"}]`, When POST, Then 200 con `extracted_names == [{"name": "Ann Lee", "bounding_box": {"page_number": 0, "x": 10, "y": 5, "width": 40, "height": 12}}]` y `fuzzy_matches == [{"extracted_name": "Ann Lee", "matched_name": "ann lee", "score": 1.0}]`. _Test: unitario_
- **AC-API-02** Given un PDF válido, un fake que cuenta llamadas y `names` = `"not json"`, `'[{"first_name": "", "last_name": "Lee"}]'` y `'{}'`, When POST, Then 422 y el fake no se llamó. _Test: unitario_
- **AC-API-03** Given `b""` y `b"not a pdf"`, When POST, Then 422 con `detail` (el cifrado ya lo cubre AC-OCR-07; el mapeo es el mismo). _Test: unitario_
- **AC-API-04** Given `max_upload_mb=1` y 1 MiB + 1 byte, When POST, Then 413 y el engine no se llama (`max_pages` ya lo cubre AC-OCR-08; misma excepción). _Test: unitario_
- **AC-API-05** Given un engine que lanza `OcrEngineError`, When POST, Then 503 con `detail`. _Test: unitario_
- **AC-LOG-01** Given una request con `X-Request-ID: abc` y `names` con "Ann Lee", When POST, Then la respuesta trae `X-Request-ID: abc`, el log tiene una línea JSON con `request_id="abc"`, `status=200` y los conteos, y "Ann" no aparece en ningún registro. Sin cabecera, se genera uno. _Test: unitario_
- **AC-API-06** Given `company_memo.pdf` y la lista del NB03, When POST con Tesseract y spaCy reales, Then 200, 8 `extracted_names` en la página 0 y `fuzzy_matches` igual a `03_matches.csv`. _Test: e2e_

## Tareas (máx. 6)
1. Config `max_upload_mb`, `max_pages` y `.env.example`.
2. Tests en rojo AC-OCR-07..09; errores en `ocr_service.py` y `recognizer` en `locate_names`.
3. Tests en rojo AC-API-01..05; `extraction_service.py`, `dependencies.py`, router y handler en `main.py`.
4. Test en rojo AC-LOG-01; `app/log.py` y registro en `main.py`.
5. E2E AC-API-06 en `tests/integration/test_extract_e2e.py`.
6. `verify.ps1` en verde; notebook de la tarea: llamar al endpoint con `TestClient` sobre el memo.

## Explicación (JM)
_Por cada AC, en 3 a 5 líneas: qué líneas lo cumplen y por qué. Respuestas a 3 preguntas de entrevistador. Se firma solo cuando Jeison puede explicarlo sin mirar._

_Estará en el notebook local de la tarea 04 (sección «Explicación de los AC de la spec 04»), que no llega al repo._
