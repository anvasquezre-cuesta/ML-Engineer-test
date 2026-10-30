# 08c - Página para preguntar a los documentos (`/viewer/ask.html`)

**Objetivo:** una página HTML autocontenida (vanilla JS, sin librerías) que sube PDFs a `POST /api/ingest` y hace preguntas a `POST /api/ask`, para que un revisor use el RAG sin curl.

**Fuera de alcance:**
- cambios de backend (ni `schemas.py` ni Python de `app/`);
- streaming de la respuesta;
- historial de chat;
- mostrar el texto de los chunks: la API solo devuelve IDs;
- borrar documentos.

**Contrato:**
- `app/viewer/ask.html`, un solo archivo con HTML, CSS y JS inline, servido por el mount `/viewer` existente (sin tocar `main.py`).
- Ingest: input de archivos PDF `multiple`; un `POST /api/ingest` (`FormData`, campo `pdf_file`) por archivo, en secuencia, y una línea por archivo: `<nombre>: <chunks_stored> chunks stored`.
- Ask: input de pregunta y botón (Enter también envía); `POST /api/ask` con `{"question": ...}`. Mientras espera muestra "Thinking…", que se borra si hay error.
- Fuentes: el ID `file:pN:cK` se muestra como `file · page N+1 · chunk K` (la página del ID es base 0).
- Si `sources` está vacío se muestra "No sources (the service abstained)" junto a la respuesta.
- Si la API responde con error, se muestra el `detail`: tal cual si es texto, `JSON.stringify(detail)` si es la lista de validación.
- Todo dato se escribe con `textContent`. Enlace al visor (`./`) en `ask.html` y una línea en `index.html` con enlace a `ask.html`.

## Criterios de aceptación
- **AC-ASK-PAGE-01** Given la app, When `GET /viewer/ask.html`, Then responde 200 `text/html` y el HTML contiene `/api/ingest` y `/api/ask`. _Test: unitario (TestClient)_
- **AC-ASK-PAGE-02** Given el servidor con Ollama, When JM ingesta `sample_pdfs/company_memo.pdf`, Then aparece "company_memo.pdf: N chunks stored"; y al preguntar "Who was promoted to Vice President of Engineering?" aparecen la respuesta y fuentes como "company_memo.pdf · page 1 · chunk 0". _Test: manual_
- **AC-ASK-PAGE-03** Given la página, When:
  - la pregunta no tiene respuesta ("Who won the 2022 football World Cup?"), Then se ve la abstención sin fuentes;
  - Ollama está cerrado, Then se ve el `detail` del 503;
  - se sube un archivo no PDF, Then se ve el 422 legible.

  _Test: manual_

## Tareas (máx. 6)
1. Test en rojo AC-ASK-PAGE-01.
2. `app/viewer/ask.html` y el enlace en `index.html`.
3. Revisión manual AC-ASK-PAGE-02 y 03.

## Explicación (JM)
Por cada AC, en 3 a 5 líneas: qué líneas lo cumplen y por qué. Respuestas a 3 preguntas de entrevistador.
Firmada solo cuando Jeison puede explicarlo sin mirar.
