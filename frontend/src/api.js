const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || "").replace(/\/$/, "");

export class ApiError extends Error {
  constructor(message, status = 0) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

function errorMessage(payload, fallback) {
  if (typeof payload?.detail === "string") return payload.detail;
  if (Array.isArray(payload?.detail)) {
    return payload.detail.map((item) => item.msg || "Invalid request").join(". ");
  }
  return fallback;
}

async function request(path, options = {}, timeoutMs = 300_000) {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), timeoutMs);

  try {
    const response = await fetch(`${API_BASE_URL}${path}`, {
      ...options,
      signal: controller.signal,
      headers: {
        Accept: "application/json",
        ...(options.headers || {}),
      },
    });
    const contentType = response.headers.get("content-type") || "";
    const payload = contentType.includes("application/json")
      ? await response.json()
      : await response.text();

    if (!response.ok) {
      throw new ApiError(
        errorMessage(payload, `Request failed with status ${response.status}`),
        response.status,
      );
    }
    return payload;
  } catch (error) {
    if (error.name === "AbortError") {
      throw new ApiError("The request took too long. Please try again.");
    }
    if (error instanceof ApiError) throw error;
    throw new ApiError("The service could not be reached. Check that it is running.");
  } finally {
    window.clearTimeout(timeout);
  }
}

export async function checkHealth() {
  return request("/health", {}, 5_000);
}

export async function extractDocument(file, names) {
  const form = new FormData();
  form.append("pdf_file", file, file.name);
  form.append("names", JSON.stringify(names));
  return request("/api/extract", { method: "POST", body: form });
}

export async function ingestDocument(file) {
  const form = new FormData();
  form.append("pdf_file", file, file.name);
  return request("/api/ingest", { method: "POST", body: form });
}

export async function askQuestion(question) {
  return request(
    "/api/ask",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question }),
    },
    210_000,
  );
}
