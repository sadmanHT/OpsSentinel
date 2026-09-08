from pathlib import Path

from benchmarklab.release import git_blob_sha, verify_release_freeze

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_phase10_release_freeze_matches_repository() -> None:
    proof = verify_release_freeze(REPO_ROOT)
    assert proof["status"] == "ok"
    assert proof["release"] == "OpsSentinel Benchmark v1.0"
    assert proof["scenario_count"] == 50
    assert proof["split_counts"] == {"dev": 30, "validation": 10, "hidden_test": 10}


def test_git_blob_sha_matches_git_object_format(tmp_path: Path) -> None:
    sample = tmp_path / "sample.txt"
    sample.write_text("hello\n", encoding="utf-8")
    assert git_blob_sha(sample) == "ce013625030ba8dba906f756967f9e9ca394464a"
