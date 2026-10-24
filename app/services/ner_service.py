"""NER service: extract person names from text via the NerProvider port."""

from typing import Protocol


class NerProvider(Protocol):
    def extract_persons(self, text: str) -> list[str]: ...


def extract_names(text: str, provider: NerProvider) -> list[str]:
    return provider.extract_persons(text)
