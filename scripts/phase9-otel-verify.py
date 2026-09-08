#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

TRACE_ID_RE = re.compile(r"^[0-9a-f]{32}$")
RESOURCE_MARKER_RE = re.compile(r"(?=ResourceSpans\s+#?\d+)", re.IGNORECASE)
MCP_SPAN_RE = re.compile(r"mcp\.tool\.[A-Za-z0-9_.-]+")
CLIENT_KIND_RE = re.compile(r"Kind\s*:\s*(?:SpanKind\.)?Client", re.IGNORECASE)
SERVER_KIND_RE = re.compile(r"Kind\s*:\s*(?:SpanKind\.)?Server", re.IGNORECASE)

REQUIRED_SERVICES = (
    "opssentinel-frontend",
    "opssentinel-backend",
    "chaoslab-checkout",
)
REQUIRED_SPANS = (
    "frontend.start_investigation",
    "agent.investigation",
    "agent.node.execute_tool",
    "agent.node.store_evidence",
)
FORBIDDEN_FRAGMENTS = (
    "legal observable evidence only",
    "scenario_id",
    "ground_truth",
    "hidden_truth",
    "must-not-enter",
)


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def _trace_chunks(log_text: str, trace_id: str) -> list[str]:
    chunks = [chunk for chunk in RESOURCE_MARKER_RE.split(log_text) if chunk.strip()]
    selected = [chunk for chunk in chunks if trace_id in chunk.lower()]
    if selected:
        return selected

    lowered = log_text.lower()
    windows: list[str] = []
    cursor = 0
    while True:
        index = lowered.find(trace_id, cursor)
        if index < 0:
            break
        start = max(0, index - 6_000)
        end = min(len(log_text), index + 6_000)
        windows.append(log_text[start:end])
        cursor = index + len(trace_id)
    return windows


def _service_chunks(chunks: list[str], service: str) -> list[str]:
    return [chunk for chunk in chunks if service in chunk]


def _check_required(condition: bool, message: str, failures: list[str]) -> bool:
    if not condition:
        failures.append(message)
    return condition


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify one Phase 9.4 distributed OTel trace.")
    parser.add_argument("--browser", required=True, type=Path)
    parser.add_argument("--collector-log", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    browser = _load_json(args.browser)
    trace_id = str(browser.get("trace_id") or "").lower()
    run_id = str(browser.get("run_id") or "")
    status = str(browser.get("status") or "")
    if not TRACE_ID_RE.fullmatch(trace_id):
        raise ValueError("browser artifact contains an invalid trace id")
    if status != "paused":
        raise ValueError(f"browser proof must be paused, observed {status!r}")

    log_text = args.collector_log.read_text(encoding="utf-8", errors="replace")
    chunks = _trace_chunks(log_text, trace_id)
    failures: list[str] = []
    _check_required(bool(chunks), "collector log has no block for browser trace id", failures)
    trace_text = "\n".join(chunks)
    lower_trace_text = trace_text.lower()

    observed_services = sorted(
        service for service in REQUIRED_SERVICES if service in trace_text
    )
    service_checks = {
        service: _check_required(
            service in trace_text,
            f"required service {service} is missing from trace",
            failures,
        )
        for service in REQUIRED_SERVICES
    }

    observed_spans = sorted(span for span in REQUIRED_SPANS if span in trace_text)
    span_checks = {
        span: _check_required(
            span in trace_text,
            f"required span {span} is missing from trace",
            failures,
        )
        for span in REQUIRED_SPANS
    }
    mcp_matches = sorted(set(MCP_SPAN_RE.findall(trace_text)))
    mcp_span_present = _check_required(
        bool(mcp_matches),
        "trace does not contain an MCP tool span",
        failures,
    )

    backend_chunks = _service_chunks(chunks, "opssentinel-backend")
    chaos_chunks = _service_chunks(chunks, "chaoslab-checkout")
    backend_client_present = _check_required(
        any(CLIENT_KIND_RE.search(chunk) for chunk in backend_chunks),
        "backend trace block does not contain an HTTP client span",
        failures,
    )
    chaos_server_present = _check_required(
        any(SERVER_KIND_RE.search(chunk) for chunk in chaos_chunks),
        "chaoslab-checkout trace block does not contain a server span",
        failures,
    )
    target_redaction_present = _check_required(
        "opssentinel.http.request_target_redacted" in trace_text
        and "[redacted]" in trace_text,
        "trace does not prove HTTP client target redaction",
        failures,
    )

    forbidden_hits = sorted(
        fragment for fragment in FORBIDDEN_FRAGMENTS if fragment in lower_trace_text
    )
    no_forbidden_fragments = _check_required(
        not forbidden_hits,
        f"trace contains forbidden fragments: {forbidden_hits}",
        failures,
    )
    no_tool_arguments = _check_required(
        '"arguments"' not in lower_trace_text and "arguments:" not in lower_trace_text,
        "trace contains a serialized tool-arguments field",
        failures,
    )
    no_unredacted_query = _check_required(
        not re.search(r"(?:url\.query|http\.target).*?(?:Str\(|=).*?(?!\[redacted\])", trace_text),
        "trace contains a potentially unredacted request-target attribute",
        failures,
    )

    checks = {
        "trace_id_observed": bool(chunks),
        "services": service_checks,
        "spans": span_checks,
        "mcp_span_present": mcp_span_present,
        "backend_client_span_present": backend_client_present,
        "chaoslab_server_span_present": chaos_server_present,
        "http_request_target_redaction_present": target_redaction_present,
        "no_forbidden_fragments": no_forbidden_fragments,
        "no_tool_arguments": no_tool_arguments,
        "no_unredacted_query_target": no_unredacted_query,
    }
    summary = {
        "trace_id": trace_id,
        "run_id": run_id,
        "status": status,
        "observed_services": observed_services,
        "observed_required_spans": observed_spans,
        "observed_mcp_spans": mcp_matches,
        "checks": checks,
        "passed": not failures,
        "failures": failures,
    }
    args.output.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    if failures:
        for failure in failures:
            print(f"FAIL: {failure}")
        return 1
    print(f"Phase 9.4 distributed trace verified: {trace_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
