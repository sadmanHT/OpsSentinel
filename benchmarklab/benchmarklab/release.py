from __future__ import annotations

from collections import Counter
from hashlib import sha1, sha256
import json
from pathlib import Path
from typing import Any

from benchmarklab.catalog import load_catalog

RELEASE_MANIFEST = Path("benchmarklab/release/opssentinel-benchmark-v1.0.json")


class ReleaseFreezeError(RuntimeError):
    """Raised when the frozen benchmark or evaluator contract has changed."""


def git_blob_sha(path: Path) -> str:
    raw = path.read_bytes()
    header = f"blob {len(raw)}\0".encode()
    return sha1(header + raw).hexdigest()


def load_release_manifest(repo_root: Path) -> dict[str, Any]:
    path = repo_root / RELEASE_MANIFEST
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ReleaseFreezeError("release manifest must be a JSON object")
    return payload


def _string_map(value: Any, field_name: str) -> dict[str, str]:
    if not isinstance(value, dict):
        raise ReleaseFreezeError(f"{field_name} must be an object")
    result: dict[str, str] = {}
    for key, item in value.items():
        if not isinstance(key, str) or not isinstance(item, str):
            raise ReleaseFreezeError(f"{field_name} must map strings to strings")
        result[key] = item
    return result


def verify_release_freeze(repo_root: Path) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    manifest = load_release_manifest(repo_root)
    catalog = load_catalog()
    errors: list[str] = []

    if catalog.benchmark_name != manifest.get("benchmark_name"):
        errors.append("benchmark name changed")
    if catalog.benchmark_version != manifest.get("benchmark_version"):
        errors.append("benchmark version changed")
    if len(catalog.scenarios) != manifest.get("scenario_count"):
        errors.append("scenario count changed")

    difficulty_counts = Counter(item.difficulty.value for item in catalog.scenarios)
    split_counts = Counter(item.split.value for item in catalog.scenarios)
    if dict(difficulty_counts) != manifest.get("difficulty_counts"):
        errors.append("difficulty distribution changed")
    if dict(split_counts) != manifest.get("split_counts"):
        errors.append("split distribution changed")

    sections = ("benchmark_source_blobs", "evaluation_metric_blobs")
    for section in sections:
        for relative_path, expected_sha in _string_map(manifest.get(section), section).items():
            path = repo_root / relative_path
            if not path.is_file():
                errors.append(f"frozen file missing: {relative_path}")
                continue
            actual_sha = git_blob_sha(path)
            if actual_sha != expected_sha:
                errors.append(
                    f"frozen file changed: {relative_path} expected={expected_sha} "
                    f"actual={actual_sha}"
                )

    if errors:
        raise ReleaseFreezeError("; ".join(errors))

    manifest_bytes = (repo_root / RELEASE_MANIFEST).read_bytes()
    return {
        "status": "ok",
        "release": manifest.get("release"),
        "benchmark_version": catalog.benchmark_version,
        "scenario_count": len(catalog.scenarios),
        "difficulty_counts": dict(difficulty_counts),
        "split_counts": dict(split_counts),
        "manifest_sha256": sha256(manifest_bytes).hexdigest(),
    }
