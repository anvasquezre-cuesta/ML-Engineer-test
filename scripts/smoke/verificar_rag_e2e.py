"""Exercise real RAG HTTP routing with a generated PDF and explicitly chosen LLM mode."""

import json
import sys
import urllib.error
import urllib.request
from uuid import uuid4

import pymupdf

from app.core.config import Settings
from verificar_http import wait_for_server


BASE = "http://127.0.0.1:8000"
CLIENT = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def post(path, body, content_type):
    request = urllib.request.Request(BASE + path, data=body, method="POST", headers={"Content-Type": content_type})
    try:
        with CLIENT.open(request, timeout=240) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as error:
        # Never print response bodies from provider errors.
        return error.code, None


def synthetic_pdf():
    """One empty first page and an image-only second page with synthetic text."""
    with pymupdf.open() as source, pymupdf.open() as scanned:
        original = source.new_page(width=700, height=350)
        original.insert_text((55, 95), "Synthetic Orchard project record.", fontsize=22)
        original.insert_text((55, 155), "The coordinator is Nora Vega.", fontsize=22)
        original.insert_text((55, 215), "The approved budget is 2400 dollars.", fontsize=22)
        pixmap = original.get_pixmap(matrix=pymupdf.Matrix(2, 2), alpha=False)
        scanned.new_page(width=700, height=350)
        page = scanned.new_page(width=700, height=350)
        page.insert_image(page.rect, pixmap=pixmap)
        return scanned.tobytes()


def ask(question):
    return post("/api/ask", json.dumps({"question": question}).encode(), "application/json")


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in {"simulado", "gemini"}:
        raise SystemExit("Uso: verificar_rag_e2e.py simulado|gemini")
    mode = sys.argv[1]
    if mode == "gemini":
        settings = Settings()
        if settings.llm_provider != "gemini" or not settings.llm_allow_external:
            raise SystemExit("Configura LLM_PROVIDER=gemini y LLM_ALLOW_EXTERNAL=true en .env")
    wait_for_server(seconds=45)
    print("[OK] GET /health respondió correctamente", flush=True)

    boundary = "rag-e2e-" + uuid4().hex
    body = (f'--{boundary}\r\nContent-Disposition: form-data; name="pdf_file"; filename="synthetic.pdf"\r\n'
            'Content-Type: application/pdf\r\n\r\n').encode() + synthetic_pdf() + f"\r\n--{boundary}--\r\n".encode()
    status, result = post("/api/ingest", body, "multipart/form-data; boundary=" + boundary)
    if status != 200 or not isinstance(result, dict) or result.get("status") != "success" or result.get("chunks_stored", 0) < 1:
        raise SystemExit(f"Falló /api/ingest (HTTP {status}); no se realizó ninguna consulta al modelo")
    print(f"[OK] PDF sintético de dos páginas ingerido; fragmentos={result['chunks_stored']}", flush=True)

    status, _ = ask("  ")
    if status != 422:
        raise SystemExit(f"La pregunta vacía no fue rechazada como se esperaba (HTTP {status})")
    print("[OK] /api/ask rechaza preguntas vacías", flush=True)

    status, result = ask("Who is the coordinator of the Synthetic Orchard project?")
    if status != 200 or not isinstance(result, dict):
        raise SystemExit(f"Falló /api/ask (HTTP {status}); revisa disponibilidad, configuración y cuota sin mostrar claves")
    answer, sources = result.get("answer"), result.get("sources")
    if (not isinstance(answer, str) or not answer.strip() or not isinstance(sources, list)
            or not sources or any(not isinstance(source, str) for source in sources)
            or not any("synthetic.pdf" in source and "página 2" in source for source in sources)):
        raise SystemExit("/api/ask no devolvió respuesta y fuente esperada para la página sintética")
    if mode == "simulado" and not answer.startswith("Synthetic smoke answer"):
        raise SystemExit("La respuesta no corresponde al generador simulado de la prueba")
    print("[OK] /api/ask devolvió el contrato y una referencia a la página física 2", flush=True)
    if mode == "gemini":
        print(f"Respuesta de Gemini para revisión humana: {answer}", flush=True)
        print("Fuentes: " + json.dumps(sources, ensure_ascii=False), flush=True)
        print("Respuesta esperada: Nora Vega. Las fuentes y la semántica requieren revisión humana.", flush=True)
    else:
        print("La respuesta es simulada: esta prueba no mide calidad de un LLM.", flush=True)


if __name__ == "__main__":
    main()
