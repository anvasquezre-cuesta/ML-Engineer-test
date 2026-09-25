import * as pdfjs from "./vendor/pdfjs/pdf.min.mjs";

import { boxesByPage, matchedNames, namesFromRows, toViewport } from "./boxes.js";

const PDFJS = "./vendor/pdfjs/";
pdfjs.GlobalWorkerOptions.workerSrc = `${PDFJS}pdf.worker.min.mjs`;

const MAX_SCALE = 1.6;
const POLL_MS = 1000;
const JOB_TIMEOUT_MS = 10 * 60 * 1000;

const $ = (selector) => document.querySelector(selector);

/** Adds one editable first/last name row to the form. */
function addNameRow(first = "", last = "") {
  const row = $("#name-row").content.firstElementChild.cloneNode(true);
  row.querySelector(".first").value = first;
  row.querySelector(".last").value = last;
  row.querySelector(".remove").addEventListener("click", () => row.remove());
  $("#name-rows").append(row);
}

function readNameRows() {
  return [...document.querySelectorAll(".name-row")].map((row) => ({
    first: row.querySelector(".first").value,
    last: row.querySelector(".last").value,
  }));
}

function setStatus(text, isError = false) {
  const status = $("#status");
  status.textContent = text;
  status.classList.toggle("error", isError);
}

/** Returns the problem+json message of a failed response. */
async function problem(response) {
  try {
    const body = await response.json();
    return `${body.title ?? "Request failed"} (${body.code ?? response.status})`;
  } catch {
    return `Request failed with HTTP ${response.status}.`;
  }
}

async function postForm(url, form) {
  const response = await fetch(url, { method: "POST", body: form });
  if (!response.ok) throw new Error(await problem(response));
  return response.json();
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

/** Submits an extraction job and polls it until it finishes. */
async function extractAsJob(form) {
  const accepted = await postForm("/api/jobs/extract", form);
  const deadline = Date.now() + JOB_TIMEOUT_MS;
  while (Date.now() < deadline) {
    const response = await fetch(`/api/jobs/${encodeURIComponent(accepted.job_id)}`);
    if (!response.ok) throw new Error(await problem(response));
    const job = await response.json();
    setStatus(`Job ${job.job_id}: ${job.status} (attempt ${job.attempts} of ${job.max_attempts})`);
    if (job.status === "succeeded") return job.extraction;
    if (job.status === "dead_lettered") {
      loadDeadLetters();
      throw new Error(`Job failed: ${job.last_error_message ?? ""} (${job.last_error_code})`);
    }
    await sleep(POLL_MS);
  }
  throw new Error("The job did not finish in time; check it again later.");
}

function cell(row, text, numeric = false) {
  const td = row.insertCell();
  td.textContent = text;
  if (numeric) td.className = "num";
  return td;
}

/** Highlights one occurrence's box and table row, scrolling to the box. */
function activate(index, scroll) {
  document.querySelectorAll(".active").forEach((el) => el.classList.remove("active"));
  const box = document.querySelector(`.box[data-index="${index}"]`);
  const row = document.querySelector(`#names-table tr[data-index="${index}"]`);
  box?.classList.add("active");
  row?.classList.add("active");
  if (scroll) box?.scrollIntoView({ behavior: "smooth", block: "center" });
}

function renderTables(result, matched) {
  const names = $("#names-table tbody");
  names.replaceChildren();
  result.extracted_names.forEach((item, index) => {
    const row = names.insertRow();
    row.dataset.index = String(index);
    const b = item.bounding_box;
    cell(row, item.name).style.color = matched.has(item.name) ? "var(--matched)" : "";
    cell(row, String(b.page_number + 1), true);
    for (const v of [b.x, b.y, b.width, b.height]) cell(row, v.toFixed(1), true);
    row.addEventListener("click", () => activate(index, true));
  });
  const matches = $("#matches-table tbody");
  matches.replaceChildren();
  for (const m of result.fuzzy_matches) {
    const row = matches.insertRow();
    cell(row, m.extracted_name);
    cell(row, m.matched_name);
    cell(row, m.score.toFixed(3), true);
  }
}

/** Renders every page and draws its boxes on top. */
async function renderPages(bytes, result, matched) {
  const container = $("#pages");
  container.replaceChildren();
  const pdf = await pdfjs.getDocument({
    data: bytes,
    wasmUrl: `${PDFJS}wasm/`,
    cMapUrl: `${PDFJS}cmaps/`,
    cMapPacked: true,
    standardFontDataUrl: `${PDFJS}standard_fonts/`,
    iccUrl: `${PDFJS}iccs/`,
  }).promise;
  const byPage = boxesByPage(result.extracted_names, matched);
  const available = Math.max(container.clientWidth, 320);
  for (let number = 0; number < pdf.numPages; number += 1) {
    const page = await pdf.getPage(number + 1);
    const natural = page.getViewport({ scale: 1 });
    const scale = Math.min(MAX_SCALE, available / natural.width);
    const viewport = page.getViewport({ scale });
    const ratio = window.devicePixelRatio || 1;

    const wrapper = document.createElement("div");
    wrapper.className = "page";
    wrapper.dataset.page = String(number);
    wrapper.dataset.scale = String(scale);
    wrapper.style.width = `${viewport.width}px`;
    wrapper.style.height = `${viewport.height}px`;
    const label = document.createElement("span");
    label.className = "page-label";
    label.textContent = `Page ${number + 1} of ${pdf.numPages}`;
    const canvas = document.createElement("canvas");
    canvas.width = Math.floor(viewport.width * ratio);
    canvas.height = Math.floor(viewport.height * ratio);
    canvas.style.width = `${viewport.width}px`;
    canvas.style.height = `${viewport.height}px`;
    wrapper.append(label, canvas);
    container.append(wrapper);

    await page.render({
      canvas,
      viewport,
      transform: ratio === 1 ? undefined : [ratio, 0, 0, ratio, 0, 0],
    }).promise;

    for (const item of byPage.get(number) ?? []) {
      const place = toViewport(item.box, scale);
      const box = document.createElement("div");
      box.className = item.matched ? "box matched" : "box";
      box.dataset.index = String(item.index);
      box.title = item.name;
      Object.assign(box.style, {
        left: `${place.left}px`,
        top: `${place.top}px`,
        width: `${place.width}px`,
        height: `${place.height}px`,
      });
      box.addEventListener("click", () => activate(item.index, false));
      wrapper.append(box);
    }
  }
  return pdf.numPages;
}

async function onSubmit(event) {
  event.preventDefault();
  const file = $("#pdf").files[0];
  if (!file) return;
  let names;
  try {
    names = namesFromRows(readNameRows());
  } catch (error) {
    setStatus(error.message, true);
    return;
  }
  const form = new FormData();
  form.append("pdf_file", file, file.name);
  form.append("names", JSON.stringify(names));
  const key = $("#document-key").value.trim();
  if (key) form.append("document_key", key);

  const button = $("#submit");
  button.disabled = true;
  setStatus("Extracting names...");
  try {
    const asJob = document.querySelector("input[name=mode]:checked").value === "job";
    const result = asJob ? await extractAsJob(form) : await postForm("/api/extract", form);
    const matched = matchedNames(result.fuzzy_matches);
    $("#results").hidden = false;
    renderTables(result, matched);
    const pages = await renderPages(await file.arrayBuffer(), result, matched);
    $("#summary").textContent =
      `${result.extracted_names.length} name occurrences on ${pages} pages; ` +
      `${result.fuzzy_matches.length} fuzzy matches.`;
    setStatus("Done.");
  } catch (error) {
    setStatus(error.message, true);
  } finally {
    button.disabled = false;
  }
}

/** Lists the jobs that failed for good. */
async function loadDeadLetters() {
  const status = $("#dead-status");
  const body = $("#dead-table tbody");
  try {
    const response = await fetch("/api/jobs?status=dead_lettered&limit=50");
    if (!response.ok) throw new Error(await problem(response));
    const jobs = await response.json();
    body.replaceChildren();
    for (const job of jobs) {
      const row = body.insertRow();
      cell(row, job.job_id.slice(0, 8)).title = job.job_id;
      cell(row, job.kind);
      cell(row, job.document_key ?? "");
      cell(row, job.last_error_code ?? "").title = job.last_error_message ?? "";
      cell(row, String(job.attempts), true);
      cell(row, new Date(job.updated_at).toLocaleString());
    }
    status.textContent = jobs.length ? "" : "No dead-lettered jobs.";
    status.classList.remove("error");
  } catch (error) {
    status.textContent = error.message;
    status.classList.add("error");
  }
}

addNameRow();
$("#add-name").addEventListener("click", () => addNameRow());
$("#extract-form").addEventListener("submit", onSubmit);
$("#refresh-dead").addEventListener("click", loadDeadLetters);
loadDeadLetters();
