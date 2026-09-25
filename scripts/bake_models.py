"""Downloads the FastEmbed models into the configured cache directory.

The image build runs this once, so a container never downloads a model. The
build fails unless both models then load with downloads forbidden.
"""

import pathlib

import fastembed

from app import config
from app.adapters.fastembed_embedding import embedding
from app.adapters.fastembed_sparse import sparse_embedding


def main() -> None:
    """Downloads both models, then proves they load offline."""
    settings = config.Settings(_env_file=None).embeddings
    online = settings.model_copy(update={"local_files_only": False})
    embedding.FastEmbedEmbedding.load(online)
    sparse_embedding.FastEmbedSparseEmbedding.load(online)
    _add_unpublished_files(settings.cache_dir, settings.sparse_model_name)
    offline = settings.model_copy(update={"local_files_only": True})
    embedding.FastEmbedEmbedding.load(offline)
    sparse_embedding.FastEmbedSparseEmbedding.load(offline)


def _add_unpublished_files(cache_dir: pathlib.Path, model_name: str) -> None:
    """Creates empty files for the ones a model declares but never publishes.

    FastEmbed accepts a cached model offline only if every declared file
    exists. BM25 declares a placeholder model file and a Tamil stop-word list
    that its repository does not contain; neither is read for English text.

    Args:
        cache_dir: The FastEmbed cache directory.
        model_name: Id of the sparse model.
    """
    [description] = [
        model
        for model in fastembed.SparseTextEmbedding.list_supported_models()
        if model["model"] == model_name
    ]
    declared = [description["model_file"], *description["additional_files"]]
    repository = "models--" + model_name.replace("/", "--")
    for snapshot in cache_dir.glob(f"{repository}/snapshots/*"):
        for name in declared:
            (snapshot / name).touch(exist_ok=True)


if __name__ == "__main__":
    main()
