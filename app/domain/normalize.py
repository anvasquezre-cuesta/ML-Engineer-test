"""Normalization of person names for comparison."""


def normalize_name(text: str) -> str:  # noqa: DOC501, DOC503
    """Returns ``text`` in a form that ignores case, accents and OCR noise.

    Letters are casefolded and stripped of accents, including letters such as
    ``ł`` and ``ø`` that Unicode does not decompose. Typographic apostrophes
    become ``'``, punctuation around each token is removed and whitespace is
    collapsed to single spaces.

    Args:
        text: A name as written or recognized.

    Returns:
        The normalized name.
    """
    raise NotImplementedError
