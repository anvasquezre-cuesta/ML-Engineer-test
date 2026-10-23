"""The API contract in ``app/models/schemas.py`` is fixed: fields may be added, never changed.

``tests/fixtures/original_contract_schema.json`` holds the JSON schemas of the models
exactly as the skeleton provided them (commit 7acb727). Every original model must still
exist with the same fields, types, constraints and required set; only descriptions and
docstrings may differ, and any added field must be optional so old clients keep working.
"""

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from app.models import schemas

ORIGINAL = json.loads(
    (Path(__file__).parents[1] / "fixtures" / "original_contract_schema.json").read_text(
        encoding="utf-8"
    )
)["models"]

DOCUMENTATION_KEYS = {"description"}


def _without_docs(node: Any) -> Any:
    if isinstance(node, dict):
        return {k: _without_docs(v) for k, v in node.items() if k not in DOCUMENTATION_KEYS}
    if isinstance(node, list):
        return [_without_docs(v) for v in node]
    return node


def _current(name: str) -> dict[str, Any]:
    model = getattr(schemas, name, None)
    assert isinstance(model, type) and issubclass(model, BaseModel), f"{name} was removed"
    return model.model_json_schema()


@pytest.mark.parametrize("name", sorted(ORIGINAL))
def test_original_model_still_exists_with_the_same_fields(name: str) -> None:
    original, current = _without_docs(ORIGINAL[name]), _without_docs(_current(name))

    for field, spec in original["properties"].items():
        assert field in current["properties"], f"{name}.{field} was removed or renamed"
        assert current["properties"][field] == spec, f"{name}.{field} changed type or constraint"
    assert set(current.get("required", [])) == set(original.get("required", [])), (
        f"{name}: the set of required fields changed"
    )


@pytest.mark.parametrize("name", sorted(ORIGINAL))
def test_added_fields_are_optional(name: str) -> None:
    current = _current(name)
    added = set(current["properties"]) - set(ORIGINAL[name]["properties"])

    assert not added & set(current.get("required", [])), f"{name}: new required field {added}"


def test_the_endpoints_still_use_the_original_models() -> None:
    from app.api import extract, health, rag

    used = {
        route.response_model.__name__  # type: ignore[attr-defined]
        for module in (extract, health, rag)
        for route in module.router.routes
        if getattr(route, "response_model", None) is not None
    }

    assert {"ExtractionResponse", "IngestResponse", "RAGResponse", "HealthResponse"} <= used
