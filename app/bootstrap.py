"""Composition root: builds adapters and use cases from Settings."""

import dataclasses
import re

import qdrant_client
import structlog

from app import config
from app.adapters.cpu_runner import thread_runner
from app.adapters.fastembed_embedding import embedding
from app.adapters.fastembed_sparse import sparse_embedding
from app.adapters.fuzzy import name_matcher
from app.adapters.langfuse_observability import observability as langfuse
from app.adapters.noop_observability import observability as noop
from app.adapters.pymupdf import page_renderer
from app.adapters.qdrant import vector_store as qdrant_store
from app.adapters.spacy_ner import ner
from app.adapters.tesseract import ocr
from app.adapters.text_chunker import sentence
from app.ports import llm_observability
from app.ports import vector_store
from app.service_layer import extract
from app.service_layer import ingest


@dataclasses.dataclass(frozen=True, slots=True)
class Container:
    """The use cases and stores the API and the worker call.

    Attributes:
        extract_names: Finds and matches person names in a PDF.
        ingest_document: Indexes a PDF for question answering.
        vector_store: The indexed chunks, read by the documents endpoints.
    """

    extract_names: extract.ExtractNames
    ingest_document: ingest.IngestDocument
    vector_store: vector_store.VectorStore


def collection_name(prefix: str, *model_names: str) -> str:
    """Names the collection after the models it holds vectors of.

    Args:
        prefix: Configured collection prefix.
        *model_names: Dense and sparse model identifiers.

    Returns:
        E.g. ``chunks_baai_bge_small_en_v1_5_qdrant_bm25``.
    """
    slugs = (
        re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
        for name in model_names
    )
    return "_".join((prefix, *slugs))


log = structlog.stdlib.get_logger(__name__)


def build_observability(
    settings: config.LlmObservabilitySettings,
) -> llm_observability.LlmObservability:
    """Traces to Langfuse when both keys are set, otherwise traces nothing.

    Tracing is optional: missing keys never stop the service. Only one of
    the two keys set is logged, since it is likely a configuration mistake.

    Args:
        settings: Langfuse host and keys.

    Returns:
        The Langfuse adapter, or the no-op adapter.
    """
    public = settings.langfuse_public_key
    secret = settings.langfuse_secret_key
    if public and secret:
        return langfuse.LangfuseObservability(
            settings, public.get_secret_value(), secret.get_secret_value()
        )
    if public or secret:
        log.warning("llm_observability.partial_keys", tracing="off")
    return noop.NoopObservability()


def build_container(settings: config.Settings) -> Container:
    """Loads every model and client once and wires the use cases.

    Args:
        settings: The service configuration.

    Returns:
        The wired use cases.
    """
    cpu = thread_runner.ThreadCpuRunner(settings.cpu.max_concurrency)
    renderer = page_renderer.PyMuPdfRenderer(settings.render.dpi)
    reader = ocr.TesseractOcr(settings.ocr.languages, settings.ocr.timeout_s)
    embedder = embedding.FastEmbedEmbedding.load(settings.embeddings)
    sparse_embedder = sparse_embedding.FastEmbedSparseEmbedding.load(
        settings.embeddings
    )
    api_key = settings.qdrant.api_key
    store = qdrant_store.QdrantVectorStore(
        qdrant_client.AsyncQdrantClient(
            url=settings.qdrant.url,
            api_key=api_key.get_secret_value() if api_key else None,
            timeout=settings.qdrant.timeout_s,
            # Connect on first use, so extraction works while Qdrant is down.
            check_compatibility=False,
        ),
        settings.qdrant,
        collection=collection_name(
            settings.qdrant.collection_prefix,
            embedder.model_name,
            sparse_embedder.model_name,
        ),
        dimension=embedder.dimension,
    )
    return Container(
        extract_names=extract.ExtractNames(
            renderer=renderer,
            ocr=reader,
            ner=ner.SpacyNer.load(settings.ner.model),
            matcher=name_matcher.RapidFuzzNameMatcher(),
            cpu=cpu,
            threshold=settings.matcher.threshold,
        ),
        ingest_document=ingest.IngestDocument(
            renderer=renderer,
            ocr=reader,
            chunker=sentence.SentenceTextChunker(
                settings.chunking.chunk_size, settings.chunking.chunk_overlap
            ),
            embedder=embedder,
            sparse_embedder=sparse_embedder,
            store=store,
            cpu=cpu,
        ),
        vector_store=store,
    )
