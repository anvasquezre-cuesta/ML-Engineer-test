import sys

import pytest


@pytest.mark.skipif(sys.platform != "linux", reason="CPU-only builds are configured for Linux")
def test_linux_pytorch_build_uses_cpu():
    import torch
    from sentence_transformers import SentenceTransformer

    assert torch.version.cuda is None
    assert (torch.tensor([2.0]) * 3).item() == 6.0
    assert SentenceTransformer is not None
