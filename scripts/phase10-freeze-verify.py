from __future__ import annotations

import json
from pathlib import Path

from benchmarklab.release import verify_release_freeze

REPO_ROOT = Path(__file__).resolve().parents[1]


if __name__ == "__main__":
    proof = verify_release_freeze(REPO_ROOT)
    print(json.dumps(proof, indent=2, sort_keys=True))
