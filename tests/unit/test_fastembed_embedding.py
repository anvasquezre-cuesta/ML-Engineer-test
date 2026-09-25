"""FastEmbed adapter: a missing model fails at startup, never downloads."""

import pathlib

import pytest

from app import config
from app.adapters.fastembed_embedding import embedding
from app.domain import errors


def test_missing_model_fails_to_load_without_downloading(
    tmp_path: pathlib.Path,
) -> None:
    settings = config.EmbeddingSettings(
        cache_dir=tmp_path, local_files_only=True
    )

    with pytest.raises(errors.EmbeddingError):
        embedding.FastEmbedEmbedding.load(settings)

    assert list(tmp_path.iterdir()) == []
