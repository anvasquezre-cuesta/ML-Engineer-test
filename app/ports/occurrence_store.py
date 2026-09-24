"""Ports for the durable record of every name occurrence."""

import abc
from collections.abc import AsyncIterator
from collections.abc import Sequence

from app.domain import occurrences


class OccurrenceWriter(abc.ABC):
    """Writes immutable generations and promotes them atomically.

    Every method may raise ``OccurrenceStoreUnavailableError``.
    """

    @abc.abstractmethod
    async def allocate_order(self, document_key: str) -> int:
        """Reserves the next acceptance order of a document.

        Args:
            document_key: The document.

        Returns:
            A number higher than every order reserved before for it.
        """

    @abc.abstractmethod
    async def head(self, document_key: str) -> occurrences.DocumentHead:
        """Reads the generation a document currently shows, consistently.

        Args:
            document_key: The document.

        Returns:
            The head; its manifest is ``None`` if nothing was promoted.
        """

    @abc.abstractmethod
    async def write_generation(
        self,
        manifest: occurrences.GenerationManifest,
        items: Sequence[occurrences.StoredOccurrence],
    ) -> None:
        """Stores every occurrence of a run, then seals it with its manifest.

        A generation that fails part-way stays unsealed and invisible.

        Args:
            manifest: The seal, written only after every item.
            items: The occurrences of the run.
        """

    @abc.abstractmethod
    async def promote(
        self, manifest: occurrences.GenerationManifest
    ) -> occurrences.PromoteOutcome:
        """Makes a sealed generation current if its order is the highest.

        Args:
            manifest: The sealed generation.

        Returns:
            ``CURRENT``, or ``SUPERSEDED`` when a higher order is current.
        """


class OccurrenceReader(abc.ABC):
    """Reads the current generation of each document.

    Every method may raise ``OccurrenceStoreUnavailableError``.
    """

    @abc.abstractmethod
    def documents(self) -> AsyncIterator[occurrences.DocumentHead]:
        """Lists every document that has a current generation.

        Returns:
            The heads, in no particular order.
        """

    @abc.abstractmethod
    def current(
        self, head: occurrences.DocumentHead
    ) -> AsyncIterator[occurrences.StoredOccurrence]:
        """Reads every occurrence of a document's current generation.

        Args:
            head: The document's head, read beforehand.

        Returns:
            The occurrences in ordinal order.
        """

    @abc.abstractmethod
    async def history(
        self, document_key: str
    ) -> list[occurrences.GenerationManifest]:
        """Lists every sealed generation of a document.

        Args:
            document_key: The document.

        Returns:
            The manifests, oldest order first.
        """
