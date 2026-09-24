"""Composition root: builds adapters and use cases from Settings."""

from collections.abc import Awaitable
from collections.abc import Callable
import dataclasses
import datetime
import re

import qdrant_client
import structlog

from app import config
from app.adapters.cpu_runner import thread_runner
from app.adapters.dynamodb_common import client as dynamodb
from app.adapters.dynamodb_jobs import repository as dynamodb_jobs
from app.adapters.dynamodb_occurrences import store as occurrence_store
from app.adapters.fastembed_embedding import embedding
from app.adapters.fastembed_sparse import sparse_embedding
from app.adapters.fuzzy import name_matcher
from app.adapters.langchain_llm import chat_models
from app.adapters.langchain_llm import llm as langchain_llm
from app.adapters.langchain_prompts import prompts
from app.adapters.langfuse_observability import observability as langfuse
from app.adapters.noop_observability import observability as noop
from app.adapters.pymupdf import page_renderer
from app.adapters.qdrant import vector_store as qdrant_store
from app.adapters.rabbitmq_queue import queue as rabbitmq_queue
from app.adapters.s3_blobs import store as s3_blobs
from app.adapters.spacy_ner import ner
from app.adapters.sqs_queue import queue as sqs_queue
from app.adapters.tesseract import ocr
from app.adapters.text_chunker import sentence
from app.adapters.unconfigured_llm import llm as unconfigured_llm
from app.domain import errors
from app.ports import job_queue
from app.ports import llm
from app.ports import llm_observability
from app.ports import vector_store
from app.service_layer import ask
from app.service_layer import extract
from app.service_layer import ingest
from app.service_layer import jobs as job_service
from app.service_layer import occurrences


@dataclasses.dataclass(frozen=True, slots=True)
class Container:
    """The use cases and stores the API and the worker call.

    Attributes:
        extract_names: Finds and matches person names in a PDF.
        ingest_document: Indexes a PDF for question answering.
        ask_question: Answers a question from the indexed chunks.
        vector_store: The indexed chunks, read by the documents endpoints.
        record_extraction: Extracts names and records every occurrence.
        query_occurrences: Lists the recorded occurrences.
        submit_job: Queues an extraction or ingestion.
        query_jobs: Reads jobs and their results.
        process_job: Runs one delivered job; used by the worker.
        reap_jobs: Recovers jobs of dead workers and lost messages.
        job_queue: Delivers jobs to the worker.
        startup: Steps awaited once before serving, e.g. creating tables.
    """

    extract_names: extract.ExtractNames
    ingest_document: ingest.IngestDocument
    ask_question: ask.AskQuestion
    vector_store: vector_store.VectorStore
    record_extraction: occurrences.ExtractAndRecord
    query_occurrences: occurrences.QueryOccurrences
    submit_job: job_service.SubmitJob
    query_jobs: job_service.QueryJobs
    process_job: job_service.ProcessJob
    reap_jobs: job_service.ReapJobs
    job_queue: job_queue.JobQueue
    startup: tuple[Callable[[], Awaitable[None]], ...] = ()


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


def build_llm(
    settings: config.LlmSettings,
    observability: llm_observability.LlmObservability,
) -> llm.Llm:
    """Builds the configured language model.

    A missing configuration never stops the service: extraction and
    ingestion keep working, and each question fails with
    ``llm.not_configured``.

    Args:
        settings: Provider, model, credentials and limits.
        observability: Supplies the tracing callbacks.

    Returns:
        The LangChain model, or a stand-in that reports what is missing.
    """
    try:
        chat = chat_models.build_chat_model(settings)
    except errors.LlmNotConfiguredError as exc:
        log.warning("llm.not_configured", provider=settings.provider)
        return unconfigured_llm.UnconfiguredLlm(exc.detail)
    return langchain_llm.LangChainLlm(chat, observability, settings.deadline_s)


def extractor_fingerprint(settings: config.Settings) -> str:
    """Names the models and settings that shape extracted occurrences.

    A change of any of them makes a re-extraction of the same content a new
    generation instead of a skipped duplicate.

    Args:
        settings: The service configuration.

    Returns:
        E.g. ``ner=en_core_web_lg|ocr=eng@300dpi|match=0.9``.
    """
    return (
        f"ner={settings.ner.model}"
        f"|ocr={settings.ocr.languages}@{settings.render.dpi}dpi"
        f"|match={settings.matcher.threshold}"
    )


def build_job_queue(settings: config.Settings) -> job_queue.JobQueue:
    """Picks the job queue of the environment.

    Args:
        settings: The service configuration.

    Returns:
        RabbitMQ locally, SQS on AWS.
    """
    queue = settings.queue
    if settings.cloud_env is config.CloudEnv.AWS:
        return sqs_queue.SqsJobQueue(
            sqs_queue.build_client(queue),
            queue.sqs_queue_url,
            queue.sqs_dead_letter_url,
            queue.sqs_wait_s,
        )
    return rabbitmq_queue.RabbitMqJobQueue(
        queue.rabbitmq_url.get_secret_value(),
        queue.rabbitmq_queue,
        settings.jobs.max_attempts + 2,
        queue.prefetch,
    )


def utc_now() -> datetime.datetime:
    """Returns the current time.

    Returns:
        The time (UTC).
    """
    return datetime.datetime.now(datetime.UTC)


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
    extract_names = extract.ExtractNames(
        renderer=renderer,
        ocr=reader,
        ner=ner.SpacyNer.load(settings.ner.model),
        matcher=name_matcher.RapidFuzzNameMatcher(),
        cpu=cpu,
        threshold=settings.matcher.threshold,
    )
    dynamo = dynamodb.build_client(settings.dynamodb)
    recorded = occurrence_store.DynamoDbOccurrenceStore(
        dynamo, settings.occurrences
    )
    repository = dynamodb_jobs.DynamoDbJobRepository(
        dynamo, settings.jobs.dynamodb_table
    )
    blobs = s3_blobs.S3BlobStore(
        s3_blobs.build_client(settings.blob), settings.blob.bucket
    )
    queue = build_job_queue(settings)
    record = occurrences.RecordOccurrences(
        recorded, extractor_fingerprint(settings)
    )
    ingest_document = ingest.IngestDocument(
        renderer=renderer,
        ocr=reader,
        chunker=sentence.SentenceTextChunker(
            settings.chunking.chunk_size, settings.chunking.chunk_overlap
        ),
        embedder=embedder,
        sparse_embedder=sparse_embedder,
        store=store,
        cpu=cpu,
    )
    return Container(
        extract_names=extract_names,
        ingest_document=ingest_document,
        ask_question=ask.AskQuestion(
            embedder=embedder,
            sparse_embedder=sparse_embedder,
            store=store,
            prompts=prompts.LangChainPrompts(settings.prompts.directory),
            llm=build_llm(
                settings.llm, build_observability(settings.llm_observability)
            ),
            cpu=cpu,
            top_k=settings.qdrant.top_k,
        ),
        vector_store=store,
        record_extraction=occurrences.ExtractAndRecord(
            extract_names, recorded, record
        ),
        query_occurrences=occurrences.QueryOccurrences(recorded),
        submit_job=job_service.SubmitJob(
            blobs,
            repository,
            queue,
            recorded,
            settings.jobs.max_attempts,
            utc_now,
        ),
        query_jobs=job_service.QueryJobs(repository, blobs),
        process_job=job_service.ProcessJob(
            repository,
            blobs,
            extract_names,
            record,
            ingest_document,
            utc_now,
            settings.jobs.lease_s,
            settings.queue.retry_delay_s,
        ),
        reap_jobs=job_service.ReapJobs(
            repository,
            queue,
            utc_now,
            settings.jobs.queued_stale_s,
            settings.jobs.reap_limit,
        ),
        job_queue=queue,
        startup=(
            (recorded.ensure_table, repository.ensure_table)
            if settings.dynamodb.create_tables
            else ()
        ),
    )
