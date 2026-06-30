"""
obs/kb_drift.py
Phase 9C — Knowledge Base Drift Detection.

Compares a stored baseline snapshot of the knowledge base against the
current Chroma store state and classifies the difference as No Drift,
Minor Drift, Moderate Drift, or Major Drift.

Distinct from evals/run_ingestion_evals.py (Phase 9A): that runner checks
the CURRENT store against curated pass/fail assertions ("does faq have
>= 50 chunks?"). This module checks the CURRENT store against a PREVIOUS
snapshot of itself — detecting when something changed between two builds,
regardless of whether the current state passes the static assertions.

Distinct from obs/kb_health_report.py (Phase 9B): that module reports the
current store's absolute state (counts, quality, warnings). This module
reports RELATIVE state — what changed since the baseline was captured.

Read-only throughout. Never rebuilds the store, never modifies Chroma,
never updates the baseline automatically (an engineer decides when to
promote a new state to baseline).

Usage:
    # Generate a baseline from the current store and save it:
    python -m obs.kb_drift --save-baseline

    # Compare the current store against the saved baseline:
    python -m obs.kb_drift

    # Write a JSON drift report in addition to console output:
    python -m obs.kb_drift --json

    # From Python:
    from obs.kb_drift import detect_drift, format_console_drift
    report = detect_drift()
    print(format_console_drift(report))
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from obs.kb_health_report import inspect_kb

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_OBS_REPORTS_DIR = Path(__file__).parent / "reports"
_DEFAULT_BASELINE_PATH = _OBS_REPORTS_DIR / "kb_baseline.json"
_DEFAULT_DRIFT_REPORT_PATH = _OBS_REPORTS_DIR / "latest_kb_drift.json"

# ---------------------------------------------------------------------------
# Drift thresholds — deterministic, documented
# ---------------------------------------------------------------------------
# All thresholds are absolute (not percentages) because the knowledge base
# is small (~500 chunks) and absolute numbers are more interpretable at this
# scale ("dropped by 75 chunks" is clearer than "dropped by 15.3%").
#
# Thresholds derived from the Phase 9B live-store baseline (491 chunks):
#   > 75 drop  = > 15% loss → likely a page-class failure     → MAJOR
#   25–75 drop = 5–15% loss → substantial content loss        → MODERATE
#   1–24 change = < 5%      → minor page edits, normal drift  → MINOR
#
# page_type drop > 50% of baseline value → MODERATE (e.g. faq drops from
# 98 to < 49) because that page type still answers queries but with half
# the context; 0 chunks → MAJOR (all queries against that type break).

# Maximum ABSOLUTE chunk-count change before escalating to the next severity
# (applied symmetrically — increases and decreases both matter).
_MAJOR_CHUNK_DELTA = 75   # > this → major
_MODERATE_CHUNK_DELTA = 25  # > this → moderate; <= this → minor

# page_type count drop fraction that escalates to MODERATE
_PAGE_TYPE_MODERATE_DROP_FRACTION = 0.50  # >50% drop of baseline count

# Required page types — 0 chunks for any of these → MAJOR
_REQUIRED_PAGE_TYPES = frozenset({
    "faq", "deadlines", "eligibility", "application_process", "program_application",
})

# ---------------------------------------------------------------------------
# Baseline extraction
# ---------------------------------------------------------------------------

def extract_baseline(health_report: dict) -> dict:
    """
    Extract the drift-relevant fields from a full obs/kb_health_report dict
    into a compact baseline snapshot.

    Fields intentionally excluded from the baseline:
      - timestamp / store_age_hours — change on every run
      - average_chars / min_chars / max_chars — minor content edits shift these
      - url_distribution top-N list — verbose, changes naturally as pages grow
      - store_path — environment-specific, not useful for portable comparison
      - overall_health / warnings — derived fields, not raw measurements
      - content_category_coverage — informational, not a regression signal

    Returns a dict with schema_version and captured_at so the format can
    evolve without ambiguity.
    """
    kb   = health_report.get("knowledge_base", {})
    cov  = health_report.get("coverage", {})
    cs   = health_report.get("chunk_stats", {})
    mh   = health_report.get("metadata_health", {})
    dt   = health_report.get("duplicate_tracking", {})

    return {
        "schema_version": "1.0",
        "captured_at":    health_report.get("timestamp", _now_iso()),
        "store_built_at": health_report.get("store_built_at"),

        # Knowledge base size
        "total_chunks":          kb.get("total_chunks", 0),
        "total_urls":             kb.get("total_urls", 0),
        "total_named_programs":   kb.get("total_named_programs", 0),
        "named_programs":         sorted(kb.get("named_programs", [])),

        # Coverage by page type
        "chunks_by_page_type":   dict(cov.get("by_page_type", {})),

        # Coverage by program
        "chunks_by_program":     dict(cov.get("by_program", {})),

        # Chunk quality
        "empty_chunks":          cs.get("empty_chunks", 0),
        "short_chunks":          cs.get("short_chunks", {}).get("count", 0),

        # Metadata completeness (critical — should always be 0)
        "missing_url":            mh.get("missing_url", 0),
        "missing_chunk_id":       mh.get("missing_chunk_id", 0),
        "missing_page_type":      mh.get("missing_page_type", 0),
        "missing_title":          mh.get("missing_title", 0),

        # Duplicate tracking
        "duplicate_chunk_id_count": dt.get("duplicate_chunk_id_count", 0),
        "total_extra_copies":       dt.get("total_extra_copies", 0),
    }


# ---------------------------------------------------------------------------
# Baseline persistence
# ---------------------------------------------------------------------------

def save_baseline(baseline: dict, path: Optional[Path] = None) -> Path:
    """Write a baseline snapshot to obs/reports/kb_baseline.json (default)."""
    out = path or _DEFAULT_BASELINE_PATH
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(baseline, indent=2, default=str), encoding="utf-8")
    return out


def load_baseline(path: Optional[Path] = None) -> Optional[dict]:
    """
    Load a baseline snapshot.  Returns None if the file does not exist or
    cannot be parsed — callers handle the missing-baseline case explicitly.
    """
    src = path or _DEFAULT_BASELINE_PATH
    if not src.exists():
        return None
    try:
        return json.loads(src.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


# ---------------------------------------------------------------------------
# Field-level comparison
# ---------------------------------------------------------------------------

def _change(field: str, baseline_val, current_val, severity: str, description: str) -> dict:
    result: dict = {
        "field":       field,
        "baseline":    baseline_val,
        "current":     current_val,
        "severity":    severity,
        "description": description,
    }
    if isinstance(baseline_val, (int, float)) and isinstance(current_val, (int, float)):
        result["delta"] = current_val - baseline_val
    return result


def _severity_order(s: str) -> int:
    return {"no_drift": 0, "info": 1, "minor": 2, "moderate": 3, "major": 4}.get(s, 0)


def _classify_chunk_delta(delta: int) -> str:
    abs_delta = abs(delta)
    if abs_delta > _MAJOR_CHUNK_DELTA:
        return "major"
    if abs_delta > _MODERATE_CHUNK_DELTA:
        return "moderate"
    if abs_delta > 0:
        return "minor"
    return "no_drift"


# ---------------------------------------------------------------------------
# Core comparison
# ---------------------------------------------------------------------------

def compare(current_snapshot: dict, baseline: dict) -> tuple[str, list[dict]]:
    """
    Compare a current snapshot (output of extract_baseline(health_report))
    against a stored baseline.

    Returns:
        (overall_drift_level, list[change_dict])
        overall_drift_level: "no_drift" | "minor_drift" | "moderate_drift" | "major_drift"
    """
    changes: list[dict] = []

    # ── Metadata regressions (previously 0, now > 0) — always MAJOR ───────
    for field in ("missing_url", "missing_chunk_id", "missing_page_type", "missing_title"):
        b_val = baseline.get(field, 0)
        c_val = current_snapshot.get(field, 0)
        if b_val == 0 and c_val > 0:
            changes.append(_change(
                field, b_val, c_val, "major",
                f"{c_val} chunk(s) now have empty {field.replace('missing_', '')} "
                "(was 0 in baseline) — required field regression",
            ))
        elif b_val > 0 and c_val == 0:
            changes.append(_change(
                field, b_val, c_val, "minor",
                f"{field} issues resolved ({b_val} → 0)",
            ))
        elif b_val != c_val:
            sev = "major" if c_val > b_val else "minor"
            changes.append(_change(field, b_val, c_val, sev,
                                    f"{field} changed from {b_val} to {c_val}"))

    # ── Empty chunks (previously 0, now > 0) — always MAJOR ───────────────
    b_empty = baseline.get("empty_chunks", 0)
    c_empty = current_snapshot.get("empty_chunks", 0)
    if b_empty == 0 and c_empty > 0:
        changes.append(_change(
            "empty_chunks", b_empty, c_empty, "major",
            f"{c_empty} empty chunk(s) detected (was 0 in baseline) — "
            "chunking regression",
        ))
    elif b_empty > 0 and c_empty < b_empty:
        changes.append(_change(
            "empty_chunks", b_empty, c_empty, "minor",
            f"Empty chunks reduced from {b_empty} to {c_empty}",
        ))

    # ── Total chunks ────────────────────────────────────────────────────────
    b_total = baseline.get("total_chunks", 0)
    c_total = current_snapshot.get("total_chunks", 0)
    delta = c_total - b_total
    if delta != 0:
        sev = _classify_chunk_delta(delta)
        direction = "grown" if delta > 0 else "shrunk"
        changes.append(_change(
            "total_chunks", b_total, c_total, sev,
            f"Total chunks {direction} by {abs(delta)} "
            f"({b_total} → {c_total})",
        ))

    # ── Total URLs ─────────────────────────────────────────────────────────
    b_urls = baseline.get("total_urls", 0)
    c_urls = current_snapshot.get("total_urls", 0)
    if b_urls != c_urls:
        direction = "added" if c_urls > b_urls else "removed"
        changes.append(_change(
            "total_urls", b_urls, c_urls, "minor",
            f"{abs(c_urls - b_urls)} URL(s) {direction} "
            f"({b_urls} → {c_urls})",
        ))

    # ── Named programs — additions/removals ────────────────────────────────
    b_progs = set(baseline.get("named_programs", []))
    c_progs = set(current_snapshot.get("named_programs", []))
    removed_progs = sorted(b_progs - c_progs)
    added_progs   = sorted(c_progs - b_progs)

    for prog in removed_progs:
        changes.append(_change(
            f"program:{prog}", "present", "absent", "major",
            f"Program {prog!r} was in baseline but has 0 chunks now — "
            "program disappeared from knowledge base",
        ))
    for prog in added_progs:
        changes.append(_change(
            f"program:{prog}", "absent", "present", "minor",
            f"New program {prog!r} added to knowledge base",
        ))

    # ── Coverage by page_type ──────────────────────────────────────────────
    b_pt = baseline.get("chunks_by_page_type", {})
    c_pt = current_snapshot.get("chunks_by_page_type", {})
    all_pt = set(b_pt) | set(c_pt)
    for pt in sorted(all_pt):
        b_cnt = b_pt.get(pt, 0)
        c_cnt = c_pt.get(pt, 0)
        if b_cnt == c_cnt:
            continue
        pt_delta = c_cnt - b_cnt
        # A required page_type dropping to 0 → major
        if pt in _REQUIRED_PAGE_TYPES and c_cnt == 0:
            sev = "major"
            desc = f"page_type={pt!r} has 0 chunks (was {b_cnt} in baseline) — required page type lost"
        # A drop > 50% of baseline value → moderate
        elif b_cnt > 0 and c_cnt < b_cnt and (b_cnt - c_cnt) / b_cnt > _PAGE_TYPE_MODERATE_DROP_FRACTION:
            sev = "moderate"
            desc = f"page_type={pt!r} dropped significantly: {b_cnt} → {c_cnt} ({b_cnt - c_cnt} fewer)"
        else:
            sev = _classify_chunk_delta(pt_delta)
            direction = "grew" if pt_delta > 0 else "shrank"
            desc = f"page_type={pt!r} {direction}: {b_cnt} → {c_cnt} ({'+' if pt_delta >= 0 else ''}{pt_delta})"
        changes.append(_change(f"page_type:{pt}", b_cnt, c_cnt, sev, desc))

    # ── Coverage by program (existing programs only) ───────────────────────
    b_prog_cnts = baseline.get("chunks_by_program", {})
    c_prog_cnts = current_snapshot.get("chunks_by_program", {})
    for prog in sorted(set(b_prog_cnts) & set(c_prog_cnts)):
        b_cnt = b_prog_cnts.get(prog, 0)
        c_cnt = c_prog_cnts.get(prog, 0)
        if b_cnt == c_cnt:
            continue
        prog_delta = c_cnt - b_cnt
        sev = _classify_chunk_delta(prog_delta)
        direction = "grew" if prog_delta > 0 else "shrank"
        changes.append(_change(
            f"program_chunks:{prog}", b_cnt, c_cnt, sev,
            f"Program {prog!r} {direction}: {b_cnt} → {c_cnt} "
            f"({'+' if prog_delta >= 0 else ''}{prog_delta})",
        ))

    # ── Short chunks ────────────────────────────────────────────────────────
    b_short = baseline.get("short_chunks", 0)
    c_short = current_snapshot.get("short_chunks", 0)
    if b_short != c_short:
        direction = "increased" if c_short > b_short else "decreased"
        changes.append(_change(
            "short_chunks", b_short, c_short, "minor",
            f"Short-chunk count {direction}: {b_short} → {c_short}",
        ))

    # ── Duplicate tracking ──────────────────────────────────────────────────
    b_dup = baseline.get("duplicate_chunk_id_count", 0)
    c_dup = current_snapshot.get("duplicate_chunk_id_count", 0)
    if b_dup != c_dup:
        if c_dup > b_dup:
            sev = "moderate"
            desc = f"New duplicate chunk_ids introduced: {b_dup} → {c_dup}"
        else:
            sev = "minor"
            desc = f"Duplicate chunk_ids resolved: {b_dup} → {c_dup}"
        changes.append(_change("duplicate_chunk_id_count", b_dup, c_dup, sev, desc))

    b_extra = baseline.get("total_extra_copies", 0)
    c_extra = current_snapshot.get("total_extra_copies", 0)
    if b_extra != c_extra and b_dup == c_dup:
        # Extra copies changed while duplicate COUNT didn't — a subtle shift
        sev = "minor" if c_extra < b_extra else "moderate"
        changes.append(_change(
            "total_extra_copies", b_extra, c_extra, sev,
            f"Total extra duplicate copies changed: {b_extra} → {c_extra}",
        ))

    # ── Overall classification ─────────────────────────────────────────────
    if not changes:
        return "no_drift", changes

    max_sev = max(_severity_order(c["severity"]) for c in changes)
    level_map = {0: "no_drift", 1: "no_drift", 2: "minor_drift",
                 3: "moderate_drift", 4: "major_drift"}
    return level_map.get(max_sev, "no_drift"), changes


# ---------------------------------------------------------------------------
# Full pipeline
# ---------------------------------------------------------------------------

def detect_drift(store=None, baseline_path: Optional[Path] = None) -> dict:
    """
    Full pipeline: inspect KB → extract current snapshot → load baseline →
    compare → return structured drift report.

    Args:
        store:          Optional already-loaded Chroma instance (avoids
                        re-loading in tests).  If None, loads from disk.
        baseline_path:  Path to the baseline JSON.  Defaults to
                        obs/reports/kb_baseline.json.

    Returns:
        A dict with keys: timestamp, overall_drift, changes, current,
        baseline (None if no baseline saved yet), baseline_captured_at,
        warnings (for UI/reporting).
    """
    health = inspect_kb(store=store)
    current_snapshot = extract_baseline(health)

    baseline = load_baseline(baseline_path)

    if baseline is None:
        return {
            "timestamp":           _now_iso(),
            "overall_drift":       "no_baseline",
            "baseline_captured_at": None,
            "current":             current_snapshot,
            "baseline":            None,
            "changes":             [],
            "warnings": [
                "No baseline found — run with --save-baseline to capture the "
                "current state as the comparison baseline"
            ],
        }

    overall, changes = compare(current_snapshot, baseline)

    return {
        "timestamp":           _now_iso(),
        "overall_drift":       overall,
        "baseline_captured_at": baseline.get("captured_at"),
        "current":             current_snapshot,
        "baseline":            baseline,
        "changes":             changes,
        "warnings":            [c["description"] for c in changes
                                if _severity_order(c["severity"]) >= 3],
    }


# ---------------------------------------------------------------------------
# Console formatting
# ---------------------------------------------------------------------------

def format_console_drift(report: dict) -> str:
    """
    Render the drift report as a readable terminal block, mirroring the
    style of obs/kb_health_report.py and obs/trace_summary.py.
    """
    width = 58
    lines: list[str] = []

    lines += ["=" * width, "Knowledge Base Drift", "=" * width, ""]
    lines.append(f"Checked: {report['timestamp']}")
    if report.get("baseline_captured_at"):
        lines.append(f"Baseline: {report['baseline_captured_at']}")
    lines.append("")

    overall = report["overall_drift"]
    status_label = overall.upper().replace("_", " ")
    lines.append(f"Overall Status: {status_label}")
    lines.append("")

    if overall == "no_baseline":
        for w in report.get("warnings", []):
            lines.append(f"  ! {w}")
        lines.append("")
        lines.append("=" * width)
        return "\n".join(lines)

    # ── Summary table ────────────────────────────────────────────────────────
    cur  = report.get("current", {})
    base = report.get("baseline", {}) or {}

    lines += ["-" * width, "Summary", "-" * width]

    def _row(label: str, b_val, c_val) -> str:
        if b_val == c_val:
            return f"  {label:<28}  {c_val}  (unchanged)"
        delta_str = ""
        if isinstance(b_val, (int, float)) and isinstance(c_val, (int, float)):
            d = c_val - b_val
            delta_str = f"  ({'+' if d >= 0 else ''}{d})"
        return f"  {label:<28}  {b_val} → {c_val}{delta_str}"

    lines.append(_row("Total Chunks",    base.get("total_chunks", "?"),    cur.get("total_chunks", "?")))
    lines.append(_row("Total URLs",       base.get("total_urls", "?"),       cur.get("total_urls", "?")))
    lines.append(_row("Named Programs",   base.get("total_named_programs", "?"), cur.get("total_named_programs", "?")))
    lines.append(_row("Duplicate IDs",   base.get("duplicate_chunk_id_count", "?"), cur.get("duplicate_chunk_id_count", "?")))
    lines.append(_row("Short Chunks",     base.get("short_chunks", "?"),    cur.get("short_chunks", "?")))
    lines.append(_row("Empty Chunks",     base.get("empty_chunks", "?"),    cur.get("empty_chunks", "?")))
    lines.append("")

    # ── Coverage changes ─────────────────────────────────────────────────────
    b_pt = base.get("chunks_by_page_type", {})
    c_pt = cur.get("chunks_by_page_type", {})
    all_pt = sorted(set(b_pt) | set(c_pt))
    if any(b_pt.get(pt) != c_pt.get(pt) for pt in all_pt):
        lines += ["-" * width, "Page Type Changes", "-" * width]
        for pt in all_pt:
            b_cnt = b_pt.get(pt, 0)
            c_cnt = c_pt.get(pt, 0)
            lines.append(_row(f"  {pt}", b_cnt, c_cnt))
        lines.append("")

    # ── Changes with severity ────────────────────────────────────────────────
    changes = report.get("changes", [])
    if changes:
        lines += ["-" * width, "Changes Detected", "-" * width]
        for c in sorted(changes, key=lambda x: -_severity_order(x["severity"])):
            sev = c["severity"].upper()
            lines.append(f"  [{sev:<8}] {c['description']}")
        lines.append("")
    else:
        lines.append("  No changes detected.")
        lines.append("")

    # ── Warnings ─────────────────────────────────────────────────────────────
    high_severity_warnings = [c["description"] for c in changes
                               if _severity_order(c["severity"]) >= 3]
    if high_severity_warnings:
        lines += ["-" * width, "Warnings (Moderate / Major)", "-" * width]
        for w in high_severity_warnings:
            lines.append(f"  ! {w}")
        lines.append("")

    lines.append("=" * width)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# JSON report
# ---------------------------------------------------------------------------

def write_drift_report(report: dict, path: Optional[Path] = None) -> Path:
    """Write the drift report to obs/reports/latest_kb_drift.json (default)."""
    out = path or _DEFAULT_DRIFT_REPORT_PATH
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    return out


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="kb_drift",
        description="Phase 9C knowledge-base drift detection — CSULB Grad Center AI Assistant",
    )
    p.add_argument(
        "--save-baseline", action="store_true",
        help="Capture the current KB state as the comparison baseline and exit",
    )
    p.add_argument(
        "--baseline-path", type=Path, default=None,
        help="Path to the baseline file (default: obs/reports/kb_baseline.json)",
    )
    p.add_argument(
        "--json", action="store_true",
        help="Write a JSON drift report to obs/reports/latest_kb_drift.json",
    )
    p.add_argument(
        "--json-path", type=Path, default=None,
        help="Write a JSON drift report to the specified path (implies --json)",
    )
    return p.parse_args()


if __name__ == "__main__":
    args = _parse_args()

    health = inspect_kb()

    if args.save_baseline:
        baseline = extract_baseline(health)
        saved = save_baseline(baseline, path=args.baseline_path)
        print(f"Baseline saved to: {saved}")
        print(f"  total_chunks:    {baseline['total_chunks']}")
        print(f"  total_urls:      {baseline['total_urls']}")
        print(f"  named_programs:  {baseline['total_named_programs']}")
        print(f"  captured_at:     {baseline['captured_at']}")
    else:
        report = detect_drift(baseline_path=args.baseline_path)
        print(format_console_drift(report))
        if args.json or args.json_path:
            out = write_drift_report(report, path=args.json_path)
            print(f"\nDrift report written to: {out}")
