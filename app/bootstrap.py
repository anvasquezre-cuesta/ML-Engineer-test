"""Composition root: builds adapters and use cases from Settings."""

import dataclasses

from app import config
from app.service_layer import extract


@dataclasses.dataclass(frozen=True, slots=True)
class Container:
    """The use cases the API and the worker call.

    Attributes:
        extract_names: Finds and matches person names in a PDF.
    """

    extract_names: extract.ExtractNames


def build_container(settings: config.Settings) -> Container:  # noqa: DOC501, DOC503
    """Loads every model and client once and wires the use cases.

    Args:
        settings: The service configuration.

    Returns:
        The wired use cases.
    """
    raise NotImplementedError
