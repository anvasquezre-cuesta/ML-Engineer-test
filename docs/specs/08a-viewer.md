# 08a - Visor de auditoría (`/viewer/`)

**Objetivo:** una página HTML autocontenida (vanilla JS + pdf.js, README:106-111) que recibe un PDF y una lista de nombres, llama a `POST /api/extract`, renderiza cada página y dibuja encima las cajas devueltas, para que un revisor confirme que cada nombre está donde dice la API.

**Fuera de alcance:**
- `BBOX_ORIGIN=bottom-left`: el visor asume `top-left`, el valor por defecto, y lo dice en la página;
- build de JS, frameworks, npm, tests en navegador (Playwright);
- RAG en el visor;
- cambios en `schemas.py` o en `/api/extract`.

**Contrato:**
- `app/viewer/index.html`, un solo archivo con HTML, CSS y JS inline.
  - pdf.js 6.4.299 desde cdnjs, como ESM: `pdf.min.mjs` y `pdf.worker.min.mjs` en `GlobalWorkerOptions.workerSrc`.
- `app/main.py`: `app.mount("/viewer", StaticFiles(directory=Path(__file__).parent / "viewer", html=True), name="viewer")`. Mismo origen que la API, sin CORS y sin dependencias nuevas.
- En la página:
  - un input de archivo PDF;
  - un textarea con `names` en JSON, `[]` por defecto;
  - un botón que hace `fetch("/api/extract")` con `FormData` (`pdf_file`, `names`).
- Para cada página (`getPage(n + 1)`, porque `page_number` empieza en 0):
  - un canvas con `getViewport({scale})`;
  - cada caja es un `div` posicionado en `left = x·scale`, `top = y·scale`, `width = w·scale`, `height = h·scale`, con el nombre como etiqueta.
- Cada página lleva el título `Page k of n`, con n = `pdf.numPages` (añadido en la revisión manual del 2026-10-30: la página 2 quedaba fuera de pantalla y no se notaba).
- Cada página es un `div` con `position:relative`. El canvas mide en CSS `viewport.width × viewport.height` y nada lo escala (sin `max-width`). La escala es una constante del JS (`SCALE = 1.5`). La nitidez en HiDPI no entra.
- Las cajas cuyo `name` coincide exactamente con algún `fuzzy_matches[].extracted_name` llevan otro color, y debajo va la tabla de coincidencias.
- Si la API responde con error, se muestra el `detail` en la página: tal cual si es texto, y con `JSON.stringify(detail)` si es la lista de validación de FastAPI.

Por qué la caja es la de la API multiplicada por la escala: las cajas están en puntos con origen arriba a la izquierda, sobre el `page.rect` de PyMuPDF. El viewport de pdf.js tiene las mismas dimensiones que ese rect, también con cropbox desplazado o con página rotada. Verificado con un PDF de prueba en `tasks/08-bonus/reviews/2026-10-30-viewer-research.md`.

**Datos de prueba:** `sample_pdfs/company_memo.pdf` con los nombres de `tests/integration/test_extract_e2e.py:18-24`. Resultado esperado: 8 cajas en la página 0; Robert Chen y Maria Garcia resaltados. También `meeting_minutes.pdf`, con 2 páginas.

## Criterios de aceptación
- **AC-VIEW-01** Given la app, When `GET /viewer/`, Then:
  - responde 200 `text/html`;
  - el HTML contiene `pdf.js/6.4.299/pdf.min.mjs` y `pdf.js/6.4.299/pdf.worker.min.mjs`;
  - el HTML llama a `/api/extract`.

  _Test: unitario (TestClient)_
- **AC-VIEW-02** Given el servidor con Tesseract, When JM abre `/viewer/` con `company_memo.pdf` y la lista del e2e, Then:
  - aparecen 8 cajas sobre los 8 nombres de la página 0, a ojo y sin desplazamiento;
  - Robert Chen y Maria Garcia se ven resaltados.

  Con `meeting_minutes.pdf` las cajas caen en las páginas 0 y 1. Queda una captura en `tasks/08-bonus/reviews/`. _Test: manual_
- **AC-VIEW-03** Given un PNG renombrado a `.pdf`, o un JSON inválido en el textarea, When se envía, Then la página muestra el `detail` del 422 en forma legible (nunca `[object Object]`) y sigue usable. _Test: manual_

## Tareas (máx. 6)
1. Test en rojo AC-VIEW-01.
2. `app/viewer/index.html` y el `mount` en `main.py`.
3. Revisión manual AC-VIEW-02 y 03, con captura.
4. `RUNNING.md`: una línea con la URL del visor. DECISIONS.md, con texto que JM aprueba:
   - pdf.js desde la CDN es un trade-off: sin red no hay visor, y el import ESM no lleva SRI. README:110 lo acepta;
   - el visor asume `top-left`.

## Explicación (JM)
Por cada AC, en 3 a 5 líneas: qué líneas lo cumplen y por qué. Respuestas a 3 preguntas de entrevistador.
Firmada solo cuando Jeison puede explicarlo sin mirar.
