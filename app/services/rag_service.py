"""RAG: chunk text, and answer questions grounded in retrieved context.

Implement this. Reminders (graded): chunking must not cut words in half; the
LLM call needs a timeout and retries; the answer must be grounded in the
retrieved chunks and ``sources`` must reflect what was actually retrieved (no
fabricated sources); handle a missing/failing LLM cleanly.
"""


def chunk_text(text: str, chunk_size: int = 500) -> list[str]:
    """Split text into retrieval chunks without breaking words."""
    raise NotImplementedError


def generate_answer(question: str) -> dict:
    """Retrieve context and return ``{"answer", "sources"}``."""
    raise NotImplementedError
