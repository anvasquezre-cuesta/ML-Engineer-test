"""Entry point of ``invoke eval`` and ``invoke eval-compare``."""

import sys

from evaluation import run

sys.exit(run.main(sys.argv[1:]))
