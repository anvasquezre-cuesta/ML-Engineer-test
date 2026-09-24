"""Value objects of ingestion and retrieval-augmented answering."""

from dataclasses import dataclass

type Vector = tuple[float, ...]


@dataclass(frozen=True, slots=True)
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


@dataclass(frozen=True, slots=True)
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


@dataclass(frozen=True, slots=True)
class EmbeddedChunk:
    """A chunk together with its embedding.

    Attributes:
        chunk: The chunk.
        vector: Its embedding.
    """

    chunk: Chunk
    vector: Vector


@dataclass(frozen=True, slots=True)
class ScoredChunk:
    """A chunk returned by similarity search.

    Attributes:
        chunk: The retrieved chunk.
        score: Similarity to the query; higher is closer.
    """

    chunk: Chunk
    score: float


@dataclass(frozen=True, slots=True)
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


@dataclass(frozen=True, slots=True)
class LlmPrompt:
    """Instructions and user message sent to the language model.

    Attributes:
        system: Instructions that constrain the answer.
        user: The question together with the retrieved context.
    """

    system: str
    user: str
