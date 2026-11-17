"""Limits shared by the private JSON-lines NER worker protocol."""

# A malformed/huge worker response must not grow an unbounded pipe buffer.
MAX_NER_RESPONSE_BYTES = 16 * 1024 * 1024
