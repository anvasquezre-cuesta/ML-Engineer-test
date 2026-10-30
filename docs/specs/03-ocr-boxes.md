# 03 - OCR y cajas en puntos PDF

**Objetivo:** OCR de todas las páginas de un PDF escaneado, con palabras en puntos PDF, y una caja por cada mención de persona (unión de sus palabras OCR), detrás de un Protocol `OcrEngine`.
**Fuera de alcance:**
- validación del upload (tamaño, magic `%PDF-`, cifrado), router, lifespan y mapeo a HTTP (spec 04);
- fuzzy matching (spec 01, cerrada) y RAG;
- recortar la puntuación pegada a la palabra de borde (D-OCR-4: se acepta y se documenta);
- un nombre que cruza renglones (D-OCR-2: NER ya lo descarta, `ner_service.py:32`; 0 de 54 en las muestras).

**Contrato** (`schemas.py` no se cambia; `BoundingBox` va en puntos, `page_number` 0-based):
- `app/services/ocr_service.py`:
  - `Word = dict`: `{"word", "page", "x", "y", "width", "height", "line"}`, en puntos; `line = (block, par, line)` de Tesseract.
  - `class OcrEngine(Protocol)`: `__call__(self, image: Image.Image) -> dict[str, list]`. Devuelve las columnas de `pytesseract.image_to_data(..., output_type=Output.DICT)` (`text`, `conf`, `left`, `top`, `width`, `height`, `block_num`, `par_num`, `line_num`), en píxeles.
  - `tesseract_data(image)`: el engine por defecto, con `ocr_lang`, `ocr_psm` y `ocr_timeout_s` de la config.
  - `class InvalidPdfError(ValueError)`: bytes vacíos, que no son PDF, o con cabecera `%PDF-` pero corruptos (este último caso no lo ataja el chequeo de magic de 04). Envuelve `pymupdf.FileDataError` (incluye `EmptyFileError`), para que 04 la mapee sin importar pymupdf. El `RuntimeError` del timeout de Tesseract se propaga; el mapeo a HTTP es de 04.
  - `ocr_pages(pdf_bytes: bytes, engine: OcrEngine | None = None) -> list[list[Word]]`: abre el PDF **una vez** con `with pymupdf.open(stream=pdf_bytes, filetype="pdf")`, renderiza cada página a `ocr_dpi` en gris y devuelve una lista de palabras por página, incluida la 0. Escala `page.rect.width / pix.width` (a 300 DPI, 0.24). Descarta `conf < 0` y texto vacío tras `strip()`. Con `bbox_origin == "bottom-left"`, `y = page.rect.height - y - height`.
  - `page_text(words: list[Word]) -> tuple[str, list[Word]]`: el texto de una página y copias de las palabras con `start` y `end` (`{**w, "start": ..., "end": ...}`). Palabras y offsets viajan juntos, así no se desalinean. Palabras unidas con `" "` dentro del mismo `line` y con `"\n"` entre renglones (`proto/ocr.py:66-89`).
  - Stubs (R1), que leen `Path(pdf_path).read_bytes()` y delegan:
    - `extract_text_from_pdf(pdf_path) -> str`: los textos de página unidos con `"\n\n"`;
    - `get_word_bounding_boxes(pdf_path) -> list[dict]`: todas las palabras, en orden de página.
- `app/services/bbox_service.py`:
  - `boxes_for_spans(words: list[Word], spans: list[Span]) -> list[dict]`: `words` son las de `page_text`, con `start` y `end`. Por cada span, la caja unión de las palabras cuyo `(start, end)` lo toca (`start < span_end and end > span_start`). Devuelve `{"name", "page", "x", "y", "width", "height"}`, en el orden de los spans.
  - `locate_names(pages: list[list[Word]]) -> list[dict]`: arma `page_text` por página, hace **una sola** llamada a `find_person_spans` (spec 02) con los textos de todas las páginas, para que funcione la propagación entre páginas (`ner_service.py:45-55`), y concatena `boxes_for_spans` por página. Es lo que usará el endpoint (spec 04).
  - Stub `find_name_bounding_boxes(pdf_path, text) -> list[dict]` (R1): `locate_names(ocr_pages(Path(pdf_path).read_bytes()))`. `text` no se usa: los offsets tienen que salir del OCR del mismo PDF (lo dice el docstring).
- `app/config.py`: `bbox_origin: Literal["top-left", "bottom-left"] = "top-left"` (variable `BBOX_ORIGIN`, R10).

**Por qué así:**
- **Bytes y una sola apertura (D-OCR-1, R6):** el upload llega en memoria, así que no hacen falta archivos temporales. Abrir por path o por `stream` da el mismo render (md5 idéntico) y el mismo `page.rect`. El proto abría el PDF 1+N veces (`proto/ocr.py:20,56`).
- **`filetype="pdf"` y `doc.is_pdf`:** pymupdf abre un PNG como documento de imagen aunque se pase `filetype="pdf"` (medido en la implementación), así que `ocr_pages` comprueba `doc.is_pdf` y lanza `InvalidPdfError`.
- **Cajas por offsets, no por búsqueda de cadenas (D-OCR-6):** el span NER y las palabras comparten el mismo texto de página, así que no hay comparación que falle por mayúsculas o por ruido OCR. Ese requisito del README (README:92-94) es de name matching y lo cubre el fuzzy.
- **Volteo por palabra (D-OCR-3):** `y = H - y - h` es monótono, así que el min/max de la unión no cambia.
- **Sin pandas en `app/`:** listas de dicts.

**Datos de prueba:**
- **Unitarios:** un PDF en blanco de N páginas creado en memoria con pymupdf, más un engine falso que devuelve columnas fijas en píxeles. No usan Tesseract.
- **E1 (integración):** un PDF "escaneado" generado en memoria. Se inserta "Signed by Maria Gonzalez today" en (72, 200) con `helv`, se rasteriza a 150 DPI en gris y se crea un PDF solo-imagen. La caja esperada es `page.search_for("Maria Gonzalez")[0]` sobre el original. El span se arma sobre el texto OCR: `(n, text.index(n), text.index(n) + len(n))`. Si el OCR lee mal el nombre, el test falla con un mensaje claro.
- **E2E (integración):** las 3 muestras contra `eval/gold_names.csv` y `eval/gold_boxes.csv` (55 cajas: 54 del proto, revisadas sobre las imágenes en 02a, más Lucas Zimmermann, armada con sus 2 palabras OCR).
- Integración y e2e se saltan si no hay Tesseract (`shutil.which("tesseract") is None`).

## Criterios de aceptación
En los unitarios, `fake` es un engine falso y la config se controla con `monkeypatch` de `get_settings` a `Settings(_env_file=None, ...)`.

- **AC-OCR-01** Given un PDF Letter en blanco, `ocr_dpi=150` por config y un fake que devuelve una palabra con `left=100, top=200, width=50, height=25` px en `(1, 1, 1)`, When se llama a `ocr_pages(pdf, fake)`, Then la palabra es `{"word": ..., "page": 0, "x": 48.0, "y": 96.0, "width": 24.0, "height": 12.0, "line": (1, 1, 1)}` (escala 612/1275 = 0.48). Se usa 150 y no 300 para que falle un DPI fijo en el código. _Test: unitario_
- **AC-OCR-02** Given un PDF de 2 páginas y un fake que devuelve una palabra por llamada, When se llama a `ocr_pages`, Then hay 2 listas, con `page` 0 y 1, y el fake se llamó 2 veces. _Test: unitario_
- **AC-OCR-03** Given un fake con `conf = -1`, con texto `"  "` y con una palabra válida, When se llama a `ocr_pages`, Then solo queda la palabra válida. _Test: unitario_
- **AC-OCR-04** Given un fake con "Ann" y "Lee" en `(1, 1, 1)` y "Bob" en `(2, 1, 1)` (otro bloque, mismo `line_num`), When se llama a `page_text(ocr_pages(pdf, fake)[0])`, Then el texto es `"Ann Lee\nBob"` y los offsets son `(0, 3), (4, 7), (8, 11)`. Falla si el renglón se agrupa solo por `line_num`. _Test: unitario_
- **AC-OCR-05** Given `b""`, `b"not a pdf"`, `b"%PDF-1.4\n%garbage"` y los bytes de un PNG, When se llama a `ocr_pages`, Then se lanza `InvalidPdfError`. _Test: unitario_
- **AC-OCR-06** Given `bbox_origin="bottom-left"` y el fake de AC-OCR-01, When se llama a `ocr_pages`, Then `y == 792 - 96.0 - 12.0`. _Test: unitario_
- **AC-BOX-01** Given "Ann" (`x=10, width=20, y=5, height=10`) y "Lee" (`x=35, width=15, y=7, height=10`) en la página 1, con offsets (0, 3) y (4, 7), y el span ("Ann Lee", 0, 7), When se llama a `boxes_for_spans`, Then sale `{"name": "Ann Lee", "page": 1, "x": 10, "y": 5, "width": 40, "height": 12}`. Falla si se toma la altura de la última palabra. _Test: unitario_
- **AC-BOX-02** Given la palabra OCR "Thompson," y el span "Margaret Thompson", que termina antes de la coma, When se llama a `boxes_for_spans`, Then el `width` llega hasta el borde derecho de la palabra "Thompson,", con la coma incluida. _Test: unitario_
- **AC-BOX-03** Given 2 spans del mismo nombre en una página, When se llama a `boxes_for_spans`, Then salen 2 cajas distintas, una por ocurrencia, y ninguna une palabras de los dos sitios. _Test: unitario_
- **AC-BOX-04** Given el PDF sintético E1 (fuentes 11, 14 y 24), When se llama a `ocr_pages`, `page_text` y `boxes_for_spans` con el span de "Maria Gonzalez", Then la caja queda dentro de la caja esperada con ±1 pt y su ancho es ≥ 0.95 del esperado. _Test: integración_
- **AC-BOX-05** Given las 3 muestras, When se llama a `locate_names(ocr_pages(bytes))`, Then, contra `gold_names.csv` (multiconjunto de `(pdf, page, name)`), la precisión es 1.0 y el recall ≥ 54/55. Además, para cada caja hallada existe una fila de `gold_boxes.csv` con el mismo `(pdf, page, name)` a ±2 pt en x, y, width y height. Una caja que mezcle dos ocurrencias se sale de ±2 pt, y los duplicados los atrapa la precisión. Tarda unos 4 s (5 páginas de OCR, medido). _Test: e2e_
- **AC-BOX-06** Given 2 páginas con "Ann Lee" y un `find_person_spans` falso que registra sus llamadas, When se llama a `locate_names`, Then hay una sola llamada, con los textos de las 2 páginas, y salen cajas en las páginas 0 y 1. Falla si el NER se llama por página (rompería la propagación entre páginas). _Test: unitario_
- **AC-CFG-04** Given `Settings(_env_file=None)`, Then `bbox_origin == "top-left"`. _Test: unitario_

## Tareas (máx. 6)
1. `eval/gold_boxes.csv` (referencia del e2e) en su propio commit.
2. `bbox_origin` en `app/config.py` y `.env.example`, con AC-CFG-04.
3. Escribir en rojo los tests AC-OCR-01..06 (`tests/unit/test_ocr_service.py`) y AC-BOX-01..03 (`tests/unit/test_bbox_service.py`); AC-BOX-04 y 05 en `tests/integration/`.
4. Pasar `proto/ocr.py` (`render_page`, `ocr_page`, `ocr_pdf`, `add_offsets`) a `ocr_service.py` sin pandas, con una sola apertura.
5. Pasar `proto/ner.py` (`name_box`, `locate_names`) a `bbox_service.py`.
6. Dejar `verify.ps1` en verde y hacer "Desde `app/`" en NB01 y 02a: palabras y cajas iguales a `01_ocr_words.csv` y `02a_name_boxes.csv`.

## Explicación (JM)
_Por cada AC, en 3 a 5 líneas: qué líneas lo cumplen y por qué. Respuestas a 3 preguntas de entrevistador. Se firma solo cuando Jeison puede explicarlo sin mirar._

_Está en el notebook local de la tarea (`notebooks/02a_ner_cajas.ipynb`, sección «Explicación de los AC de la spec 03»), que no llega al repo. Jeison la estudia allí, junto a las celdas que muestran cada número._
