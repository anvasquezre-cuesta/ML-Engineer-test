import "./styles.css";

import { askQuestion, checkHealth, extractDocument, ingestDocument } from "./api.js";
import { EvidencePdfViewer } from "./pdf-viewer.js";
import {
  bestMatchFor,
  collectCandidateNames,
  formatBytes,
  parseSourceReference,
  validatePdfFile,
} from "./utils.js";

const maxUploadMb = Number(import.meta.env.VITE_MAX_UPLOAD_MB || 20);
const maxUploadBytes = maxUploadMb * 1024 * 1024;

// Remove registrations from older versions of the frontend. This application
// does not use a service worker, and a stale worker could serve outdated assets.
if ("serviceWorker" in navigator) {
  navigator.serviceWorker.getRegistrations()
    .then(async (registrations) => {
      if (!registrations.length) return;
      const wasControlled = Boolean(navigator.serviceWorker.controller);
      await Promise.all(registrations.map((registration) => registration.unregister()));
      const reloadKey = "evidence-desk-retired-service-worker";
      if (wasControlled && !sessionStorage.getItem(reloadKey)) {
        sessionStorage.setItem(reloadKey, "true");
        window.location.reload();
      }
    })
    .catch((error) => console.warn("Could not retire an older service worker", error));
}

const elements = {
  navButtons: [...document.querySelectorAll(".rail-button")],
  views: [...document.querySelectorAll(".view")],
  apiStatus: document.querySelector("#apiStatus"),
  uploadLimits: [...document.querySelectorAll(".uploadLimit")],
  extractSetup: document.querySelector("#extractSetup"),
  extractProgress: document.querySelector("#extractProgress"),
  reviewResults: document.querySelector("#reviewResults"),
  resultActions: [...document.querySelectorAll(".result-action")],
  extractFileInput: document.querySelector("#extractFileInput"),
  extractDropzone: document.querySelector("#extractDropzone"),
  extractSelectedFile: document.querySelector("#extractSelectedFile"),
  candidateRows: document.querySelector("#candidateRows"),
  candidateCount: document.querySelector("#candidateCount"),
  addCandidateButton: document.querySelector("#addCandidateButton"),
  extractButton: document.querySelector("#extractButton"),
  replacePdfButton: document.querySelector("#replacePdfButton"),
  exportButton: document.querySelector("#exportButton"),
  pageMetric: document.querySelector("#pageMetric"),
  peopleMetric: document.querySelector("#peopleMetric"),
  matchMetric: document.querySelector("#matchMetric"),
  timeMetric: document.querySelector("#timeMetric"),
  viewerFilename: document.querySelector("#viewerFilename"),
  pageCount: document.querySelector("#pageCount"),
  zoomValue: document.querySelector("#zoomValue"),
  previousPageButton: document.querySelector("#previousPageButton"),
  nextPageButton: document.querySelector("#nextPageButton"),
  zoomOutButton: document.querySelector("#zoomOutButton"),
  zoomInButton: document.querySelector("#zoomInButton"),
  findingFilter: document.querySelector("#findingFilter"),
  findingsList: document.querySelector("#findingsList"),
  occurrenceSummary: document.querySelector("#occurrenceSummary"),
  documentStage: document.querySelector("#documentStage"),
  ingestFileInput: document.querySelector("#ingestFileInput"),
  ingestDropzone: document.querySelector("#ingestDropzone"),
  ingestSelectedFile: document.querySelector("#ingestSelectedFile"),
  ingestButton: document.querySelector("#ingestButton"),
  ingestActivity: document.querySelector("#ingestActivity"),
  ingestCount: document.querySelector("#ingestCount"),
  askForm: document.querySelector("#askForm"),
  questionInput: document.querySelector("#questionInput"),
  askButton: document.querySelector("#askButton"),
  chatMessages: document.querySelector("#chatMessages"),
  clearConversationButton: document.querySelector("#clearConversationButton"),
  sourceList: document.querySelector("#sourceList"),
  sourceCount: document.querySelector("#sourceCount"),
  toast: document.querySelector("#toast"),
};

const state = {
  extractFile: null,
  extraction: null,
  activeFinding: null,
  ingestFile: null,
  ingestHistory: [],
  toastTimer: null,
};

const pdfViewer = new EvidencePdfViewer({
  canvas: document.querySelector("#pdfCanvas"),
  pageElement: document.querySelector("#pdfPage"),
  overlayElement: document.querySelector("#overlayLayer"),
  onBoxSelected: (index) => selectFinding(index),
});

function setView(viewName, updateHash = true) {
  if (!elements.views.some((view) => view.id === viewName)) viewName = "review";
  elements.views.forEach((view) => view.classList.toggle("active", view.id === viewName));
  elements.navButtons.forEach((button) => {
    const active = button.dataset.view === viewName;
    button.classList.toggle("active", active);
    if (active) button.setAttribute("aria-current", "page");
    else button.removeAttribute("aria-current");
  });
  if (updateHash) history.replaceState(null, "", `#${viewName}`);
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function setBusy(button, busy, busyLabel, idleLabel) {
  button.disabled = busy;
  button.classList.toggle("busy", busy);
  button.textContent = busy ? busyLabel : idleLabel;
}

function showToast(title, message, type = "error") {
  window.clearTimeout(state.toastTimer);
  elements.toast.querySelector("strong").textContent = title;
  elements.toast.querySelector("p").textContent = message;
  elements.toast.querySelector(".toast-icon").textContent = type === "success" ? "✓" : "!";
  elements.toast.classList.toggle("success", type === "success");
  elements.toast.hidden = false;
  state.toastTimer = window.setTimeout(() => { elements.toast.hidden = true; }, 6500);
}

async function refreshHealth() {
  try {
    const health = await checkHealth();
    elements.apiStatus.className = "api-status online";
    elements.apiStatus.querySelector("span").textContent = health.status === "ok" ? "API operational" : "API responded";
  } catch {
    elements.apiStatus.className = "api-status offline";
    elements.apiStatus.querySelector("span").textContent = "API unavailable";
  }
}

function displaySelectedFile(container, file) {
  container.querySelector("strong").textContent = file.name;
  container.querySelector("small").textContent = formatBytes(file.size);
  container.hidden = false;
}

function clearSelectedFile(container) {
  container.hidden = true;
  container.querySelector("strong").textContent = "";
  container.querySelector("small").textContent = "";
}

function wireFilePicker({ input, dropzone, selected, onSelect, onClear }) {
  const choose = () => input.click();
  dropzone.addEventListener("click", choose);
  input.addEventListener("change", () => {
    if (input.files?.[0]) onSelect(input.files[0]);
  });
  for (const eventName of ["dragenter", "dragover"]) {
    dropzone.addEventListener(eventName, (event) => {
      event.preventDefault();
      dropzone.classList.add("dragging");
    });
  }
  for (const eventName of ["dragleave", "drop"]) {
    dropzone.addEventListener(eventName, (event) => {
      event.preventDefault();
      dropzone.classList.remove("dragging");
    });
  }
  dropzone.addEventListener("drop", (event) => {
    const file = event.dataTransfer?.files?.[0];
    if (file) onSelect(file);
  });
  selected.querySelector("button").addEventListener("click", () => {
    input.value = "";
    clearSelectedFile(selected);
    onClear();
  });
}

async function acceptExtractFile(file) {
  try {
    await validatePdfFile(file, maxUploadBytes);
    state.extractFile = file;
    displaySelectedFile(elements.extractSelectedFile, file);
    elements.extractButton.disabled = false;
  } catch (error) {
    state.extractFile = null;
    elements.extractFileInput.value = "";
    clearSelectedFile(elements.extractSelectedFile);
    elements.extractButton.disabled = true;
    showToast("PDF not accepted", error.message);
  }
}

function addCandidateRow(firstName = "", lastName = "") {
  const row = document.createElement("div");
  row.className = "candidate-row";

  const firstInput = document.createElement("input");
  firstInput.type = "text";
  firstInput.placeholder = "e.g. María";
  firstInput.autocomplete = "off";
  firstInput.value = firstName;
  firstInput.setAttribute("aria-label", "Candidate first name");

  const lastInput = document.createElement("input");
  lastInput.type = "text";
  lastInput.placeholder = "e.g. González";
  lastInput.autocomplete = "off";
  lastInput.value = lastName;
  lastInput.setAttribute("aria-label", "Candidate last name");

  const removeButton = document.createElement("button");
  removeButton.type = "button";
  removeButton.textContent = "×";
  removeButton.setAttribute("aria-label", "Remove candidate");
  removeButton.addEventListener("click", () => {
    row.remove();
    if (!elements.candidateRows.children.length) addCandidateRow();
    updateCandidateCount();
  });
  for (const input of [firstInput, lastInput]) {
    input.addEventListener("input", () => {
      input.classList.remove("invalid");
      updateCandidateCount();
    });
  }
  row.append(firstInput, lastInput, removeButton);
  elements.candidateRows.append(row);
  updateCandidateCount();
  return row;
}

function candidateValues() {
  return [...elements.candidateRows.querySelectorAll(".candidate-row")].map((row) => ({
    firstName: row.children[0].value,
    lastName: row.children[1].value,
  }));
}

function updateCandidateCount() {
  const { names } = collectCandidateNames(candidateValues());
  elements.candidateCount.textContent = `${names.length} ${names.length === 1 ? "name" : "names"}`;
}

function markIncompleteCandidates(indices) {
  const rows = [...elements.candidateRows.querySelectorAll(".candidate-row")];
  rows.forEach((row, index) => {
    if (!indices.includes(index)) return;
    [...row.querySelectorAll("input")].forEach((input) => {
      input.classList.toggle("invalid", !input.value.trim());
    });
  });
  rows[indices[0]]?.querySelector(".invalid")?.focus();
}

function updateViewerControls() {
  elements.pageCount.textContent = `${pdfViewer.pageNumber} / ${pdfViewer.pageCount}`;
  elements.zoomValue.textContent = `${Math.round(pdfViewer.scale * 100)}%`;
  elements.previousPageButton.disabled = pdfViewer.pageNumber <= 1;
  elements.nextPageButton.disabled = pdfViewer.pageNumber >= pdfViewer.pageCount;
  elements.zoomOutButton.disabled = pdfViewer.scale <= 0.55;
  elements.zoomInButton.disabled = pdfViewer.scale >= 2.4;
}

function findingMatchesFilter(finding, match, filter) {
  if (!filter) return true;
  const content = [finding.name, match?.matched_name, `page ${finding.bounding_box.page_number + 1}`]
    .filter(Boolean)
    .join(" ")
    .toLocaleLowerCase();
  return content.includes(filter.toLocaleLowerCase());
}

function renderFindings() {
  elements.findingsList.replaceChildren();
  const findings = state.extraction?.extracted_names || [];
  const matches = state.extraction?.fuzzy_matches || [];
  const filter = elements.findingFilter.value.trim();
  let visibleCount = 0;

  findings.forEach((finding, index) => {
    const match = bestMatchFor(finding.name, matches);
    if (!findingMatchesFilter(finding, match, filter)) return;
    visibleCount += 1;
    const box = finding.bounding_box;
    const button = document.createElement("button");
    button.type = "button";
    button.className = "finding";
    button.classList.toggle("active", index === state.activeFinding);
    button.dataset.index = String(index);

    const top = document.createElement("div");
    top.className = "finding-top";
    const name = document.createElement("span");
    name.className = "finding-name";
    name.textContent = finding.name;
    const score = document.createElement("span");
    score.className = `score${match ? "" : " no-match"}`;
    score.textContent = match ? `${Math.round(match.score * 100)}% match` : "No match";
    top.append(name, score);

    const meta = document.createElement("div");
    meta.className = "finding-meta";
    meta.textContent = `Page ${box.page_number + 1} · x ${box.x.toFixed(1)} · y ${box.y.toFixed(1)} · ${box.width.toFixed(1)} × ${box.height.toFixed(1)} pt`;

    const matchLine = document.createElement("div");
    matchLine.className = "match-line";
    const matchCopy = document.createElement("span");
    if (match) {
      matchCopy.append("Candidate: ");
      const candidate = document.createElement("b");
      candidate.textContent = match.matched_name;
      matchCopy.append(candidate);
    } else {
      matchCopy.textContent = "No candidate met the configured threshold";
    }
    matchLine.append(matchCopy);
    button.append(top, meta, matchLine);
    button.addEventListener("click", () => selectFinding(index));
    elements.findingsList.append(button);
  });

  if (!visibleCount) {
    const empty = document.createElement("div");
    empty.className = "no-findings";
    empty.textContent = findings.length ? "No findings match this filter." : "No person names were located in this document.";
    elements.findingsList.append(empty);
  }
}

async function selectFinding(index) {
  const finding = state.extraction?.extracted_names?.[index];
  if (!finding) return;
  state.activeFinding = index;
  const targetPage = finding.bounding_box.page_number + 1;
  if (pdfViewer.pageNumber !== targetPage) await pdfViewer.goTo(targetPage);
  pdfViewer.setActive(index);
  updateViewerControls();
  renderFindings();
  elements.findingsList.querySelector(`[data-index="${index}"]`)?.scrollIntoView({ block: "nearest" });
}

async function runExtraction() {
  if (!state.extractFile) return;
  const { names, incompleteIndices } = collectCandidateNames(candidateValues());
  if (incompleteIndices.length) {
    markIncompleteCandidates(incompleteIndices);
    showToast("Complete each candidate", "Both first and last name are required for a candidate row.");
    return;
  }

  const startedAt = performance.now();
  elements.extractSetup.hidden = true;
  elements.reviewResults.hidden = true;
  elements.extractProgress.hidden = false;
  elements.resultActions.forEach((action) => { action.hidden = true; });
  elements.extractButton.disabled = true;

  try {
    const result = await extractDocument(state.extractFile, names);
    state.extraction = result;
    state.activeFinding = result.extracted_names.length ? 0 : null;
    pdfViewer.setFindings(result.extracted_names);
    pdfViewer.activeIndex = state.activeFinding;
    const pageCount = await pdfViewer.load(state.extractFile);
    pdfViewer.setFindings(result.extracted_names);
    pdfViewer.activeIndex = state.activeFinding;
    await pdfViewer.render();

    elements.pageMetric.textContent = String(pageCount);
    elements.peopleMetric.textContent = String(result.extracted_names.length);
    elements.matchMetric.textContent = String(result.fuzzy_matches.length);
    elements.timeMetric.textContent = `${((performance.now() - startedAt) / 1000).toFixed(1)}s`;
    elements.viewerFilename.textContent = state.extractFile.name;
    elements.occurrenceSummary.textContent = `${result.extracted_names.length} ${result.extracted_names.length === 1 ? "occurrence" : "occurrences"} · document order`;
    elements.findingFilter.value = "";
    renderFindings();
    updateViewerControls();

    elements.extractProgress.hidden = true;
    elements.reviewResults.hidden = false;
    elements.resultActions.forEach((action) => { action.hidden = false; });
  } catch (error) {
    elements.extractProgress.hidden = true;
    elements.extractSetup.hidden = false;
    elements.extractButton.disabled = false;
    showToast("Extraction failed", error.message);
  }
}

async function resetReview({ chooseFile = false } = {}) {
  state.extractFile = null;
  state.extraction = null;
  state.activeFinding = null;
  elements.extractFileInput.value = "";
  clearSelectedFile(elements.extractSelectedFile);
  elements.extractButton.disabled = true;
  elements.reviewResults.hidden = true;
  elements.extractProgress.hidden = true;
  elements.extractSetup.hidden = false;
  elements.resultActions.forEach((action) => { action.hidden = true; });
  const destruction = pdfViewer.destroy();
  if (chooseFile) elements.extractFileInput.click();
  await destruction;
}

function exportExtraction() {
  if (!state.extraction || !state.extractFile) return;
  const payload = JSON.stringify({ filename: state.extractFile.name, ...state.extraction }, null, 2);
  const url = URL.createObjectURL(new Blob([payload], { type: "application/json" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = `${state.extractFile.name.replace(/\.pdf$/i, "")}-extraction.json`;
  link.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 0);
}

async function acceptIngestFile(file) {
  try {
    await validatePdfFile(file, maxUploadBytes);
    state.ingestFile = file;
    displaySelectedFile(elements.ingestSelectedFile, file);
    elements.ingestButton.disabled = false;
  } catch (error) {
    state.ingestFile = null;
    elements.ingestFileInput.value = "";
    clearSelectedFile(elements.ingestSelectedFile);
    elements.ingestButton.disabled = true;
    showToast("PDF not accepted", error.message);
  }
}

function renderIngestHistory() {
  elements.ingestActivity.replaceChildren();
  elements.ingestCount.textContent = String(state.ingestHistory.length);
  if (!state.ingestHistory.length) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    const icon = document.createElement("span");
    icon.textContent = "▤";
    const copy = document.createElement("p");
    copy.textContent = "Documents indexed in this session will appear here.";
    empty.append(icon, copy);
    elements.ingestActivity.append(empty);
    return;
  }
  state.ingestHistory.forEach((item) => {
    const row = document.createElement("div");
    row.className = "activity-row";
    const dot = document.createElement("i");
    const info = document.createElement("div");
    const name = document.createElement("b");
    name.textContent = item.filename;
    const meta = document.createElement("small");
    meta.textContent = `${item.chunks} chunks · ${item.time}`;
    info.append(name, meta);
    const status = document.createElement("span");
    status.textContent = "Ready";
    row.append(dot, info, status);
    elements.ingestActivity.append(row);
  });
}

async function runIngestion() {
  if (!state.ingestFile) return;
  const file = state.ingestFile;
  setBusy(elements.ingestButton, true, "Indexing document…", "Index document →");
  try {
    const result = await ingestDocument(file);
    state.ingestHistory.unshift({
      filename: file.name,
      chunks: result.chunks_stored,
      time: "just now",
    });
    renderIngestHistory();
    state.ingestFile = null;
    elements.ingestFileInput.value = "";
    clearSelectedFile(elements.ingestSelectedFile);
    showToast("Document indexed", `${result.chunks_stored} chunks are ready for grounded questions.`, "success");
  } catch (error) {
    showToast("Ingestion failed", error.message);
  } finally {
    setBusy(elements.ingestButton, false, "Indexing document…", "Index document →");
    elements.ingestButton.disabled = !state.ingestFile;
  }
}

function appendMessage(role, text) {
  elements.chatMessages.querySelector(".welcome-message")?.remove();
  const message = document.createElement("div");
  message.className = `message ${role}`;
  const label = document.createElement("span");
  label.className = "message-label";
  label.textContent = role === "user" ? "You" : "Grounded answer";
  const copy = document.createElement("div");
  copy.textContent = text;
  message.append(label, copy);
  elements.chatMessages.append(message);
  elements.chatMessages.scrollTop = elements.chatMessages.scrollHeight;
}

function appendTyping() {
  const message = document.createElement("div");
  message.className = "message answer";
  message.id = "typingMessage";
  const label = document.createElement("span");
  label.className = "message-label";
  label.textContent = "Searching evidence";
  const dots = document.createElement("div");
  dots.className = "typing";
  dots.append(document.createElement("i"), document.createElement("i"), document.createElement("i"));
  message.append(label, dots);
  elements.chatMessages.append(message);
  elements.chatMessages.scrollTop = elements.chatMessages.scrollHeight;
}

function renderSources(sources) {
  elements.sourceList.replaceChildren();
  elements.sourceCount.textContent = String(sources.length);
  if (!sources.length) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    const icon = document.createElement("span");
    icon.textContent = "◇";
    const copy = document.createElement("p");
    copy.textContent = "The service returned no sources for this answer.";
    empty.append(icon, copy);
    elements.sourceList.append(empty);
    return;
  }
  sources.forEach((reference) => {
    const source = parseSourceReference(reference);
    const card = document.createElement("article");
    card.className = "source-card";
    const title = document.createElement("b");
    title.textContent = `[${source.id}] ${source.filename}`;
    const location = document.createElement("span");
    location.textContent = source.location;
    card.append(title, location);
    elements.sourceList.append(card);
  });
}

async function submitQuestion(event) {
  event.preventDefault();
  const question = elements.questionInput.value.trim();
  if (!question) {
    elements.questionInput.focus();
    return;
  }
  appendMessage("user", question);
  elements.questionInput.value = "";
  elements.questionInput.style.height = "auto";
  appendTyping();
  setBusy(elements.askButton, true, "Asking…", "Ask →");
  try {
    const result = await askQuestion(question);
    document.querySelector("#typingMessage")?.remove();
    appendMessage("answer", result.answer);
    renderSources(result.sources);
  } catch (error) {
    document.querySelector("#typingMessage")?.remove();
    showToast("Question could not be answered", error.message);
  } finally {
    setBusy(elements.askButton, false, "Asking…", "Ask →");
    elements.questionInput.focus();
  }
}

function clearConversation() {
  elements.chatMessages.replaceChildren();
  const welcome = document.createElement("div");
  welcome.className = "welcome-message";
  const icon = document.createElement("span");
  icon.textContent = "✦";
  const title = document.createElement("h2");
  title.textContent = "Ask about your indexed documents";
  const copy = document.createElement("p");
  copy.textContent = "Try a person, date, metric, or comparison. If the evidence is insufficient, the service will say so.";
  welcome.append(icon, title, copy);
  elements.chatMessages.append(welcome);
  elements.sourceCount.textContent = "0";
  elements.sourceList.replaceChildren();
  const sourceEmpty = document.createElement("div");
  sourceEmpty.className = "empty-state";
  const sourceIcon = document.createElement("span");
  sourceIcon.textContent = "⌕";
  const sourceCopy = document.createElement("p");
  sourceCopy.textContent = "Sources used by an answer will appear here.";
  sourceEmpty.append(sourceIcon, sourceCopy);
  elements.sourceList.append(sourceEmpty);
}

elements.uploadLimits.forEach((element) => { element.textContent = `${maxUploadMb} MB`; });
elements.navButtons.forEach((button) => button.addEventListener("click", () => setView(button.dataset.view)));
window.addEventListener("hashchange", () => setView(location.hash.slice(1), false));
document.querySelectorAll(".brand, .mark").forEach((link) => link.addEventListener("click", () => setView("review")));
elements.toast.querySelector("button").addEventListener("click", () => { elements.toast.hidden = true; });

wireFilePicker({
  input: elements.extractFileInput,
  dropzone: elements.extractDropzone,
  selected: elements.extractSelectedFile,
  onSelect: acceptExtractFile,
  onClear: () => { state.extractFile = null; elements.extractButton.disabled = true; },
});
wireFilePicker({
  input: elements.ingestFileInput,
  dropzone: elements.ingestDropzone,
  selected: elements.ingestSelectedFile,
  onSelect: acceptIngestFile,
  onClear: () => { state.ingestFile = null; elements.ingestButton.disabled = true; },
});

elements.addCandidateButton.addEventListener("click", () => addCandidateRow());
elements.extractButton.addEventListener("click", runExtraction);
elements.replacePdfButton.addEventListener("click", () => resetReview({ chooseFile: true }));
elements.exportButton.addEventListener("click", exportExtraction);
elements.findingFilter.addEventListener("input", renderFindings);
elements.previousPageButton.addEventListener("click", async () => { await pdfViewer.goTo(pdfViewer.pageNumber - 1); updateViewerControls(); });
elements.nextPageButton.addEventListener("click", async () => { await pdfViewer.goTo(pdfViewer.pageNumber + 1); updateViewerControls(); });
elements.zoomOutButton.addEventListener("click", async () => { await pdfViewer.setScale(pdfViewer.scale - 0.15); updateViewerControls(); });
elements.zoomInButton.addEventListener("click", async () => { await pdfViewer.setScale(pdfViewer.scale + 0.15); updateViewerControls(); });
elements.ingestButton.addEventListener("click", runIngestion);
elements.askForm.addEventListener("submit", submitQuestion);
elements.clearConversationButton.addEventListener("click", clearConversation);
elements.questionInput.addEventListener("input", () => {
  elements.questionInput.style.height = "auto";
  elements.questionInput.style.height = `${Math.min(elements.questionInput.scrollHeight, 130)}px`;
});
elements.questionInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    elements.askForm.requestSubmit();
  }
});

addCandidateRow();
addCandidateRow();
renderIngestHistory();
setView(location.hash.slice(1) || "review", false);
refreshHealth();
window.setInterval(refreshHealth, 30_000);
window.addEventListener("beforeunload", () => { pdfViewer.destroy(); });
