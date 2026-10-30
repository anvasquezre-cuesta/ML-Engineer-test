# 08b - CI (GitHub Actions)

**Objetivo:** que cada push y cada PR corran lint, formato y tests en una máquina limpia, para que el verde no dependa del equipo de Jeison.

**Fuera de alcance:**
- tests de RAG con modelos o LLM (se saltan solos: MiniLM no está en caché y no hay Ollama);
- Docker, publicación, cobertura con umbral, matriz de sistemas operativos o de versiones de Python.

**Contrato:** `.github/workflows/ci.yml`, con un job:
- `on: [push, pull_request]`; `permissions: contents: read`; `concurrency` con `group: ${{ github.workflow }}-${{ github.ref }}` y `cancel-in-progress: true`;
- `runs-on: ubuntu-24.04` fijo, no `latest`, para que la versión de Tesseract no cambie sin aviso; `timeout-minutes: 20`;
- `actions/checkout` y `astral-sh/setup-uv` fijados por SHA de commit, con comentario de versión, a releases de ≥ 2 semanas (GitHub recomienda fijar por SHA);
- pasos:
  1. `sudo apt-get update && sudo apt-get install -y tesseract-ocr` (en Ubuntu trae `eng` como dependencia);
  2. `tesseract --version`, para que la versión quede en el log;
  3. `uv sync --locked --extra dev`;
  4. `uv run ruff check .`;
  5. `uv run ruff format --check .`;
  6. `uv run pytest -rs -v`, para que el log liste cada test ejecutado y el motivo de cada skip.

Python sale de `.python-version`, y `--locked` falla si `uv.lock` no coincide con `pyproject.toml`.

Fuentes: `tasks/08-bonus/reviews/2026-10-30-ci-research.md`.

**Datos de prueba:** la rama tal como está. Esperado: unitarios en verde; `test_ocr_boxes` y `test_extract_e2e` corren con Tesseract 5.3.4; `test_rag_*` se saltan.

## Criterios de aceptación
- **AC-CI-01** Given un push al fork de JM, When corre el workflow, Then:
  - el job termina en verde;
  - el log muestra los tests de OCR y extract e2e ejecutados (no saltados) y los de RAG saltados.

  _Test: e2e (ejecución en GitHub)_
- **AC-CI-02** Given el YAML, When se lee, Then:
  - toda action va fijada por SHA de 40 caracteres, con comentario de versión;
  - hay `permissions: contents: read`;
  - el runner es fijo.

  _Test: revisión (code-critic)_

**Riesgo conocido:** en local se usa Tesseract 5.4 y en CI la 5.3.4. `test_extract_e2e` compara nombres exactos. Si falla en CI, se investiga la diferencia de OCR. El test no se afloja de antemano.

## Tareas (máx. 6)
1. JM crea su fork en GitHub y añade el remoto (Claude no ejecuta git de escritura).
2. `ci.yml` con los SHA verificados.
3. Push de JM y revisión del log (AC-CI-01).
4. `RUNNING.md`: una línea sobre el CI.

## Explicación (JM)
Por cada AC, en 3 a 5 líneas: qué líneas lo cumplen y por qué. Respuestas a 3 preguntas de entrevistador.
Firmada solo cuando Jeison puede explicarlo sin mirar.
