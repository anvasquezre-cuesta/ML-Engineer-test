"""Pinned embedding-model identity and build-time artifact verification."""

import hashlib
from contextlib import contextmanager
import os
from pathlib import Path
import stat
import sys
import tempfile


MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
MODEL_REVISION = "1110a243fdf4706b3f48f1d95db1a4f5529b4d41"
MODEL_DIRECTORY = "/opt/models/all-minilm-l6-v2"
MODEL_DIMENSIONS = 384
MODEL_MAX_TOKENS = 256

# SHA-256 of the exact files at MODEL_REVISION. No executable remote code or
# alternate framework weights are needed for the local sentence-transformer.
MODEL_FILES = {
    "config.json": "953f9c0d463486b10a6871cc2fd59f223b2c70184f49815e7efbcab5d8908b41",
    "config_sentence_transformers.json": "061ca9d39661d6c6d6de5ba27f79a1cd5770ea247f8d46412a68a498dc5ac9f3",
    "sentence_bert_config.json": "fc1993fde0a95c24ec6c022539d41cf6e2f7c9721e5415d6fb6897472a9cd4b7",
    "modules.json": "84e40c8e006c9b1d6c122e02cba9b02458120b5fb0c87b746c41e0207cf642cf",
    "1_Pooling/config.json": "4be450dde3b0273bb9787637cfbd28fe04a7ba6ab9d36ac48e92b11e350ffc23",
    "model.safetensors": "53aa51172d142c89d9012cce15ae4d6cc0ca6895895114379cacb4fab128d9db",
    "tokenizer.json": "be50c3628f2bf5bb5e3a7f17b1f74611b2561a3a27eeab05e5aa30f411572037",
    "tokenizer_config.json": "acb92769e8195aabd29b7b2137a9e6d6e25c476a4f15aa4355c233426c61576b",
    "special_tokens_map.json": "303df45a03609e4ead04bc3dc1536d0ab19b5358db685b6f3da123d05ec200e3",
    "vocab.txt": "07eced375cec144d27c900241f3e339478dec958f92fddbc551f295c992038a3",
}


def verify_model_files(directory: str | Path) -> None:
    """Reject missing or changed artifacts before loading the local model."""
    base = Path(directory)
    for name, expected in MODEL_FILES.items():
        digest = hashlib.sha256()
        try:
            with (base / name).open("rb") as source:
                for block in iter(lambda: source.read(1024 * 1024), b""):
                    digest.update(block)
        except OSError:
            raise ValueError("Pinned embedding model files are unavailable") from None
        if digest.hexdigest() != expected:
            raise ValueError("Pinned embedding model files failed verification")


@contextmanager
def verified_model_snapshot(directory: str | Path):
    """Load only allowlisted, verified bytes, never extra tokenizer/config files.

    Copy and hash in the same pass to close the source-check/source-load race.
    The private snapshot outlives loading and inference, including lazy readers.
    """
    with tempfile.TemporaryDirectory(prefix="embedding-model-") as temporary:
        target = Path(temporary)
        try:
            for name, expected in MODEL_FILES.items():
                source = Path(directory) / name
                fd = os.open(source, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
                with os.fdopen(fd, "rb") as stream:
                    if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                        raise ValueError("Model artifacts must be regular files")
                    destination = target / name
                    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                    digest = hashlib.sha256()
                    with destination.open("xb") as output:
                        for block in iter(lambda: stream.read(1024 * 1024), b""):
                            digest.update(block)
                            output.write(block)
                    if digest.hexdigest() != expected:
                        raise ValueError("Pinned embedding model files failed verification")
        except OSError:
            raise ValueError("Pinned embedding model files are unavailable") from None
        yield target


def provision_model(directory: str | Path) -> None:
    """Download the fixed revision during image construction, then verify it."""
    from huggingface_hub import snapshot_download
    from sentence_transformers import SentenceTransformer

    snapshot_download(
        MODEL_NAME, revision=MODEL_REVISION, local_dir=str(directory), allow_patterns=list(MODEL_FILES),
    )
    with verified_model_snapshot(directory) as snapshot:
        model = SentenceTransformer(str(snapshot), local_files_only=True, trust_remote_code=False, device="cpu")
        if model.get_embedding_dimension() != MODEL_DIMENSIONS or model.max_seq_length != MODEL_MAX_TOKENS:
            raise ValueError("Pinned embedding model has an unexpected configuration")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python embedding_model.py MODEL_DIRECTORY")
    provision_model(sys.argv[1])
