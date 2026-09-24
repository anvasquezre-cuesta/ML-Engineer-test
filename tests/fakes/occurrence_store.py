"""In-memory occurrence store with the conditional rules of the real one."""

from collections.abc import AsyncIterator
from collections.abc import Sequence

from app.domain import errors
from app.domain import occurrences
from app.ports import occurrence_store

Items = list[occurrences.StoredOccurrence]


class InMemoryOccurrenceStore(
    occurrence_store.OccurrenceWriter, occurrence_store.OccurrenceReader
):
    """Keeps generations in dicts; can fail part-way through a write.

    Attributes:
        fail_after: Items written before the next write fails; ``None``
            never fails.
        lose_on_read: Items of each generation that reads leave out.
        fail_reads_after: Documents read before the next read fails;
            ``None`` never fails.
    """

    def __init__(self) -> None:
        """Initializes an empty store."""
        self.fail_after: int | None = None
        self.lose_on_read = 0
        self.fail_reads_after: int | None = None
        self._reads = 0
        self._orders: dict[str, int] = {}
        self._items: dict[tuple[str, str], Items] = {}
        self._sealed: dict[tuple[str, str], occurrences.GenerationManifest] = {}
        self._current: dict[str, occurrences.GenerationManifest] = {}

    async def allocate_order(self, document_key: str) -> int:
        """Increments the document's order counter.

        Args:
            document_key: The document.

        Returns:
            The new order.
        """
        self._orders[document_key] = self._orders.get(document_key, 0) + 1
        return self._orders[document_key]

    async def head(self, document_key: str) -> occurrences.DocumentHead:
        """Returns the document's current manifest.

        Args:
            document_key: The document.

        Returns:
            The head.
        """
        return occurrences.DocumentHead(
            document_key, self._current.get(document_key)
        )

    async def write_generation(
        self,
        manifest: occurrences.GenerationManifest,
        items: Sequence[occurrences.StoredOccurrence],
    ) -> None:
        """Stores the items one by one, then the seal.

        Args:
            manifest: The seal.
            items: The occurrences.

        Raises:
            errors.OccurrenceStoreUnavailableError: When ``fail_after``
                items have been written.
        """
        key = (manifest.document_key, manifest.generation)
        stored = self._items.setdefault(key, [])
        for count, item in enumerate(items):
            if self.fail_after is not None and count == self.fail_after:
                self.fail_after = None
                raise errors.OccurrenceStoreUnavailableError()
            stored.append(item)
        self._sealed[key] = manifest

    async def promote(
        self, manifest: occurrences.GenerationManifest
    ) -> occurrences.PromoteOutcome:
        """Makes a sealed generation current if its order is higher.

        Args:
            manifest: The sealed generation.

        Returns:
            The outcome.
        """
        assert (manifest.document_key, manifest.generation) in self._sealed
        current = self._current.get(manifest.document_key)
        if current is not None and current.order >= manifest.order:
            return occurrences.PromoteOutcome.SUPERSEDED
        self._current[manifest.document_key] = manifest
        return occurrences.PromoteOutcome.CURRENT

    async def documents(self) -> AsyncIterator[occurrences.DocumentHead]:
        """Yields every promoted document.

        Yields:
            The heads.
        """
        for key, manifest in list(self._current.items()):
            yield occurrences.DocumentHead(key, manifest)

    async def current(
        self, head: occurrences.DocumentHead
    ) -> AsyncIterator[occurrences.StoredOccurrence]:
        """Yields the items of the head's generation.

        Args:
            head: The document's head.

        Yields:
            The occurrences in ordinal order.

        Raises:
            errors.OccurrenceStoreUnavailableError: When
                ``fail_reads_after`` documents were already read.
        """
        if head.manifest is None:
            return
        if self._reads == self.fail_reads_after:
            raise errors.OccurrenceStoreUnavailableError()
        self._reads += 1
        key = (head.document_key, head.manifest.generation)
        items = self._items[key]
        for item in items[: len(items) - self.lose_on_read]:
            yield item

    async def history(
        self, document_key: str
    ) -> list[occurrences.GenerationManifest]:
        """Lists the sealed generations of a document.

        Args:
            document_key: The document.

        Returns:
            The manifests, oldest order first.
        """
        sealed = [m for (k, _), m in self._sealed.items() if k == document_key]
        return sorted(sealed, key=lambda m: m.order)
