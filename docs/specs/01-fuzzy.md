# 01 - Fuzzy match de nombres

**Objetivo:** implementar `fuzzy_match_names` para comparar los nombres extraídos con los pedidos en `names`, con un umbral configurable.
**Fuera de alcance:**
- el router y el parseo del JSON `names` (spec 04);
- NER y OCR (specs 02 y 03);
- lógica de iniciales y segundos nombres (decisión F6: es un límite documentado).

**Contrato:**
- `app/services/fuzzy_service.py`:
  - `fuzzy_match_names(extracted_names: list[str], query_names: list[dict], threshold: float | None = None) -> list[dict]`;
  - devuelve `{"extracted_name", "matched_name", "score"}`, con las mismas claves que `FuzzyMatch` en `app/models/schemas.py`, que no se cambia;
  - es la única función pública; la normalización es privada (`_normalize`).
- `app/config.py`: `fuzzy_threshold: float = Field(0.90, ge=0.0, le=1.0)`, que se puede cambiar con la variable `FUZZY_THRESHOLD`.

**Por qué `threshold: float | None = None`:**
- R1 (`research/14-revision-plan.md:13`) pide conservar la firma de 2 argumentos, por si hay tests ocultos.
- El literal `= 0.90` sería un valor fijo en el código, y README:81 lo prohíbe.
- `= get_settings().fuzzy_threshold` se evaluaría al importar el módulo.
- La salida es `None`, que se resuelve dentro de la función con `get_settings().fuzzy_threshold`. El router (spec 04) pasa `settings.fuzzy_threshold` de forma explícita: la dependencia va inyectada, y el valor por defecto solo cubre las llamadas de 2 argumentos.

**Datos de prueba:** cadenas cortas en los tests. Los valores esperados son los que validó `notebooks/03_fuzzy.ipynb` (oro de pares: `eval/gold_fuzzy_pairs.csv`).

## Reglas (decisiones F1-F5, `research/17-nb03-fuzzy-research.md`)
- **Normalización (F3):**
  1. `casefold`;
  2. NFKD;
  3. quitar las marcas combinantes;
  4. borrar los apóstrofos (`'` y `’`);
  5. convertir en espacio todo lo que no sea `\w`;
  6. quitar los títulos {dr, mr, mrs, ms, miss, prof};
  7. colapsar los espacios.
- **Score (F2):** `max(fuzz.ratio, fuzz.token_sort_ratio) / 100` sobre las claves ya normalizadas. No se usan `partial_ratio`, `token_set_ratio` ni `WRatio` (README:93-94).
- **Qué se devuelve (F1, F4):**
  - todos los pares con `score >= threshold`, sobre el score crudo;
  - en la salida, `round(score, 4)`;
  - orden: score descendente, luego `extracted_name` y luego `matched_name`;
  - `matched_name = f"{first_name} {last_name}"`.
- **Dedupe (F5):** los extraídos y los pedidos se deduplican por clave normalizada, conservando la primera aparición original. Una clave vacía se descarta, porque `fuzz.ratio("", "")` da 100.

## Criterios de aceptación
- **AC-FUZ-01** Given el extraído "María González" y el pedido Maria/Gonzalez (ejemplo literal de README:93), When se comparan, Then el score es 1.0. _Test: unitario_
- **AC-FUZ-02** Given "Maria" y Maria/Gonzalez, Then no hay match: un nombre a medias no pasa (`partial_ratio` daría 100). _Test: unitario_
- **AC-FUZ-03** Given "Catherlne Dubois" (un carácter de ruido OCR) y Catherine/Dubois, Then hay match (0.9375). _Test: unitario_
- **AC-FUZ-04** Given "Gonzalez Maria" y Maria/Gonzalez, Then el score es 1.0 (orden invertido). _Test: unitario_
- **AC-FUZ-05** Given "Robert Chen" y James/Chen, Then no hay match (mismo apellido, otra persona). _Test: unitario_
- **AC-FUZ-06a** Given un par que pasa con 0.90, When se llama con `threshold=0.99`, Then no sale. _Test: unitario_
- **AC-FUZ-06b** Given `get_settings().fuzzy_threshold` por defecto (0.90), When se llama sin `threshold`, Then se usa ese valor. Que el entorno lo cambia ya lo prueba AC-CFG-01. _Test: unitario_
- **AC-FUZ-07** Given varios matches, Then cada score tiene 4 decimales como máximo y la lista va en orden descendente con los desempates de F4. _Test: unitario_
- **AC-FUZ-08** Given los extraídos ["Ana Ruiz", "ana  ruiz"] y los pedidos Ana/Ruiz y ANA/RUIZ, Then sale un solo par `{"Ana Ruiz", "Ana Ruiz", 1.0}` (primera aparición). _Test: unitario_
- **AC-FUZ-09** Given extraídos o pedidos vacíos, Then la salida es `[]`. _Test: unitario_
- **AC-FUZ-10** Given un match, Then sus claves son las de `FuzzyMatch` y `FuzzyMatch(**m)` valida, lo que cubre también el rango [0, 1]. _Test: unitario_
- **AC-FUZ-11** Given "Dr. Robert Chen" y Robert/Chen, Then el score es 1.0 (se quita el título). _Test: unitario_
- **AC-FUZ-12** Given "abcd efghi" y abcd/efghk (indel 2 sobre 20 caracteres, es decir 0.90 exacto) con threshold 0.90, Then el par se reporta (`>=`). _Test: unitario_
- **AC-FUZ-13** Given el extraído "Dr." y el pedido "."/"-" (los dos quedan vacíos al normalizar), Then la salida es `[]`. _Test: unitario_
- **AC-CFG-02** Given `FUZZY_THRESHOLD=1.5`, When se crea `Settings(_env_file=None)`, Then lanza `ValidationError`. Va en `tests/unit/test_config.py`. _Test: unitario_

## Tareas (máx. 6)
1. Agregar `fuzzy_threshold` en `app/config.py`, con su test AC-CFG-02.
2. Escribir los tests AC-FUZ-01..13 en `tests/unit/test_fuzzy_service.py`, en rojo.
3. Pasar `notebooks/proto/fuzzy.py` a `app/services/fuzzy_service.py`:
   - `_normalize` queda privada;
   - el score se calcula dentro del bucle sobre las claves ya normalizadas, sin `name_score`.
4. Dejar `verify.ps1` en verde.

## Explicación (JM)
_Por cada AC, en 3 a 5 líneas: qué líneas lo cumplen y por qué. Respuestas a 3 preguntas de entrevistador. Se firma solo cuando Jeison puede explicarlo sin mirar._

_Redactada por Claude y revisada por Jeison. Las líneas son de `app/services/fuzzy_service.py` (commit 3f6e372). Firmada por Jeison Mesa, 2026-10-29._

- **AC-FUZ-01** (acentos y mayúsculas): en `_normalize`, la línea 15 pasa a minúsculas con `casefold` y separa cada letra de su acento con NFKD; la 16 borra las marcas combinantes. "María González" y "Maria Gonzalez" dan la misma clave, así que el score es 1.0.
- **AC-FUZ-02** (nombre a medias): en la línea 46, `fuzz.ratio` compara las cadenas completas: "maria" contra "maria gonzalez" da 52.6. No se usan `partial_ratio` ni `token_set_ratio`, que darían 100.
- **AC-FUZ-03** (ruido OCR): también la línea 46. Indel cuenta las inserciones y los borrados, así que una letra cambiada cuesta 2 sobre 32 caracteres: 1 − 2/32 = 0.9375.
- **AC-FUZ-04** (orden invertido): `token_sort_ratio`, en la línea 46, ordena las palabras antes de comparar. El `max` se queda con el mejor de los dos scores.
- **AC-FUZ-05** (mismo apellido, otra persona): Robert contra James Chen da 0.571, bajo el umbral, y la línea 48 lo descarta.
- **AC-FUZ-06a/b** (umbral): las líneas 40-41 usan el valor explícito, o `get_settings().fuzzy_threshold` si llega `None`. El valor está en `app/config.py` con `Field(ge=0, le=1)` y lo cambia `FUZZY_THRESHOLD`.
- **AC-FUZ-07** (orden y decimales): la línea 49 redondea a 4 decimales solo la salida. La 50 ordena por score descendente y desempata por `extracted_name` y luego por `matched_name`.
- **AC-FUZ-08** (dedupe): `_by_key`, en las líneas 22-28, guarda la primera aparición de cada clave normalizada (`setdefault` no sobrescribe). Se aplica a los dos lados (líneas 42 y 44).
- **AC-FUZ-09** (vacíos): con una lista vacía uno de los bucles no itera, `hits` queda en `[]` y se devuelve `[]`.
- **AC-FUZ-10** (schema): la línea 51 arma los dicts con las claves exactas de `FuzzyMatch`, y el score queda en [0, 1].
- **AC-FUZ-11** (título): la línea 19 quita {dr, mr, ...} después de que la 18 pase "dr." a "dr".
- **AC-FUZ-12** (borde 0.90): la línea 48 usa `>=`, y 1 − 2/20 da exactamente 0.9, así que el par se reporta.
- **AC-FUZ-13** (clave vacía): en la línea 26, `if key :=` descarta las claves vacías, porque `fuzz.ratio("", "")` daría 100.
- **AC-CFG-02**: `Field(ge=0.0, le=1.0)` hace que `FUZZY_THRESHOLD=1.5` lance `ValidationError` al crear `Settings`.

**Preguntas de entrevistador**
1. *¿Por qué no `WRatio`, que es el default de rapidfuzz?* Porque combina `partial_ratio` y `token_set_ratio`, que inflan los nombres a medias, y el README pide similitud de cadena completa.
2. *¿Por qué filtras antes de redondear?* El umbral se aplica al valor medido y el redondeo es solo presentación. Con nombres reales no cambia ningún resultado: el mayor score por debajo de 0.90 es 0.8983.
3. *¿Qué falla y qué harías en producción?* Las iniciales, los segundos nombres y 2 o más errores de OCR quedan como falsos negativos. Los nombres a una letra de otro (Mario/Maria) son falsos positivos, y lo ve quien revisa la caja. En producción mediría el umbral con datos reales etiquetados, porque estas cifras salen de resubstitución.
