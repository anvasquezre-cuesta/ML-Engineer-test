"""Value objects of ingestion and retrieval-augmented answering."""

import dataclasses
import enum

type Vector = tuple[float, ...]


@dataclasses.dataclass(frozen=True, slots=True)
class SourcePage:
    """OCR text of one page of an ingested document.

    Attributes:
        document_key: Identity of the document (filename or client id).
        content_hash: SHA-256 hex digest of the PDF bytes.
        page_number: 0-based page index.
        text: The page text.
    """

    document_key: str
    content_hash: str
    page_number: int
    text: str


@dataclasses.dataclass(frozen=True, slots=True)
class Chunk:
    """A contiguous slice of one page's text that never splits a word.

    Attributes:
        document_key: Identity of the document.
        content_hash: SHA-256 hex digest of the PDF bytes.
        page_number: 0-based page index.
        chunk_index: Position of the chunk within its page.
        start_char: Offset of the chunk's first character in the page text.
        end_char: Offset one past the chunk's last character.
        text: The chunk text.
        strategy: Name of the chunking strategy that produced it.
    """

    document_key: str
    content_hash: str
    page_number: int
    chunk_index: int
    start_char: int
    end_char: int
    text: str
    strategy: str


@dataclasses.dataclass(frozen=True, slots=True)
class SparseVector:
    """Term weights of a text, e.g. BM25 term frequencies.

    Attributes:
        indices: Term ids, one per non-zero weight.
        values: The weights, aligned with ``indices``.
    """

    indices: tuple[int, ...]
    values: tuple[float, ...]


@dataclasses.dataclass(frozen=True, slots=True)
class EmbeddedChunk:
    """A chunk together with its dense and sparse embeddings.

    Attributes:
        chunk: The chunk.
        vector: Its dense embedding.
        sparse: Its term weights for keyword search.
    """

    chunk: Chunk
    vector: Vector
    sparse: SparseVector


@dataclasses.dataclass(frozen=True, slots=True)
class SearchQuery:
    """A question embedded for hybrid search.

    Attributes:
        dense: The question's dense embedding.
        sparse: The question's term weights.
    """

    dense: Vector
    sparse: SparseVector


@dataclasses.dataclass(frozen=True, slots=True)
class ScoredChunk:
    """A chunk returned by similarity search.

    Attributes:
        chunk: The retrieved chunk.
        score: Similarity to the query; higher is closer.
    """

    chunk: Chunk
    score: float


@dataclasses.dataclass(frozen=True, slots=True)
class DocumentRecord:
    """What the vector store holds for one ingested document.

    Attributes:
        document_key: Identity of the document.
        content_hash: SHA-256 hex digest of the ingested PDF bytes.
        chunk_count: Number of chunks stored for the document.
    """

    document_key: str
    content_hash: str
    chunk_count: int


@dataclasses.dataclass(frozen=True, slots=True)
class Passage:
    """A retrieved chunk as numbered in the answer prompt.

    Attributes:
        number: 1-based position the model cites as ``[number]``.
        document_key: Identity of the chunk's document.
        page: 1-based page number.
        text: The chunk text with bracketed numbers defused.
    """

    number: int
    document_key: str
    page: int
    text: str


@dataclasses.dataclass(frozen=True, slots=True)
class LlmPrompt:
    """Instructions and user message sent to the language model.

    Attributes:
        system: Instructions that constrain the answer.
        user: The question together with the retrieved context.
    """

    system: str
    user: str


class IngestStatus(enum.StrEnum):
    """What an ingest did with a document.

    Attributes:
        INGESTED: The document was new and its chunks were stored.
        UNCHANGED: The same content was already stored; nothing was written.
        REPLACED: Older content under the same key was deleted first.
    """

    INGESTED = "ingested"
    UNCHANGED = "unchanged"
    REPLACED = "replaced"


@dataclasses.dataclass(frozen=True, slots=True)
class IngestResult:
    """Outcome of ingesting one document.

    Attributes:
        document_key: Identity of the document.
        status: What the ingest did.
        chunks_stored: Chunks stored for the document afterwards.
    """

    document_key: str
    status: IngestStatus
    chunks_stored: int
