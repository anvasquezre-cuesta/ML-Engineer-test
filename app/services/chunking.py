"""Split page text into overlapping windows of whole words.

The unit is a whitespace-separated word, so a word can never be cut in half.
Windows advance by ``chunk_words - overlap_words``; the last window ends at the
last word, so there is no trailing chunk made only of overlap.
"""


class WordWindowChunker:
    def __init__(self, chunk_words: int, overlap_words: int) -> None:
        if chunk_words < 1:
            raise ValueError("chunk_words must be at least 1")
        if not 0 <= overlap_words < chunk_words:
            raise ValueError("overlap_words must be in [0, chunk_words)")
        self._size = chunk_words
        self._step = chunk_words - overlap_words

    def split(self, text: str) -> list[str]:
        words = text.split()
        chunks: list[str] = []
        start = 0
        while start < len(words):
            end = min(start + self._size, len(words))
            chunks.append(" ".join(words[start:end]))
            if end == len(words):
                break
            start += self._step
        return chunks
