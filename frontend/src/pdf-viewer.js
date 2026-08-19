import * as pdfjsLib from "pdfjs-dist";
import pdfWorkerUrl from "pdfjs-dist/build/pdf.worker.min.mjs?url";

// Keep a cache-busting query on the worker URL. Earlier container builds served
// this file with the wrong MIME type, and browsers can retain that failed
// response because the asset filename itself is content-hashed and unchanged.
pdfjsLib.GlobalWorkerOptions.workerSrc = `${pdfWorkerUrl}?module=1`;

export class EvidencePdfViewer {
  constructor({ canvas, pageElement, overlayElement, onBoxSelected }) {
    this.canvas = canvas;
    this.pageElement = pageElement;
    this.overlayElement = overlayElement;
    this.onBoxSelected = onBoxSelected;
    this.document = null;
    this.renderTask = null;
    this.pageNumber = 1;
    this.pageCount = 0;
    this.scale = 1.15;
    this.findings = [];
    this.activeIndex = null;
  }

  async load(file) {
    await this.destroy();
    const content = new Uint8Array(await file.arrayBuffer());
    this.document = await pdfjsLib.getDocument({ data: content }).promise;
    this.pageCount = this.document.numPages;
    this.pageNumber = 1;
    return this.pageCount;
  }

  setFindings(findings) {
    this.findings = findings;
  }

  setActive(index) {
    this.activeIndex = index;
    this.overlayElement.querySelectorAll(".bbox").forEach((element) => {
      element.classList.toggle("active", Number(element.dataset.index) === index);
    });
  }

  async goTo(pageNumber) {
    if (!this.document) return;
    this.pageNumber = Math.min(Math.max(1, pageNumber), this.pageCount);
    await this.render();
  }

  async setScale(scale) {
    this.scale = Math.min(2.4, Math.max(0.55, scale));
    await this.render();
  }

  async render() {
    if (!this.document) return;
    if (this.renderTask) {
      this.renderTask.cancel();
      try { await this.renderTask.promise; } catch (error) {
        if (error?.name !== "RenderingCancelledException") throw error;
      }
    }

    const page = await this.document.getPage(this.pageNumber);
    const baseViewport = page.getViewport({ scale: 1 });
    const viewport = page.getViewport({ scale: this.scale });
    const pixelRatio = window.devicePixelRatio || 1;
    const context = this.canvas.getContext("2d", { alpha: false });

    this.canvas.width = Math.floor(viewport.width * pixelRatio);
    this.canvas.height = Math.floor(viewport.height * pixelRatio);
    this.canvas.style.width = `${viewport.width}px`;
    this.canvas.style.height = `${viewport.height}px`;
    this.pageElement.style.width = `${viewport.width}px`;
    this.pageElement.style.height = `${viewport.height}px`;
    this.overlayElement.style.width = `${viewport.width}px`;
    this.overlayElement.style.height = `${viewport.height}px`;

    this.renderTask = page.render({
      canvasContext: context,
      viewport,
      transform: pixelRatio === 1 ? null : [pixelRatio, 0, 0, pixelRatio, 0, 0],
    });
    try {
      await this.renderTask.promise;
    } catch (error) {
      if (error?.name !== "RenderingCancelledException") throw error;
      return;
    } finally {
      this.renderTask = null;
    }

    this.renderBoxes(viewport, baseViewport);
  }

  renderBoxes(viewport, baseViewport) {
    this.overlayElement.replaceChildren();
    const scaleX = viewport.width / baseViewport.width;
    const scaleY = viewport.height / baseViewport.height;

    this.findings.forEach((finding, index) => {
      const box = finding.bounding_box;
      if (box.page_number !== this.pageNumber - 1) return;
      const element = document.createElement("button");
      element.type = "button";
      element.className = "bbox";
      element.dataset.index = String(index);
      element.title = `${finding.name} · page ${box.page_number + 1}`;
      element.setAttribute("aria-label", `Locate ${finding.name} in the findings panel`);
      element.style.left = `${box.x * scaleX}px`;
      element.style.top = `${box.y * scaleY}px`;
      element.style.width = `${box.width * scaleX}px`;
      element.style.height = `${box.height * scaleY}px`;

      const label = document.createElement("span");
      label.className = "bbox-label";
      label.textContent = finding.name;
      element.append(label);
      element.addEventListener("click", () => this.onBoxSelected(index));
      element.classList.toggle("active", index === this.activeIndex);
      this.overlayElement.append(element);
    });
  }

  async destroy() {
    if (this.renderTask) this.renderTask.cancel();
    if (this.document) await this.document.destroy();
    this.renderTask = null;
    this.document = null;
    this.pageCount = 0;
    this.overlayElement.replaceChildren();
    const context = this.canvas.getContext("2d");
    context?.clearRect(0, 0, this.canvas.width, this.canvas.height);
  }
}
