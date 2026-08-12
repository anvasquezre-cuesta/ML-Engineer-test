"""Fuzzy-match extracted names against the requested name pairs.

Implement this. Reminders (graded): use a full-string similarity (not a
substring ratio that inflates partial matches), be case-insensitive and
accent-insensitive, and only report matches at or above a configurable
threshold (default 90%). Scores in the response are 0..1.
"""


def fuzzy_match_names(
    extracted_names: list[str], query_names: list[dict]
) -> list[dict]:
    """Return matches as ``{"extracted_name", "matched_name", "score"}``."""
    raise NotImplementedError
