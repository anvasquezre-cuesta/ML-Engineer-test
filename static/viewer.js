/* Audit viewer: overlay extracted name bounding boxes on rendered PDF pages. */

const banner = document.getElementById("errorBanner");

function showError(msg) {
  banner.textContent = msg;
  banner.style.display = "block";
}

function hideError() {
  banner.style.display = "none";
}

function doExtract() {
  const fileInput = document.getElementById("fileInput");
  if (!fileInput.files.length) {
    showError("Please select a PDF file.");
    return;
  }
  hideError();

  // Load-time CDN-failure check
  if (typeof pdfjsLib === "undefined" || window.__pdfjsLoadFailed) {
    showError("PDF viewer (pdf.js) failed to load from CDN — viewer unavailable offline");
    return;
  }

  const file = fileInput.files[0];
  const formData = new FormData();
  formData.append("file", file);
  formData.append("names_json", "[]");

  document.getElementById("montage").innerHTML = "<p>Extracting…</p>";

  fetch("/api/extract", {
    method: "POST",
    body: formData,
  })
    .then((r) => {
      if (!r.ok) throw new Error("HTTP " + r.status);
      return r.json();
    })
    .then((data) => {
      overlayPdf(file, data);
    })
    .catch((e) => {
      showError("Extraction request failed: " + e.message);
    });
}

function overlayPdf(file, data) {
  const groups = {};
  for (const entry of data.extracted_names) {
    const pn = entry.bounding_box.page_number;
    if (!groups[pn]) groups[pn] = [];
    groups[pn].push(entry);
  }

  const montage = document.getElementById("montage");
  montage.innerHTML = "<p>Loading PDF…</p>";

  file.arrayBuffer().then((buf) => {
    pdfjsLib.getDocument({ data: buf }).promise.then((doc) => {
      montage.innerHTML = "";

      for (const pn in groups) {
        const pageEntries = groups[pn];
        doc.getPage(parseInt(pn) + 1).then(async (pdfjsPage) => {
          const pageWrap = document.createElement("div");
          pageWrap.className = "page-wrap";

          // Compute display scale: map PDF points to viewport pixels.
          // Both spaces share origin top-left, y down.
          const baseViewport = pdfjsPage.getViewport({ scale: 1 });
          const canvas = document.createElement("canvas");
          canvas.width = baseViewport.width;
          canvas.height = baseViewport.height;
          canvas.className = "page-canvas";
          pageWrap.appendChild(canvas);

          const ctx = canvas.getContext("2d");
          await pdfjsPage.render({ canvasContext: ctx, viewport: baseViewport }).promise;

          // Scale to viewport width for display
          const k = canvas.clientWidth / baseViewport.width;

          for (const entry of pageEntries) {
            const bb = entry.bounding_box;
            const box = document.createElement("div");
            box.className = "overlay-box";
            box.textContent = entry.name;
            box.style.left = (bb.x * k) + "px";
            box.style.top = (bb.y * k) + "px";
            box.style.width = (bb.width * k) + "px";
            box.style.height = (bb.height * k) + "px";
            pageWrap.appendChild(box);
          }

          montage.appendChild(pageWrap);
        });
      }
    }).catch((e) => {
      showError("Failed to load PDF: " + e.message);
    });
  });
}

// Immediate load-time CDN-failure check
if (typeof pdfjsLib === "undefined" || window.__pdfjsLoadFailed) {
  showError("PDF viewer (pdf.js) failed to load from CDN — viewer unavailable offline");
}
