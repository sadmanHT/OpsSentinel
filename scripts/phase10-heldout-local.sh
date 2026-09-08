#!/usr/bin/env bash
set -euo pipefail

OUTPUT_DIR="${PHASE10_HELDOUT_OUTPUT_DIR:-phase10-heldout}"
BACKEND_LOG="/tmp/phase10-backend.log"
CHAOSLAB_LOG="/tmp/phase10-chaoslab.log"

cleanup() {
  docker compose down -v --remove-orphans || true
}
trap cleanup EXIT

printf '%s\n' 'Phase 10 local held-out reproduction.'
printf '%s\n' 'The first successful preregistered CI run remains the authoritative research snapshot.'
printf '%s\n' 'This command is a reproducibility/regression run; do not replace the published result because a rerun differs.'

rm -rf "$OUTPUT_DIR"
python -m pip install -e 'benchmarklab[dev]' -e 'evaluationlab[dev]'
python scripts/phase10-freeze-verify.py
ruff check benchmarklab scripts/phase10-heldout-evaluation.py
mypy benchmarklab/benchmarklab
pytest benchmarklab/tests/test_phase10_release_freeze.py benchmarklab/tests/test_phase10_final_report.py

docker compose down -v --remove-orphans || true
docker compose build
docker compose up -d

healthy=0
for _attempt in $(seq 1 60); do
  if curl --fail --silent http://127.0.0.1:8000/health >/dev/null \
    && curl --fail --silent http://127.0.0.1:8100/health >/dev/null \
    && curl --fail --silent http://127.0.0.1:8080/health >/dev/null \
    && curl --fail --silent http://127.0.0.1:8101/health >/dev/null \
    && curl --fail --silent http://127.0.0.1:8102/health >/dev/null \
    && curl --fail --silent http://127.0.0.1:8103/health >/dev/null \
    && curl --fail --silent http://127.0.0.1:8104/health >/dev/null; then
    healthy=1
    break
  fi
  sleep 2
done

if [[ "$healthy" -ne 1 ]]; then
  docker compose ps
  docker compose logs --no-color
  exit 1
fi

PHASE10_HELDOUT_OUTPUT_DIR="$OUTPUT_DIR" python scripts/phase10-heldout-evaluation.py

curl --fail --silent http://127.0.0.1:8100/faults | grep '^\[\]$'
docker compose logs backend --no-color > "$BACKEND_LOG"
docker compose logs chaoslab-controller checkout inventory payment worker gateway --no-color > "$CHAOSLAB_LOG"

if grep -E 'Traceback|Unhandled exception|CRITICAL' "$BACKEND_LOG"; then
  cat "$BACKEND_LOG"
  exit 1
fi
if grep -E 'Traceback|Unhandled exception|CRITICAL' "$CHAOSLAB_LOG"; then
  cat "$CHAOSLAB_LOG"
  exit 1
fi

printf 'Phase 10 held-out reproduction artifact: %s\n' "$OUTPUT_DIR"
