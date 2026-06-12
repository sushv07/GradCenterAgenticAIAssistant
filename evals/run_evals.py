#!/usr/bin/env python3
"""
evals/run_evals.py
Phase 2A/2C evaluation harness for the CSULB Grad Center AI Assistant.

Asserts: route correctness, route reason, retrieval event structure,
         fallback behavior, advisor outcome, store_rebuild (advisory).
Reports: backend inference — expected vs actual backend, backend_match,
         vector_db_touched (informational, does not gate pass/fail).
Does NOT assert: response content, answer quality, multi-turn behavior.

Usage (from project root):
    python -m evals.run_evals
    python evals/run_evals.py [--dataset PATH] [--skip-known-failures]
                               [--ci] [--no-archive] [--no-warmup] [--verbose]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ── Project root on sys.path ──────────────────────────────────────────────────
_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import gradcenter_logging
from gradcenter_logging import new_request_id, set_request_id
import orchestrator

# ── Paths ─────────────────────────────────────────────────────────────────────
_EVALS_DIR       = Path(__file__).parent
_REPORTS_DIR     = _EVALS_DIR / "reports"
_DEFAULT_DATASET = _EVALS_DIR / "golden_queries.json"

# ── Log capture ───────────────────────────────────────────────────────────────
# All production modules import emit via `from gradcenter_logging import emit`,
# which binds the original function object in each module's namespace.
# Replacing `gradcenter_logging.emit` after import does NOT intercept those
# calls.  Instead, we attach a logging.Handler to the "gradcenter" logger:
# every emit() call routes through _logger.log(), so the handler intercepts
# every event regardless of how emit was imported.

import logging as _logging

_capture_buffers: dict[str, list[dict]] = {}
_capture_handler: "_CaptureHandler | None" = None


class _CaptureHandler(_logging.Handler):
    def emit(self, record: _logging.LogRecord) -> None:
        try:
            event_dict = json.loads(record.getMessage())
            rid = event_dict.get("request_id", "")
            if rid in _capture_buffers:
                _capture_buffers[rid].append(event_dict)
        except Exception:
            pass


def _install_capture_hook() -> None:
    global _capture_handler
    if _capture_handler is not None:
        return  # idempotent
    _capture_handler = _CaptureHandler()
    _capture_handler.setLevel(_logging.DEBUG)
    _logging.getLogger("gradcenter").addHandler(_capture_handler)


def _start_capture(rid: str) -> None:
    _capture_buffers[rid] = []


def _stop_capture(rid: str) -> list[dict]:
    return _capture_buffers.pop(rid, [])


# ── Assertion helpers ─────────────────────────────────────────────────────────

def _ar(name: str, expected: Any, actual: Any, passed: bool, message: str = "") -> dict:
    return {
        "name":     name,
        "expected": expected,
        "actual":   actual,
        "passed":   passed,
        "message":  message if not passed else "",
    }


def _assert_route(response: dict, expected_route: str) -> dict:
    actual = response.get("route")
    passed = actual == expected_route
    return _ar("route", expected_route, actual, passed,
               f"expected={expected_route!r} actual={actual!r}")


def _assert_route_reason(events: list[dict], expected: str) -> dict:
    rd = [e for e in events if e["event"] == "route.decision"]
    if not rd:
        return _ar("route_reason", expected, None, False,
                   "no route.decision event captured")
    actual = rd[0].get("reason")
    passed = actual == expected
    return _ar("route_reason", expected, actual, passed,
               f"expected={expected!r} actual={actual!r}")


def _assert_retrieval_events(events: list[dict], expected_list: list[dict]) -> list[dict]:
    ret_events = [e for e in events if e["event"] == "retrieval.result"]

    if not expected_list:
        passed = len(ret_events) == 0
        return [_ar(
            "retrieval_events_empty", 0, len(ret_events), passed,
            f"expected 0 retrieval.result events, got {len(ret_events)}"
        )]

    results = []
    for i, exp in enumerate(expected_list):
        matches = [
            e for e in ret_events
            if e.get("page_type") == exp["page_type"]
            and e.get("k_requested") == exp["k_requested"]
        ]
        name = f"retrieval_events[{i}]"
        if not matches:
            results.append(_ar(
                name, exp, None, False,
                f"no retrieval.result for page_type={exp['page_type']!r} "
                f"k_requested={exp['k_requested']}"
            ))
        else:
            num_returned = matches[0].get("num_returned", 0)
            passed       = num_returned >= exp["min_returned"]
            actual_snap  = {
                "page_type":    matches[0].get("page_type"),
                "k_requested":  matches[0].get("k_requested"),
                "num_returned": num_returned,
            }
            results.append(_ar(
                name, exp, actual_snap, passed,
                f"num_returned={num_returned} < min_returned={exp['min_returned']}"
            ))
    return results


def _assert_fallback(events: list[dict], expected: bool | None) -> dict:
    if expected is None:
        return _ar("fallback", None, None, True,
                   "skipped — fallback_used is null for this route")

    tool_events  = [e for e in events if e["event"] == "tool.result"]
    any_fallback = any(e.get("fallback_used") is True for e in tool_events)

    if expected:
        return _ar("fallback", True, any_fallback, any_fallback,
                   "no tool.result event had fallback_used=True")
    else:
        return _ar("fallback", False, any_fallback, not any_fallback,
                   "unexpected fallback_used=True in tool.result")


def _assert_advisor_outcome(events: list[dict], expected_advisor: dict | None) -> dict | None:
    if not expected_advisor:
        return None
    adv_events = [e for e in events if e["event"] == "advisor.match"]
    if not adv_events:
        return _ar("advisor_outcome", expected_advisor.get("outcome"), None, False,
                   "no advisor.match event captured")
    actual   = adv_events[0].get("outcome")
    expected = expected_advisor.get("outcome")
    passed   = actual == expected
    return _ar("advisor_outcome", expected, actual, passed,
               f"expected={expected!r} actual={actual!r}")


def _assert_store_rebuild_advisory(events: list[dict], expected: bool) -> dict:
    builds = [
        e for e in events
        if e["event"] == "store.lifecycle"
        and e.get("lifecycle_event") == "build_start"
    ]
    actual = len(builds) > 0
    passed = actual == expected
    return _ar(
        "store_rebuild_advisory", expected, actual, passed,
        f"(advisory) expected={expected} actual={actual}"
    )


# ── Backend inference (informational — does not gate pass/fail) ───────────────

_CHROMA_PAGE_TYPES = frozenset({
    "deadlines", "eligibility", "application_process", "program_application",
})

_BACKEND_BUCKETS = (
    "chroma", "faq_rag", "rapidfuzz",
    "admissions_json", "json_keyword", "admissions_rag", "unknown",
)


def _infer_backend(
    events: list[dict],
    response: dict,
    expected_backend: str,
) -> tuple[str, bool]:
    """
    Infer actual_backend from captured log events and the response route.
    Returns (actual_backend, vector_db_touched).

    Inference priority (first match wins):
      1. retrieval.result with a ChromaDB page_type  → chroma         (vdb=True)
      2. advisor.match + route==advisor              → rapidfuzz       (vdb=False)
      3. route==guidance, no retrieval               → admissions_json (vdb=False)
      4. route==answer, no retrieval                 → json_keyword    (vdb=False)
      5. route==next_steps + faq_rag.query event     → faq_rag         (vdb=True)
      6. route==next_steps + faq_rag store.lifecycle → faq_rag         (vdb=True)
      7. route==next_steps, warm store (no event)    → *_inferred      (vdb=True/False)
      8. fallback                                    → unknown
    """
    route        = response.get("route")
    ret_events   = [e for e in events if e["event"] == "retrieval.result"]
    adv_events   = [e for e in events if e["event"] == "advisor.match"]
    store_events = [e for e in events if e["event"] == "store.lifecycle"]

    # Rule 1: ChromaDB retrieval
    chroma_hits = {e.get("page_type") for e in ret_events} & _CHROMA_PAGE_TYPES
    if chroma_hits:
        return "chroma", True

    # Rule 2: Fuzzy advisor match
    if adv_events and route == "advisor":
        return "rapidfuzz", False

    # Rule 3: Guidance with no retrieval
    if route == "guidance" and not ret_events:
        return "admissions_json", False

    # Rule 4: Answer with no retrieval
    if route == "answer" and not ret_events:
        return "json_keyword", False

    # Rule 5/6/7: Next-steps path
    if route == "next_steps":
        # Rule 5: per-query faq_rag.query event present (Phase 3A instrumentation)
        faq_query_events = [e for e in events if e["event"] == "faq_rag.query"]
        if faq_query_events:
            return "faq_rag", True
        # Rule 6: store.lifecycle build event (first request, store was cold)
        faq_store = [e for e in store_events if e.get("store_type") == "faq_rag"]
        if faq_store:
            return "faq_rag", True
        # Rule 7: warm store, no per-query event — fall back to expected as ground truth.
        if expected_backend == "faq_rag":
            return "faq_rag_inferred", True
        if expected_backend == "admissions_rag":
            return "admissions_rag_inferred", False

    return "unknown", bool(ret_events)


def _check_backend(
    events: list[dict],
    response: dict,
    expected_backend: str,
) -> dict:
    """
    Run backend inference and return a backend_info dict with four fields:
    expected_backend, actual_backend, backend_match, vector_db_touched.
    backend_match is True for exact matches AND for inferred variants that
    resolve to the correct base (faq_rag_inferred ~ faq_rag, etc.).
    """
    actual_backend, vector_db_touched = _infer_backend(
        events, response, expected_backend
    )
    backend_match = (
        actual_backend == expected_backend
        or (actual_backend == "faq_rag_inferred"       and expected_backend == "faq_rag")
        or (actual_backend == "admissions_rag_inferred" and expected_backend == "admissions_rag")
    )
    return {
        "expected_backend":  expected_backend,
        "actual_backend":    actual_backend,
        "backend_match":     backend_match,
        "vector_db_touched": vector_db_touched,
    }


# ── Per-case runner ───────────────────────────────────────────────────────────

def _run_case(case: dict) -> dict:
    cid   = case["id"]
    query = case["query"]
    exp   = case.get("expected", {})

    rid = new_request_id()
    set_request_id(rid)
    _start_capture(rid)

    t0        = time.perf_counter()
    error_str = None
    response: dict = {}
    try:
        response = orchestrator.run(query, session_id=f"eval_{cid}")
    except Exception as exc:
        error_str = repr(exc)
    elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)

    events = _stop_capture(rid)

    bi = _check_backend(events, response, exp.get("backend", ""))

    if error_str:
        return {
            "id": cid, "query": query,
            "status": "ERROR",
            "known_failure": case.get("known_failure", False),
            "elapsed_ms": elapsed_ms,
            "assertions": [],
            "captured_events": _bucket_events(events),
            "error": error_str,
            "expected_backend":  exp.get("backend", ""),
            "actual_backend":    "unknown",
            "backend_match":     False,
            "vector_db_touched": False,
        }

    assertions: list[dict] = []

    assertions.append(_assert_route(response, exp.get("route", "")))
    assertions.append(_assert_route_reason(events, exp.get("route_reason", "")))
    assertions.extend(_assert_retrieval_events(events, exp.get("retrieval_events", [])))
    assertions.append(_assert_fallback(events, exp.get("fallback_used")))

    adv = _assert_advisor_outcome(events, exp.get("advisor"))
    if adv:
        assertions.append(adv)

    if "store_rebuild" in exp:
        assertions.append(
            _assert_store_rebuild_advisory(events, exp["store_rebuild"])
        )

    # store_rebuild_advisory never gates status
    gating = [a for a in assertions if a["name"] != "store_rebuild_advisory"]
    any_failed = any(not a["passed"] for a in gating)

    if any_failed:
        status = "KNOWN_FAIL" if case.get("known_failure", False) else "FAIL"
    else:
        status = "PASS"

    return {
        "id": cid, "query": query,
        "status": status,
        "known_failure": case.get("known_failure", False),
        "elapsed_ms": elapsed_ms,
        "assertions": assertions,
        "captured_events": _bucket_events(events),
        "error": None,
        "expected_backend":  bi["expected_backend"],
        "actual_backend":    bi["actual_backend"],
        "backend_match":     bi["backend_match"],
        "vector_db_touched": bi["vector_db_touched"],
    }


def _bucket_events(events: list[dict]) -> dict:
    names = ("route.decision", "retrieval.result", "tool.result",
             "advisor.match", "store.lifecycle",
             "faq_rag.query", "keyword.retrieval", "keyword.result")
    return {n: [e for e in events if e["event"] == n] for n in names}


# ── Report ────────────────────────────────────────────────────────────────────

def _percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    s   = sorted(values)
    idx = (p / 100) * (len(s) - 1)
    lo  = int(idx)
    hi  = min(lo + 1, len(s) - 1)
    return round(s[lo] + (idx - lo) * (s[hi] - s[lo]), 1)


def _build_backend_summary(results: list[dict]) -> dict:
    """
    Aggregate backend inference results across all non-SKIP cases.
    Inferred variants (faq_rag_inferred, admissions_rag_inferred) are folded
    into their base bucket for count purposes.
    """
    non_skip    = [r for r in results if r.get("status") != "SKIP"]
    n           = len(non_skip)
    counts      = {b: 0 for b in _BACKEND_BUCKETS}
    match_count = 0
    vdb_count   = 0
    mismatches: list[dict] = []

    for r in non_skip:
        actual = r.get("actual_backend") or "unknown"
        # Fold inferred suffixes into base bucket
        base = actual.removesuffix("_inferred") if actual.endswith("_inferred") else actual
        counts[base if base in counts else "unknown"] += 1

        if r.get("backend_match"):
            match_count += 1
        else:
            mismatches.append({
                "id":               r["id"],
                "expected_backend": r.get("expected_backend", ""),
                "actual_backend":   actual,
            })

        if r.get("vector_db_touched"):
            vdb_count += 1

    return {
        "counts":                counts,
        "backend_match":         match_count,
        "backend_match_rate":    round(match_count / n, 4) if n else 0.0,
        "vector_db_touched":     vdb_count,
        "vector_db_touched_pct": round(vdb_count / n * 100, 1) if n else 0.0,
        "mismatches":            mismatches,
    }


def _build_report(
    results: list[dict],
    dataset_path: str,
    dataset_schema_version: str,
    warmup_performed: bool,
) -> dict:
    total  = len(results)
    counts = {s: sum(1 for r in results if r["status"] == s)
              for s in ("PASS", "FAIL", "KNOWN_FAIL", "ERROR", "SKIP")}

    timed      = [r["elapsed_ms"] for r in results if r["status"] != "SKIP"]
    pass_rate  = round(counts["PASS"] / total, 4) if total else 0.0
    gate_numer = counts["PASS"] + counts["KNOWN_FAIL"] + counts["SKIP"]
    gate_rate  = round(gate_numer / total, 4) if total else 1.0

    return {
        "schema_version":         "1.0.0",
        "run_id":                 str(uuid.uuid4()),
        "timestamp":              (datetime.now(timezone.utc)
                                   .isoformat(timespec="seconds")
                                   .replace("+00:00", "Z")),
        "dataset_path":           dataset_path,
        "dataset_schema_version": dataset_schema_version,
        "warmup_performed":       warmup_performed,
        "summary": {
            "total":       total,
            "passed":      counts["PASS"],
            "failed":      counts["FAIL"],
            "known_failed": counts["KNOWN_FAIL"],
            "errors":      counts["ERROR"],
            "skipped":     counts["SKIP"],
            "pass_rate":   pass_rate,
            "gate_pass_rate": gate_rate,
        },
        "latency_ms": {
            "p50":  _percentile(timed, 50),
            "p95":  _percentile(timed, 95),
            "max":  round(max(timed), 1) if timed else 0.0,
            "note": "snapshot only — no SLA gate in Phase 2A",
        },
        "backend_summary": _build_backend_summary(results),
        "cases": results,
    }


def _write_report(report: dict, no_archive: bool) -> tuple[Path, Path | None]:
    _REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    latest = _REPORTS_DIR / "latest_eval_report.json"
    latest.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")

    archive: Path | None = None
    if not no_archive:
        ts      = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        archive = _REPORTS_DIR / f"eval_report_{ts}.json"
        archive.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")

    return latest, archive


# ── Terminal output ───────────────────────────────────────────────────────────

_ICON = {"PASS": "✓", "FAIL": "✗", "KNOWN_FAIL": "⚠", "ERROR": "!", "SKIP": "–"}


def _print_case_live(result: dict, verbose: bool) -> None:
    icon   = _ICON.get(result["status"], "?")
    cid    = result["id"]
    status = result["status"]
    label  = f"  {icon}  {cid:<22}"
    ms_str = f"{result['elapsed_ms']:>7.1f} ms"

    if status == "PASS":
        rd  = next((a for a in result["assertions"] if a["name"] == "route"),        None)
        rr  = next((a for a in result["assertions"] if a["name"] == "route_reason"), None)
        rs  = f"route={rd['actual']}"       if rd else ""
        rrs = f"reason={rr['actual']}"      if rr else ""
        print(f"{label}  {rs:<30} {rrs:<42} {ms_str}")
        if verbose:
            for a in result["assertions"]:
                _print_assertion(a, indent=7)

    elif status == "SKIP":
        print(f"{label}  SKIP")

    else:
        print(f"{label}  {status:<12} {ms_str}")
        if result.get("error"):
            print(f"       error: {result['error'][:160]}")
        for a in result["assertions"]:
            if not a["passed"] or verbose:
                _print_assertion(a, indent=7)


def _print_assertion(a: dict, indent: int = 7) -> None:
    pad = " " * indent
    adv = "  (advisory)" if a["name"] == "store_rebuild_advisory" else ""
    if a["passed"]:
        print(f"{pad}✓ {a['name']}{adv}")
    else:
        print(f"{pad}✗ {a['name']}: {a['message']}{adv}")


def _print_footer(report: dict, latest: Path, archive: Path | None) -> None:
    s   = report["summary"]
    lat = report["latency_ms"]
    bs  = report.get("backend_summary", {})
    print()
    print("─" * 72)
    print(
        f"  {s['passed']} PASS  │  {s['failed']} FAIL  │  "
        f"{s['known_failed']} KNOWN_FAIL  │  {s['errors']} ERROR  │  {s['skipped']} SKIP"
    )
    print()
    print(f"  pass_rate:       {s['pass_rate'] * 100:.1f}%  "
          f"({s['passed']}/{s['total']})")
    numer = s["passed"] + s["known_failed"] + s["skipped"]
    print(f"  gate_pass_rate:  {s['gate_pass_rate'] * 100:.1f}%  "
          f"({numer}/{s['total']} non-gating)")
    print()
    print(f"  Latency:  p50={lat['p50']}ms  p95={lat['p95']}ms  "
          f"max={lat['max']}ms  (snapshot, no SLA)")

    if bs:
        non_skip = s["total"] - s["skipped"]
        print()
        print("  Backend inference  (informational — not gated):")
        counts = bs.get("counts", {})
        for backend in _BACKEND_BUCKETS:
            n = counts.get(backend, 0)
            if n:
                print(f"    {backend:<18}  {n}")
        print()
        print(f"  backend_match:      {bs['backend_match']}/{non_skip}  "
              f"({bs['backend_match_rate'] * 100:.1f}%)")
        print(f"  vector_db_touched:  {bs['vector_db_touched']}/{non_skip}  "
              f"({bs['vector_db_touched_pct']:.1f}%)")
        mismatches = bs.get("mismatches", [])
        if mismatches:
            print(f"\n  Backend mismatches ({len(mismatches)}):")
            for m in mismatches:
                print(f"    {m['id']:<22}  expected={m['expected_backend']!r:<20}  "
                      f"actual={m['actual_backend']!r}")
        else:
            print("  backend_mismatches: none")

    print()
    print(f"  Report: {latest}")
    if archive:
        print(f"          {archive}")
    print("─" * 72)


# ── CLI ───────────────────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="run_evals",
        description="Phase 2A evaluation harness — CSULB Grad Center AI Assistant",
    )
    p.add_argument(
        "--dataset", default=str(_DEFAULT_DATASET),
        help="Path to golden queries JSON  (default: evals/golden_queries.json)",
    )
    p.add_argument(
        "--skip-known-failures", action="store_true",
        help="Skip cases with known_failure=true  (status=SKIP)",
    )
    p.add_argument(
        "--ci", action="store_true",
        help="Exit 1 if any FAIL or ERROR  (KNOWN_FAIL does not trigger)",
    )
    p.add_argument(
        "--no-archive", action="store_true",
        help="Write only latest_eval_report.json, skip timestamped archive",
    )
    p.add_argument(
        "--no-warmup", action="store_true",
        help="Skip pre-run store warm-up call",
    )
    p.add_argument(
        "--verbose", action="store_true",
        help="Print per-assertion detail for every case",
    )
    return p.parse_args()


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    args = _parse_args()

    dataset_path = Path(args.dataset)
    if not dataset_path.exists():
        print(f"[run_evals] ERROR: dataset not found: {dataset_path}", file=sys.stderr)
        sys.exit(1)

    with dataset_path.open(encoding="utf-8") as fh:
        dataset = json.load(fh)

    schema_version = dataset.get("schema_version")
    if schema_version != "1.0.0":
        print(
            f"[run_evals] ERROR: unsupported schema_version {schema_version!r} "
            f"(expected '1.0.0')",
            file=sys.stderr,
        )
        sys.exit(1)

    cases = dataset.get("cases", [])
    if not cases:
        print("[run_evals] ERROR: dataset contains no cases", file=sys.stderr)
        sys.exit(1)

    print(f"Phase 2A Eval  ─  {dataset_path}  (schema: {schema_version})")

    _install_capture_hook()

    warmup_performed = False
    if args.no_warmup:
        print("Warm-up skipped (--no-warmup)")
    else:
        print("Warming up stores...", end=" ", flush=True)
        try:
            # Pass 1: warms ChromaDB vector store (application route)
            set_request_id(new_request_id())
            orchestrator.run("what are the steps to apply?", session_id="eval_warmup_chroma")
            # Pass 2: warms FAQ RAG store (next_steps route)
            set_request_id(new_request_id())
            orchestrator.run("I don't know where to start with graduate school",
                             session_id="eval_warmup_faq")
            warmup_performed = True
            print("done")
        except Exception as exc:
            print(f"WARNING: warm-up failed ({exc})")

    print(f"Running {len(cases)} cases\n")

    results: list[dict] = []
    for case in cases:
        if args.skip_known_failures and case.get("known_failure", False):
            results.append({
                "id": case["id"], "query": case["query"],
                "status": "SKIP",
                "known_failure": True,
                "elapsed_ms": 0.0,
                "assertions": [],
                "captured_events": {},
                "error": None,
                "expected_backend":  case.get("expected", {}).get("backend", ""),
                "actual_backend":    None,
                "backend_match":     None,
                "vector_db_touched": None,
            })
            print(f"  {_ICON['SKIP']}  {case['id']:<22}  SKIP")
            continue

        result = _run_case(case)
        results.append(result)
        _print_case_live(result, verbose=args.verbose)

    report           = _build_report(results, str(dataset_path),
                                     schema_version, warmup_performed)
    latest, archive  = _write_report(report, args.no_archive)
    _print_footer(report, latest, archive)

    if args.ci:
        if any(r["status"] in ("FAIL", "ERROR") for r in results):
            sys.exit(1)


if __name__ == "__main__":
    main()
