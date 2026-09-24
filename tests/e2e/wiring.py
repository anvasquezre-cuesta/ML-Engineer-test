"""An app wired to fakes for the heavy models and an in-memory Qdrant."""

from collections.abc import Callable
from collections.abc import Iterator
import contextlib

from fastapi import testclient
import qdrant_client

from app import bootstrap
from app import config
from app import main
from app.adapters.langchain_prompts import prompts
from app.adapters.qdrant import vector_store as qdrant_store
from app.adapters.text_chunker import sentence
from app.ports import llm
from app.ports import page_renderer
from app.service_layer import ask as ask_service
from app.service_layer import extract as extract_service
from app.service_layer import ingest as ingest_service
from app.service_layer import occurrences as occurrence_service
from tests import builders
from tests.fakes import cpu_runner
from tests.fakes import embedding
from tests.fakes import llm as llm_fake
from tests.fakes import name_matcher
from tests.fakes import ner as ner_fake
from tests.fakes import occurrence_store
from tests.fakes import ocr as ocr_fake
from tests.fakes import page_renderer as page_renderer_fake
from tests.fakes import sparse_embedding

UPLOAD_LIMIT = 1024
PAGE = builders.page_words([["Dr. Anna Berg met Lucas Moreau"]])


def fake_container(
    renderer: page_renderer.PageRenderer,
    model: llm.Llm,
    recorded: occurrence_store.InMemoryOccurrenceStore,
) -> Callable[[config.Settings], bootstrap.Container]:
    """Returns a factory wiring the use cases to fakes around ``renderer``.

    OCR, NER, the matcher, embeddings and the language model are fakes;
    chunking, the prompt files and the Qdrant adapter are real, over an
    in-process Qdrant.

    Args:
        renderer: The renderer the use cases call first.
        model: The language model that answers questions.
        recorded: The occurrence store.

    Returns:
        A container factory for ``create_app``.
    """
    reader = ocr_fake.ScriptedOcr([PAGE])
    cpu = cpu_runner.InlineCpuRunner()

    def build(settings: config.Settings) -> bootstrap.Container:
        store = qdrant_store.QdrantVectorStore(
            qdrant_client.AsyncQdrantClient(location=":memory:"),
            settings.qdrant,
            collection="chunks_test",
            dimension=embedding.HashingEmbedding.DIMENSION,
        )
        embedder = embedding.HashingEmbedding()
        sparse_embedder = sparse_embedding.WordCountSparseEmbedding()
        extract_names = extract_service.ExtractNames(
            renderer=renderer,
            ocr=reader,
            ner=ner_fake.ExactNer({"Anna Berg", "Lucas Moreau"}),
            matcher=name_matcher.ScriptedNameMatcher(
                {("Anna Berg", "Anna Berg"): 1.0}
            ),
            cpu=cpu,
            threshold=0.9,
        )
        return bootstrap.Container(
            extract_names=extract_names,
            ingest_document=ingest_service.IngestDocument(
                renderer=renderer,
                ocr=reader,
                chunker=sentence.SentenceTextChunker(80, 10),
                embedder=embedder,
                sparse_embedder=sparse_embedder,
                store=store,
                cpu=cpu,
            ),
            ask_question=ask_service.AskQuestion(
                embedder=embedder,
                sparse_embedder=sparse_embedder,
                store=store,
                prompts=prompts.LangChainPrompts(settings.prompts.directory),
                llm=model,
                cpu=cpu,
                top_k=settings.qdrant.top_k,
            ),
            vector_store=store,
            record_extraction=occurrence_service.ExtractAndRecord(
                extract_names,
                recorded,
                occurrence_service.RecordOccurrences(recorded, "fake"),
            ),
            query_occurrences=occurrence_service.QueryOccurrences(recorded),
        )

    return build


@contextlib.contextmanager
def fake_client(
    renderer: page_renderer.PageRenderer | None = None,
    model: llm.Llm | None = None,
    recorded: occurrence_store.InMemoryOccurrenceStore | None = None,
    upload_limit: int = UPLOAD_LIMIT,
    raise_server_exceptions: bool = False,
) -> Iterator[testclient.TestClient]:
    """Runs an app wired to fakes.

    Args:
        renderer: The renderer to wire; a one-page blank renderer by default.
        model: The language model; by default one that is never asked.
        recorded: The occurrence store; an empty one by default.
        upload_limit: Largest accepted upload in bytes.
        raise_server_exceptions: Re-raise unhandled server errors in the
            test instead of returning a 500.

    Yields:
        The running test client.
    """
    settings = config.Settings(
        _env_file=None, upload=config.UploadSettings(max_bytes=upload_limit)
    )
    factory = fake_container(
        renderer or page_renderer_fake.BlankPageRenderer(1),
        model or llm_fake.ScriptedLlm(""),
        recorded or occurrence_store.InMemoryOccurrenceStore(),
    )
    with testclient.TestClient(
        main.create_app(settings, factory),
        raise_server_exceptions=raise_server_exceptions,
    ) as client:
        yield client
