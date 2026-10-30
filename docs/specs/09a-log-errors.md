# 09a - Log de peticiones que fallan sin control

**Objetivo:** que una petición que termina en una excepción no controlada (500) también deje su línea de log JSON con `request_id`, `status` y `ms`.

**Fuera de alcance:**
- cambiar las respuestas: el 500 lo sigue devolviendo FastAPI;
- registrar la traza o el mensaje de la excepción (puede contener nombres, que son PII);
- tocar los errores de dominio de `main.py` (ya tienen su estado y su línea de log).

**Contrato:** `app/log.py`, `log_requests`. Sin cambios en `schemas.py` ni en los endpoints.
**Datos de prueba:** un `OcrEngine` falso que lanza `RuntimeError`; `TestClient(app, raise_server_exceptions=False)`.

## Criterios de aceptación
- **AC-LOG-02** Given un motor OCR que lanza `RuntimeError`, When `POST /api/extract` con `X-Request-ID: boom`, Then la respuesta es 500 y hay una línea de log con `request_id` `boom`, `status` 500 y `ms`. _Test: unitario (TestClient)_
- **AC-LOG-03** Given el mismo caso, Then la excepción no se silencia: con `raise_server_exceptions=True` el `RuntimeError` llega al test. _Test: unitario_

## Tareas
1. Tests en rojo en `tests/unit/test_extract_api.py`.
2. En `log_requests`: `status = 500` por defecto, y el `log_event` dentro de `finally`, sin `except`.

## Explicación (JM)
En `tasks/09-final-eval/explicacion-ac.md`.
