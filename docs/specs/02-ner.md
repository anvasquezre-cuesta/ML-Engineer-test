# 02 - NER de personas

**Objetivo:** extraer los nombres de persona de cada página como spans `(name, start, end)`, con los filtros del prototipo y la propagación D4, detrás de un Protocol `NameRecognizer`.
**Fuera de alcance:**
- OCR y cajas (spec 03), que consumen los spans;
- router, lifespan e inyección en FastAPI (spec 04);
- modelo ausente: hoy daría `OSError`; lo resuelve el lifespan (spec 04);
- otros idiomas y segundos nombres;
- solapes parciales entre un span propagado y uno de spaCy (0 casos en las muestras; `proto/ner.py:88-89`).

**Contrato** (`app/services/ner_service.py`; `schemas.py` no se cambia):
- `Span = tuple[str, int, int]`: `(name, start, end)` sobre el texto de **una** página, con `text[start:end] == name`. La spec 03 lo usa en sus tipos.
- `class NameRecognizer(Protocol)`: `__call__(self, text: str) -> list[Span]`. Devuelve los PERSON sin filtrar.
- `spacy_persons(text: str) -> list[Span]`: el recognizer por defecto. Usa `_load_model(get_settings().ner_model)`, donde `_load_model(name: str)` lleva `@lru_cache`. La carga es perezosa (importar el módulo no carga spaCy) y la caché va por nombre de modelo.
- `find_person_spans(pages: list[str], recognizer: NameRecognizer | None = None) -> list[list[Span]]`:
  - una lista de spans por página, ordenada por `(start, end)`;
  - con `None` usa `spacy_persons`, que se resuelve en cada llamada;
  - `get_settings()` se lee dentro de la función, no al importar.
- `extract_names(text: str) -> list[str]`: el envoltorio que conserva la firma del stub (R1). Trata `text` como una sola página y devuelve los nombres únicos en orden de aparición.
- `app/config.py`:
  - `ner_model: str = "en_core_web_sm"` (variable `NER_MODEL`);
  - `ner_drop_all_caps: bool = True` (variable `NER_DROP_ALL_CAPS`, R3).

**Por qué por páginas y no un solo texto:**
- Los offsets que necesitan las cajas son por página (`notebooks/proto/ocr.py:66-89`).
- D4 propaga a todo el documento los nombres hallados en cualquier página (`research/17:74`).
- `extract_names(text)` se conserva por R1, pero el endpoint (spec 04) toma los nombres de los spans.

**Datos de prueba:**
- unitarios: cadenas cortas y un recognizer falso (una lambda o un dict por página);
- integración: una frase con PERSON, ORG, GPE y DATE;
- regresión: las 3 muestras contra `eval/gold_names.csv` (P 1.0, R 54/55), igual que `notebooks/02c_evaluacion.ipynb`.

## Reglas (decisiones D-NER-1..4, `tasks/02-ner/reviews/2026-10-29-decisions-critic.md`)
- **Filtros (`_is_name`, `proto/ner.py:22`):** un span se descarta si se cumple cualquiera de estas condiciones:
  1. contiene `"\n"` (cruza renglón);
  2. no contiene `" "` (una sola palabra);
  3. `name.isupper()`, solo si `ner_drop_all_caps` es verdadero.
- **Propagación (D4, `_propagate`, `proto/ner.py:85-100`):**
  - los nombres reunidos de todas las páginas, ya filtrados, se buscan en cada página como coincidencia exacta (distingue mayúsculas) con borde de palabra `(?<!\w)…(?!\w)`;
  - se deduplica con `dict.fromkeys` sobre las tuplas y se ordena por `(start, end)`. Como `text[start:end] == name`, dos spans con el mismo `(start, end)` son la misma tupla. Se usa `dict.fromkeys` y no `set` porque conserva el orden de inserción: así, si alguien quita el `sorted`, AC-NER-06 falla siempre y no según el hash (medido: con `set`, la mutación sobrevivía en 25 de 200 semillas).
- **Sin pandas en `app/`:** pandas solo está en el grupo `notebooks`. Tampoco va la columna `source`.

## Criterios de aceptación
En los unitarios, `fake` es un recognizer falso. La config se controla con `monkeypatch` de `ner_service.get_settings` a `Settings(_env_file=None, ...)`.

- **AC-NER-01** Given el modelo real, When se llama a `extract_names("Maria Gonzalez met Acme Corp in Paris on Monday.")`, Then devuelve `["Maria Gonzalez"]`, sin ORG, GPE ni DATE. _Test: integración_
- **AC-NER-02** Given un fake que devuelve "Robert\nChen", "Chen" y "JOHN SMITH", con la config por defecto, When se llama a `find_person_spans(pages, fake)`, Then los tres se descartan. _Test: unitario_
- **AC-NER-03** Given "Robert Chen" hallado por el fake solo en la página 0 y presente dos veces en la página 1, When se llama a `find_person_spans(pages, fake)`, Then la página 1 tiene 2 spans de "Robert Chen", uno por aparición. _Test: unitario_
- **AC-NER-04** Given "Ann Lee" hallado y la página "Ann Lee met Ann Leeds and LeeAnn Lee", When se llama a `find_person_spans(pages, fake)`, Then sale un solo span: "Ann Leeds" y "LeeAnn Lee" no cuentan (prueba los dos bordes). Ningún `(start, end)` se repite aunque el fake y la propagación encuentren el mismo. _Test: unitario_
- **AC-NER-05** Given `ner_drop_all_caps=False` y un fake que devuelve "JOHN SMITH", When se llama a `find_person_spans(pages, fake)`, Then el span se conserva. _Test: unitario_
- **AC-NER-06** Given `pages=["Ann Lee met Bob Ray", "Bob Ray met Ann Lee"]` y un fake que devuelve solo `("Bob Ray", 12, 19)` en la página 0 y `("Ann Lee", 12, 19)` en la página 1, When se llama a `find_person_spans(pages, fake)`, Then la página 0 es `[("Ann Lee", 0, 7), ("Bob Ray", 12, 19)]`: el span propagado va antes que el del fake, así que solo pasa si se ordena por `start` y cada span cumple `pages[i][start:end] == name`. _Test: unitario_
- **AC-NER-07** Given un fake parcheado en `ner_service.spacy_persons`, When se llama a `extract_names` con un texto que repite un nombre, Then devuelve nombres únicos en orden de aparición. Además, `extract_names("") == []` y `find_person_spans([]) == []`. _Test: unitario_
- **AC-CFG-03** Given `Settings(_env_file=None)`, Then `ner_model == "en_core_web_sm"` y `ner_drop_all_caps is True`. Va en `tests/unit/test_config.py`. _Test: unitario_

## Tareas (máx. 6)
1. Agregar `ner_model` y `ner_drop_all_caps` en `app/config.py` y `.env.example`, con su test AC-CFG-03.
2. Escribir los tests AC-NER-02..07 en `tests/unit/test_ner_service.py` y AC-NER-01 en `tests/integration/test_ner_spacy.py`, en rojo.
3. Pasar `notebooks/proto/ner.py` a `app/services/ner_service.py` sin pandas:
   - `person_spans` pasa a `spacy_persons`;
   - `filter_persons` pasa a `_is_name`;
   - `propagate_names` pasa a `_propagate`.
4. Dejar `verify.ps1` en verde. Regresión del assistant sobre las 3 muestras: P 1.0 y R 54/55.
5. Sección "Desde `app/`" en 02a/02c.

## Explicación (JM)
_Por cada AC, en 3 a 5 líneas: qué líneas lo cumplen y por qué. Respuestas a 3 preguntas de entrevistador. Se firma solo cuando Jeison puede explicarlo sin mirar._

_Redactada por Claude y revisada por Jeison. Las líneas son de `app/services/ner_service.py` (commit 1784712, 60 líneas). Firmada por Jeison Mesa, 2026-10-29._

- **AC-NER-01** (solo PERSON): la línea 27 se queda solo con `e.label_ == "PERSON"`. Así, "Acme Corp" (ORG), "Paris" (GPE) y "Monday" (DATE) no salen. `extract_names` (línea 60) devuelve los nombres. Es el único test con el modelo real.
- **AC-NER-02** (filtros): `_is_name`, en la línea 32, descarta un span si tiene `"\n"` (cruza renglón), si no tiene `" "` (una sola palabra) o si está en MAYÚSCULAS. `"Robert Chen\nCFO"` tiene espacio, así que solo lo descarta el filtro de renglón, y por eso el test detecta si alguien quita ese filtro.
- **AC-NER-03** (propagación): la línea 54 reúne los nombres hallados en todas las páginas. La 55 llama a `_propagate` en cada página, y la 40 busca cada nombre con `re.finditer`. Por eso "Robert Chen" aparece 2 veces en la página 1, aunque el fake no lo devuelva ahí.
- **AC-NER-04** (bordes y duplicados): `(?<!\w)` y `(?!\w)`, en la línea 40, exigen que antes y después del nombre no haya una letra. "Ann Leeds" y "LeeAnn Lee" quedan fuera. `dict.fromkeys`, en la línea 42, deja una sola vez el `(0, 7)` que devuelven tanto el fake como la regex.
- **AC-NER-05** (config): la línea 50 lee `get_settings().ner_drop_all_caps` dentro de la función. Con `False`, la condición `not (drop_all_caps and ...)` de la línea 32 siempre es verdadera y "JOHN SMITH" se conserva. El valor vive en `app/config.py:20` (`NER_DROP_ALL_CAPS`).
- **AC-NER-06** (orden y offsets): la línea 42 ordena por `(start, end)`. El span propagado `("Ann Lee", 0, 7)` va antes que el del fake, así que el test solo pasa si se ordena. Como `dict.fromkeys` conserva el orden de inserción, sin `sorted` falla siempre, no según el hash. `text[start:end] == name` se cumple porque la regex y spaCy dan offsets sobre el mismo texto.
- **AC-NER-07** (`extract_names` y vacíos):
  - en la línea 49, `recognizer or spacy_persons` se resuelve en cada llamada, así que el test puede reemplazar `spacy_persons`;
  - en la línea 60, `dict.fromkeys` deja los nombres únicos en orden de aparición;
  - con `[]` no hay páginas y la salida es `[]`.
- **AC-CFG-03**: `app/config.py:19-20` da los valores por defecto `en_core_web_sm` y `True`.

**Preguntas de entrevistador**
1. *¿Por qué el stub recibe un texto y tú trabajas por páginas?* Las cajas necesitan offsets dentro de cada página, y la propagación busca en todas las páginas los nombres de todo el documento. `extract_names` conserva la firma del stub (R1).
2. *¿Cómo pruebas sin cargar spaCy?* El Protocol `NameRecognizer` (líneas 14-15) permite pasar un `dict.get` como recognizer. El modelo se carga recién en la primera llamada (`_load_model` con `@lru_cache`, líneas 18-21).
3. *¿Cómo sabes que `app/` hace lo mismo que el notebook?* Con spaCy real sobre las 3 muestras, el multiconjunto de `(pdf, page, name, start, end)` es idéntico al del proto (sobra 0, falta 0). Da P 1.0 y R 54/55. Está en 02a y 02c, sección "Desde `app/`".
