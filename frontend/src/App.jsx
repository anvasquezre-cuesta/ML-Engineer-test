import {useEffect, useRef, useState} from "react";
import * as pdfjs from "pdfjs-dist";
import workerUrl from "pdfjs-dist/build/pdf.worker.min.mjs?url";
import {displayBox} from "./geometry.js";

pdfjs.GlobalWorkerOptions.workerSrc = workerUrl;

const labels = {ocr: "OCR", ner: "NER", recovery_1: "Recuperación 1",
  recovery_2: "Recuperación 2", recovery_3: "Recuperación 3", final: "Resultado final"};
const defaultMessage = "Selecciona un PDF para comenzar.";

function disposePdf(task) {
  if (task) task.destroy().catch(() => {});
}

function errorMessage(status) {
  if (status === 400) return "El PDF no es válido o no es compatible.";
  if (status === 408 || status === 504) return "El procesamiento agotó el tiempo disponible.";
  if (status === 413) return "El documento o los nombres superan un límite del servicio.";
  if (status === 422) return "La solicitud o los nombres no son válidos.";
  if (status === 503) return "El servicio está ocupado o no está disponible.";
  return "No se pudo procesar la solicitud. Comprueba que la API esté disponible.";
}

function parseNames(value) {
  const names = JSON.parse(value.trim() || "[]");
  if (!Array.isArray(names) || names.some((item) => !item || Array.isArray(item) ||
      typeof item.first_name !== "string" || !item.first_name.trim() ||
      typeof item.last_name !== "string" || !item.last_name.trim())) throw new Error("invalid names");
  return names;
}

// Compare the public response fields, not JSON property ordering.
function sameResponse(first, second) {
  if (!Array.isArray(second?.extracted_names) || !Array.isArray(second?.fuzzy_matches) ||
      first.extracted_names.length !== second.extracted_names.length ||
      first.fuzzy_matches.length !== second.fuzzy_matches.length) return false;
  const namesEqual = first.extracted_names.every((item, index) => {
    const other = second.extracted_names[index];
    const a = item.bounding_box, b = other?.bounding_box;
    return item.name === other?.name && a && b &&
      ["page_number", "x", "y", "width", "height"].every((key) => a[key] === b[key]);
  });
  return namesEqual && first.fuzzy_matches.every((item, index) => {
    const other = second.fuzzy_matches[index];
    return ["extracted_name", "matched_name", "score"].every((key) => item[key] === other?.[key]);
  });
}

async function checkPreview(file, result, signal) {
  const catalog = await fetch("/api/extract/preview", {cache: "no-store", signal});
  if (!catalog.ok) throw new Error("La vista por etapas no está disponible, caducó o fue reemplazada.");
  const info = await catalog.json();
  if (typeof info.preview_id !== "string" || !Array.isArray(info.stages) ||
      !info.stages.includes("final") || info.stages.some((stage) => !Object.hasOwn(labels, stage))) {
    throw new Error("La vista por etapas recibida no es válida.");
  }
  const base = `/api/extract/preview/${encodeURIComponent(info.preview_id)}`;
  const [pdf, finalResponse] = await Promise.all([
    fetch(`${base}/document`, {cache: "no-store", signal}),
    fetch(`${base}/stages/final`, {cache: "no-store", signal}),
  ]);
  if (!pdf.ok || !finalResponse.ok) throw new Error("La vista por etapas caducó o fue reemplazada.");
  const [local, remote, final] = await Promise.all([file.arrayBuffer(), pdf.arrayBuffer(), finalResponse.json()]);
  const localBytes = new Uint8Array(local), remoteBytes = new Uint8Array(remote);
  if (localBytes.length !== remoteBytes.length || !localBytes.every((byte, index) => byte === remoteBytes[index]) ||
      final.stage !== "final" || !sameResponse(result, final)) {
    throw new Error("La vista por etapas no coincide con este PDF y resultado. Vuelve a analizarlo.");
  }
  return {base, stages: info.stages};
}

function PDFPage({document, pageNumber, boxes, stagePage, onError}) {
  const canvas = useRef(null);
  const [geometry, setGeometry] = useState(null);
  const [rendering, setRendering] = useState(true);

  useEffect(() => {
    let cancelled = false, renderTask;
    setGeometry(null);
    setRendering(true);
    (async () => {
      try {
        const page = await document.getPage(pageNumber + 1);
        if (cancelled) return;
        const unrotated = page.getViewport({scale: 1, rotation: 0});
        const visible = page.getViewport({scale: 1});
        // Bound browser canvas memory even for unusually large page dimensions.
        const scale = Math.min(1.5, Math.sqrt(8_000_000 / (visible.width * visible.height)),
          8192 / visible.width, 8192 / visible.height);
        if (!Number.isFinite(scale) || scale <= 0) throw new Error("invalid page geometry");
        const viewport = page.getViewport({scale});
        const element = canvas.current;
        if (!element || cancelled) return;
        element.width = Math.ceil(viewport.width);
        element.height = Math.ceil(viewport.height);
        renderTask = page.render({canvas: element, canvasContext: element.getContext("2d"), viewport});
        await renderTask.promise;
        if (!cancelled) {
          setGeometry({width: unrotated.width, height: unrotated.height, rotation: visible.rotation});
          setRendering(false);
        }
      } catch (error) {
        if (!cancelled && error.name !== "RenderingCancelledException") {
          setRendering(false);
          onError("No se pudo mostrar esta página del PDF.");
        }
      }
    })();
    return () => { cancelled = true; renderTask?.cancel(); };
  }, [document, pageNumber, onError]);

  const dimensionsMatch = !stagePage || (geometry && Math.abs(stagePage.width - geometry.width) < 0.02 &&
    Math.abs(stagePage.height - geometry.height) < 0.02);
  const mapped = geometry && dimensionsMatch ? boxes.map((item) => ({...item,
    position: displayBox(item.box, geometry.width, geometry.height, geometry.rotation)})) : [];
  const omitted = mapped.filter((item) => !item.position).length;
  return <>
    {rendering && <p className="page-message" role="status">Cargando página…</p>}
    <div className="page-sheet" hidden={!geometry}>
      <canvas ref={canvas} aria-label={`Página ${pageNumber + 1} del PDF`} />
      <div className="overlay" aria-label="Cajas de detección">
        {mapped.filter((item) => item.position).map((item, index) =>
          <span key={index} className={`box ${item.source?.startsWith("recovery_") ? "recovered" : ""}`}
            style={Object.fromEntries(Object.entries(item.position).map(([key, value]) => [key, `${value}%`]))}
            title={item.text} aria-label={item.text} />)}
      </div>
    </div>
    {!rendering && stagePage && !dimensionsMatch && <p className="error">Las dimensiones de esta etapa no coinciden; no se muestran sus cajas.</p>}
    {omitted > 0 && <p className="error">No se muestran {omitted} cajas con coordenadas inválidas.</p>}
  </>;
}

export default function App() {
  const [file, setFile] = useState(null), [names, setNames] = useState("[]");
  const [pdf, setPdf] = useState(null), [result, setResult] = useState(null);
  const [page, setPage] = useState(0), [busy, setBusy] = useState(false);
  const [message, setMessage] = useState(defaultMessage), [error, setError] = useState(false);
  const [preview, setPreview] = useState(null);
  const [stage, setStage] = useState("final"), [stageData, setStageData] = useState(null);
  const generation = useRef(0), controller = useRef(null), pdfRef = useRef(null);

  function reset() {
    generation.current += 1;
    controller.current?.abort(); controller.current = null;
    disposePdf(pdfRef.current); pdfRef.current = null;
    setPdf(null); setResult(null); setPreview(null); setStage("final"); setStageData(null);
    setPage(0); setBusy(false);
  }
  useEffect(() => () => {
    generation.current += 1;
    controller.current?.abort();
    disposePdf(pdfRef.current);
  }, []);

  // Stable callback prevents PDF.js from restarting render on unrelated state changes.
  const reportPageError = useRef((text) => { setMessage(text); setError(true); }).current;

  async function extract(event) {
    event.preventDefault();
    if (busy) return;
    if (!file) { setMessage("Selecciona un PDF."); setError(true); return; }
    let parsed;
    try { parsed = parseNames(names); }
    catch { setMessage("Usa una lista JSON con first_name y last_name."); setError(true); return; }
    reset();
    const current = generation.current;
    const abort = new AbortController(); controller.current = abort;
    setBusy(true); setError(false); setMessage("Analizando el documento…");
    let loadingTask;
    try {
      // A separate buffer is used because PDF.js can transfer it to its worker.
      loadingTask = pdfjs.getDocument({data: new Uint8Array(await file.arrayBuffer()),
        cMapUrl: "/pdfjs/cmaps/", cMapPacked: true, standardFontDataUrl: "/pdfjs/standard_fonts/",
        wasmUrl: "/pdfjs/wasm/"});
      if (current !== generation.current) { disposePdf(loadingTask); return; }
      pdfRef.current = loadingTask;
      const loaded = await loadingTask.promise;
      if (current !== generation.current) { disposePdf(loadingTask); return; }
      const form = new FormData(); form.append("pdf_file", file); form.append("names", JSON.stringify(parsed));
      const response = await fetch("/api/extract", {method: "POST", body: form, cache: "no-store", signal: abort.signal});
      if (!response.ok) throw new Error(errorMessage(response.status));
      const data = await response.json();
      if (!Array.isArray(data?.extracted_names) || !Array.isArray(data?.fuzzy_matches)) throw new Error("La respuesta de la API no es válida.");
      if (current !== generation.current) return;
      setPdf(loaded); setResult(data); setMessage("Análisis terminado. Revisa las cajas y las posibles omisiones.");
      try {
        const checked = await checkPreview(file, data, abort.signal);
        if (current === generation.current) setPreview(checked);
      } catch (previewError) {
        if (current === generation.current && previewError.name !== "AbortError") {
          setMessage("Análisis terminado. Las etapas no están disponibles; el resultado final sigue disponible.");
        }
      }
    } catch (err) {
      if (current === generation.current && err.name !== "AbortError") {
        disposePdf(loadingTask);
        if (pdfRef.current === loadingTask) pdfRef.current = null;
        setError(true); setMessage(err.message?.startsWith("El ") || err.message?.startsWith("La ") ||
          err.message?.startsWith("No ") ? err.message : "No se pudo abrir o procesar el PDF.");
      }
    } finally { if (current === generation.current) setBusy(false); }
  }

  async function selectStage(next) {
    if (next === "final") { setStage("final"); setStageData(null); setError(false); return; }
    if (!preview || busy) return;
    const current = generation.current;
    const abort = new AbortController(); controller.current = abort;
    setBusy(true); setError(false);
    try {
      const response = await fetch(`${preview.base}/stages/${encodeURIComponent(next)}`,
        {cache: "no-store", signal: abort.signal});
      if (!response.ok) throw new Error("La etapa caducó o fue reemplazada. El resultado final sigue disponible.");
      const data = await response.json();
      if (data.stage !== next || !Array.isArray(data.pages)) throw new Error("La etapa recibida no es válida.");
      if (current !== generation.current) return;
      setStageData(data); setStage(next); setMessage(`Mostrando ${labels[next]}.`);
    } catch (err) {
      if (current === generation.current && err.name !== "AbortError") { setError(true); setMessage(err.message); }
    } finally { if (current === generation.current) setBusy(false); }
  }

  const stagePage = stageData?.pages.find((item) => item.page_number === page);
  const boxes = stage === "final" ? (result?.extracted_names || []).filter((item) => item.bounding_box?.page_number === page)
    .map((item) => ({text: item.name, box: item.bounding_box})) :
    (stagePage?.boxes || []).filter((item) => item.box?.page_number === page);

  return <div className="app">
    <header><div><strong>Document Intelligence</strong><span> / Auditoría de PDF</span></div><small>INTERFAZ LOCAL</small></header>
    <main>
      <aside>
        <h1>Revisa los nombres de tu documento</h1>
        <p className="muted">Selecciona un PDF y visualiza las detecciones devueltas por la API.</p>
        <form onSubmit={extract}>
          <label htmlFor="pdf-file">Documento PDF</label>
          <input id="pdf-file" type="file" accept="application/pdf,.pdf" onChange={(event) => {
            reset(); setFile(event.target.files[0] || null); setError(false); setMessage(defaultMessage);
          }} />
          <label htmlFor="names">Nombres para comparar <span className="optional">opcional</span></label>
          <textarea id="names" value={names} onChange={(event) => setNames(event.target.value)} rows="4" spellCheck="false" />
          <p className="hint">JSON: <code>{'[{"first_name":"Ana","last_name":"López"}]'}</code></p>
          <button type="submit" className="primary" disabled={busy || !file}>Analizar PDF</button>
        </form>
        <p className={error ? "status error" : "status"} role="status" aria-live="polite">{message}</p>
        {result && <>
          <section><h2>Nombres encontrados <span>{result.extracted_names.length}</span></h2>
            {result.extracted_names.length === 0 ? <p className="muted">No se encontraron nombres.</p> :
              <ul className="results">{result.extracted_names.map((item, index) =>
                <li key={index}><button type="button" onClick={() => {
                  const number = item.bounding_box?.page_number;
                  if (Number.isInteger(number) && number >= 0 && number < pdf.numPages) setPage(number);
                }}>{item.name}<small>Pág. {(item.bounding_box?.page_number ?? 0) + 1}</small></button></li>)}</ul>}
          </section>
          <section><h2>Coincidencias <span>{result.fuzzy_matches.length}</span></h2>
            {result.fuzzy_matches.length === 0 ? <p className="muted">Sin coincidencias para los nombres consultados.</p> :
              <ul className="results matches">{result.fuzzy_matches.map((item, index) =>
                <li key={index}>{item.extracted_name} → {item.matched_name} <strong>{Math.round(item.score * 100)}%</strong></li>)}</ul>}
          </section>
        </>}
        <p className="privacy">La extracción usa OCR y NER locales, no requiere Gemini. Revisa las detecciones manualmente.</p>
      </aside>
      <section className="document-area" aria-label="Documento">
        <div className="document-header"><div><h2>Documento</h2><p>{file?.name || "Ningún PDF seleccionado"}</p></div>
          {pdf && <span>{pdf.numPages} {pdf.numPages === 1 ? "página" : "páginas"}</span>}</div>
        {result && <div className="stages" aria-label="Etapas">
          {(preview?.stages || ["final"]).map((item) => <button key={item} type="button" disabled={busy}
            className={stage === item ? "active" : ""} aria-pressed={stage === item} onClick={() => selectStage(item)}>{labels[item]}</button>)}
        </div>}
        <div className="canvas-area">
          {!pdf ? <div className="empty"><div className="empty-icon">▤</div><strong>Tu documento aparecerá aquí</strong><p>Elige un PDF y pulsa «Analizar PDF».</p></div> :
            <PDFPage key={page} document={pdf} pageNumber={page} boxes={boxes} stagePage={stage === "final" ? null : stagePage} onError={reportPageError} />}
        </div>
        {pdf && <nav className="pagination" aria-label="Páginas">
          <button type="button" disabled={page === 0} onClick={() => setPage(page - 1)}>← Anterior</button>
          <span>Página {page + 1} de {pdf.numPages}</span>
          <button type="button" disabled={page === pdf.numPages - 1} onClick={() => setPage(page + 1)}>Siguiente →</button>
        </nav>}
        {stage !== "final" && !stagePage && <p className="error">Esta etapa no contiene la página actual.</p>}
      </section>
    </main>
  </div>;
}
