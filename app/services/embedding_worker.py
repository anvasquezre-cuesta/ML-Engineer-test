"""Private persistent CPU worker; never print document/model errors to stderr."""

from dataclasses import asdict
import json
import sys

from app.services.chunking_service import ChunkingError, ChunkingLimitError, TokenAwareChunker
from app.services.embedding_service import EmbeddingInputError, EmbeddingModel, EmbeddingModelUnavailableError

MAX_MESSAGE_BYTES = 64 * 1024 * 1024


def send(message: dict) -> None:
    data = json.dumps(message, ensure_ascii=True, separators=(",", ":"), allow_nan=False).encode() + b"\n"
    if len(data) > MAX_MESSAGE_BYTES:
        data = b'{"status":"limit_error"}\n'
    sys.stdout.buffer.write(data)
    sys.stdout.buffer.flush()


def prepare(model, request, config):
    pages = request["pages"]
    if not isinstance(pages, list) or not pages or len(pages) > config["max_pdf_pages"]:
        raise ChunkingLimitError("Invalid pages")
    if any(not isinstance(text, str) for text in pages):
        raise ChunkingError("Invalid page text")
    if sum(map(len, pages)) > config["ingest_max_document_chars"]:
        raise ChunkingLimitError("Document is too large")
    chunker = TokenAwareChunker(
        model.tokenizer, max_tokens=config["ingest_chunk_tokens"], overlap_tokens=config["ingest_overlap_tokens"],
        model_max_tokens=256, max_page_chars=config["ingest_max_page_chars"],
        max_page_chunks=config["ingest_max_chunks"],
    )
    chunks, page_records = [], []
    for number, text in enumerate(pages):
        page_chunks = chunker.split_page(text, number)
        chunks.extend(page_chunks)
        page_records.append({"page_number": number, "text_detected": bool(text.strip()), "chunk_count": len(page_chunks)})
        if len(chunks) > config["ingest_max_chunks"]:
            raise ChunkingLimitError("Document chunk limit exceeded")
    vectors = model.encode(
        [chunk.text for chunk in chunks], max_tokens=config["ingest_chunk_tokens"],
        batch_size=config["embedding_batch_size"], max_inputs=config["ingest_max_chunks"],
        max_input_chars=config["ingest_max_page_chars"],
        # Repeated overlapping text is bounded separately from original OCR.
        max_document_chars=config["ingest_max_page_chars"] * config["ingest_max_chunks"],
    )
    return {"status": "ok", "chunks": [asdict(chunk) for chunk in chunks], "pages": page_records, "vectors": vectors}


def process(model, line, config):
    try:
        request = json.loads(line)
        if request.get("operation", "prepare") == "query":
            vectors = model.encode([request["question"]], max_tokens=config["embedding_query_max_tokens"],
                                   max_inputs=1, max_input_chars=2000, max_document_chars=2000)
            send({"status": "ok", "vector": vectors[0]})
        elif request.get("operation", "prepare") == "prepare":
            send(prepare(model, request, config))
        else:
            send({"status": "input_error"})
    except ChunkingLimitError:
        send({"status": "limit_error"})
    except (ChunkingError, EmbeddingInputError):
        send({"status": "input_error"})
    except Exception:
        send({"status": "processing_error"})


def main():
    model = None
    try:
        config = json.loads(sys.stdin.buffer.readline(64 * 1024))
        model = EmbeddingModel(config["embedding_model_dir"])
        send({"status": "ready"})
        while True:
            line = sys.stdin.buffer.readline(MAX_MESSAGE_BYTES + 1)
            if not line:
                return
            if len(line) > MAX_MESSAGE_BYTES:
                send({"status": "limit_error"})
                return
            process(model, line, config)
            del line
    except EmbeddingModelUnavailableError:
        send({"status": "model_unavailable"})
    except Exception:
        send({"status": "processing_error"})
    finally:
        if model is not None:
            model.close()


if __name__ == "__main__":
    main()
