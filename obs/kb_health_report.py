"""
obs/kb_health_report.py
Phase 9B — knowledge-base health report.

Inspects the built Chroma vector store (chroma_db/) and produces a
structured health summary covering chunk counts, coverage by page type and
program, metadata completeness, chunk quality, and duplicate chunk_ids.

Distinct from evals/run_ingestion_evals.py (Phase 9A): that runner drives
structured assertion cases ("is deadlines page_type count >= 5?") and
produces PASS/FAIL verdicts against a curated dataset. This module produces
a free-form diagnostic overview of the store's current state — no dataset,
no case assertions, no pass/fail per-field. Think of it as `df -h` for the
knowledge base: a one-shot human-readable overview, not a regression gate.

Purely read-only. Never rebuilds the store, never modifies chunking,
never changes embeddings, never touches retrieval or routing.

Usage:
    from obs.kb_health_report import inspect_kb, format_console_report
    report = inspect_kb()            # load from chroma_db/
    print(format_console_report(report))

    python -m obs.kb_health_report                 # print to console
    python -m obs.kb_health_report --json          # also write JSON file
    python -m obs.kb_health_report --json-path /tmp/kb.json
"""
from __future__ import annotations

import argparse
import json
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from config.settings import CHROMA_DIR

# ---------------------------------------------------------------------------
# Thresholds — deterministic, documented, not invented
# ---------------------------------------------------------------------------

# Chunk count below which the store is considered degraded rather than just
# under-populated — 100 chunks is ~20% of the Phase 9A baseline (491), which
# would indicate a near-complete ingestion failure.
_MIN_TOTAL_CHUNKS = 100

# Page types that MUST be present in any healthy store.  These are the four
# primary CSULB sources from rag/ingestion.py:PAGE_SOURCES plus the
# program-application type added by dynamic discovery.
_REQUIRED_PAGE_TYPES = frozenset({
    "faq", "deadlines", "eligibility", "application_process", "program_application",
})

# Minimum distinct named programs expected.  The current store has 5.
# Fewer suggests one or more programs were entirely missed by discovery.
_MIN_NAMED_PROGRAMS = 5

# Chunks shorter than this (chars) are flagged as suspiciously short.
# Phase 9A's live store had 2 chunks at 29 chars each.  50 chars is a
# reasonable lower bound for semantically useful content.
_SHORT_CHUNK_THRESHOLD = 50

# ---------------------------------------------------------------------------
# Core inspection function
# ---------------------------------------------------------------------------

def inspect_kb(store=None) -> dict:
    """
    Inspect the built Chroma vector store and return a structured health
    report.

    Args:
        store: An already-loaded Chroma instance.  If None (default), the
               store is loaded from disk via rag.store.load_vector_store().
               Passing a store instance skips the disk-load step — useful
               for tests that have already loaded the store.

    Returns:
        A dict with the following top-level keys:
            timestamp, store_path, store_built_at, store_age_hours,
            overall_health, warnings,
            knowledge_base, coverage, chunk_stats,
            metadata_health, duplicate_tracking.
        Returns a minimal "unavailable" dict if the store cannot be loaded.
    """
    if store is None:
        from rag.store import load_vector_store
        store = load_vector_store()

    if store is None:
        return {
            "timestamp":      _now_iso(),
            "store_path":     str(CHROMA_DIR),
            "store_built_at": None,
            "store_age_hours": None,
            "overall_health": "unhealthy",
            "warnings": ["Vector store not found — chroma_db/ does not exist or is corrupt"],
            "knowledge_base": {"total_chunks": 0, "total_urls": 0, "total_named_programs": 0},
            "coverage": {"by_page_type": {}, "by_program": {}},
            "chunk_stats": {},
            "metadata_health": {},
            "duplicate_tracking": {},
        }

    coll = store._collection
    items = coll.get(include=["metadatas", "documents"])
    metadatas: list[dict]  = items["metadatas"]
    documents:  list[str]  = items["documents"]
    total = len(metadatas)

    # ── Store age ─────────────────────────────────────────────────────────
    ts_file = CHROMA_DIR / ".last_built"
    store_built_at: Optional[str] = None
    store_age_hours: Optional[float] = None
    if ts_file.exists():
        try:
            mtime = ts_file.stat().st_mtime
            store_age_hours = round((time.time() - mtime) / 3600, 1)
            store_built_at = datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat(
                timespec="seconds"
            )
        except OSError:
            pass

    # ── Knowledge-base summary ─────────────────────────────────────────────
    distinct_urls    = len({m.get("url", "") for m in metadatas if m.get("url")})
    distinct_programs = sorted({
        m["program_name"]
        for m in metadatas
        if m.get("program_name", "").strip()
    })

    knowledge_base = {
        "total_chunks":         total,
        "total_urls":           distinct_urls,
        "total_named_programs": len(distinct_programs),
        "named_programs":       distinct_programs,
    }

    # ── Coverage ───────────────────────────────────────────────────────────
    pt_counts = Counter(m.get("page_type", "") for m in metadatas)
    prog_counts = Counter(m.get("program_name", "") for m in metadatas if m.get("program_name", "").strip())
    url_counts = Counter(m.get("url", "") for m in metadatas if m.get("url"))

    coverage = {
        "by_page_type": dict(sorted(pt_counts.items())),
        "by_program":   dict(prog_counts.most_common()),
        "url_distribution": {
            "total_distinct_urls": distinct_urls,
            "top_10_urls": [
                {"url": url, "chunks": cnt}
                for url, cnt in url_counts.most_common(10)
            ],
        },
    }

    # ── Chunk statistics ───────────────────────────────────────────────────
    chunk_lengths = [len(d) for d in documents]
    empty_count = sum(1 for d in documents if not d.strip())
    short_count = sum(1 for d in documents if 0 < len(d.strip()) < _SHORT_CHUNK_THRESHOLD)

    chunk_stats = {
        "average_chars":     round(sum(chunk_lengths) / total, 1) if total else 0.0,
        "min_chars":          min(chunk_lengths) if chunk_lengths else 0,
        "max_chars":          max(chunk_lengths) if chunk_lengths else 0,
        "empty_chunks":       empty_count,
        "short_chunks": {
            "count":           short_count,
            "threshold_chars": _SHORT_CHUNK_THRESHOLD,
        },
    }

    # ── Metadata health ────────────────────────────────────────────────────
    def _missing(field: str) -> int:
        return sum(
            1 for m in metadatas
            if not str(m.get(field, "") or "").strip()
        )

    metadata_health = {
        "total_chunks":     total,
        "missing_url":       _missing("url"),
        "missing_chunk_id":  _missing("chunk_id"),
        "missing_page_type": _missing("page_type"),
        "missing_title":     _missing("title"),
        "content_category_coverage": {
            "with_value":    sum(1 for m in metadatas if m.get("content_category", "").strip()),
            "without_value": sum(1 for m in metadatas if not m.get("content_category", "").strip()),
        },
    }

    # ── Duplicate chunk_ids ────────────────────────────────────────────────
    chunk_id_counts = Counter(m.get("chunk_id", "") for m in metadatas)
    dup_ids = {k: v for k, v in chunk_id_counts.items() if v > 1 and k}
    duplicate_tracking = {
        "duplicate_chunk_id_count": len(dup_ids),
        "total_extra_copies":       sum(v - 1 for v in dup_ids.values()),
        "known_duplicates": sorted(
            [{"chunk_id": cid, "count": cnt} for cid, cnt in dup_ids.items()],
            key=lambda x: -x["count"],
        ),
    }

    # ── Classify + derive warnings ─────────────────────────────────────────
    overall_health, warnings = classify_health(
        total=total,
        pt_counts=dict(pt_counts),
        distinct_programs=distinct_programs,
        empty_count=empty_count,
        short_count=short_count,
        metadata_health=metadata_health,
        dup_count=len(dup_ids),
        store_age_hours=store_age_hours,
    )

    return {
        "timestamp":       _now_iso(),
        "store_path":      str(CHROMA_DIR),
        "store_built_at":  store_built_at,
        "store_age_hours": store_age_hours,
        "overall_health":  overall_health,
        "warnings":        warnings,
        "knowledge_base":  knowledge_base,
        "coverage":        coverage,
        "chunk_stats":     chunk_stats,
        "metadata_health": metadata_health,
        "duplicate_tracking": duplicate_tracking,
    }


# ---------------------------------------------------------------------------
# Health classification
# ---------------------------------------------------------------------------

def classify_health(
    *,
    total: int,
    pt_counts: dict[str, int],
    distinct_programs: list[str],
    empty_count: int,
    short_count: int,
    metadata_health: dict,
    dup_count: int,
    store_age_hours: Optional[float],
) -> tuple[str, list[str]]:
    """
    Assign a deterministic overall health status and build a warnings list.

    Priority order: unhealthy → degraded → healthy_with_warnings → healthy.
    A store satisfies the FIRST category whose conditions fire; conditions
    are checked in severity order and the most severe wins.

    Returns:
        (status_string, warnings_list)
    """
    warnings: list[str] = []
    status_reasons: list[str] = []

    # ── Unhealthy conditions ───────────────────────────────────────────────
    if total == 0:
        return "unhealthy", ["Store is empty — 0 chunks found"]

    critical_missing = [
        f for f in ("missing_url", "missing_chunk_id", "missing_page_type")
        if metadata_health.get(f, 0) > 0
    ]
    if critical_missing:
        for f in critical_missing:
            count = metadata_health[f]
            status_reasons.append(
                f"{count} chunk(s) have empty {f.replace('missing_', '')} "
                "— required for retrieval"
            )

    if empty_count > 0:
        status_reasons.append(f"{empty_count} chunk(s) have empty page_content")

    if status_reasons:
        return "unhealthy", status_reasons

    # ── Degraded conditions ────────────────────────────────────────────────
    if total < _MIN_TOTAL_CHUNKS:
        status_reasons.append(
            f"Only {total} total chunks (minimum expected: {_MIN_TOTAL_CHUNKS}) — "
            "ingestion may have failed"
        )

    missing_page_types = sorted(
        pt for pt in _REQUIRED_PAGE_TYPES if pt_counts.get(pt, 0) == 0
    )
    for pt in missing_page_types:
        status_reasons.append(
            f"page_type={pt!r} has 0 chunks — source page may have failed to ingest"
        )

    if status_reasons:
        return "degraded", status_reasons

    # ── Healthy-with-warnings conditions ──────────────────────────────────
    if dup_count > 0:
        warnings.append(
            f"{dup_count} chunk_id(s) appear in more than one document — "
            "known for deadlines specialist extractor (see Phase 8A)"
        )

    if short_count > 0:
        warnings.append(
            f"{short_count} chunk(s) shorter than {_SHORT_CHUNK_THRESHOLD} chars "
            "— may be sentence fragments from chunk boundary splits"
        )

    if len(distinct_programs) < _MIN_NAMED_PROGRAMS:
        warnings.append(
            f"Only {len(distinct_programs)} named program(s) found "
            f"(expected {_MIN_NAMED_PROGRAMS}) — discovery may have missed some programs"
        )

    if store_age_hours is not None and store_age_hours > 48:
        warnings.append(
            f"Store is {store_age_hours:.0f}h old — consider triggering a rebuild "
            "if CSULB pages may have changed"
        )

    if warnings:
        return "healthy_with_warnings", warnings

    return "healthy", []


# ---------------------------------------------------------------------------
# Console formatting
# ---------------------------------------------------------------------------

def format_console_report(report: dict) -> str:
    """
    Render the full health report as a readable terminal block.
    Follows the established obs/ module convention (fixed-width header/footer,
    grouped sections, key-value layout).
    """
    width = 60
    lines: list[str] = []

    # ── Header ─────────────────────────────────────────────────────────────
    lines += ["=" * width, "Knowledge Base Health Report", "=" * width, ""]
    lines.append(f"Store:   {report['store_path']}")
    if report.get("store_built_at"):
        age = f"  ({report['store_age_hours']}h ago)" if report.get("store_age_hours") is not None else ""
        lines.append(f"Built:   {report['store_built_at']}{age}")
    lines.append(f"Checked: {report['timestamp']}")
    lines.append("")

    # ── Overall health ──────────────────────────────────────────────────────
    status = report["overall_health"].upper().replace("_", " ")
    lines.append(f"Overall Health: {status}")
    if report["warnings"]:
        lines.append("")
        lines.append("Warnings:")
        for w in report["warnings"]:
            lines.append(f"  ! {w}")
    lines.append("")

    # ── Knowledge base summary ──────────────────────────────────────────────
    kb = report.get("knowledge_base", {})
    lines += ["-" * width, "Knowledge Base", "-" * width]
    lines.append(f"  Total Chunks:   {kb.get('total_chunks', 0)}")
    lines.append(f"  Distinct URLs:  {kb.get('total_urls', 0)}")
    lines.append(f"  Named Programs: {kb.get('total_named_programs', 0)}")
    if kb.get("named_programs"):
        for prog in kb["named_programs"]:
            lines.append(f"    • {prog}")
    lines.append("")

    # ── Coverage ───────────────────────────────────────────────────────────
    cov = report.get("coverage", {})
    lines += ["-" * width, "Coverage", "-" * width]

    pt = cov.get("by_page_type", {})
    if pt:
        lines.append("  By Page Type:")
        for page_type, count in sorted(pt.items()):
            bar = "!" if page_type in _REQUIRED_PAGE_TYPES and count == 0 else " "
            lines.append(f"  {bar} {page_type:<28} {count:>5} chunks")

    prog = cov.get("by_program", {})
    if prog:
        lines.append("")
        lines.append("  By Program:")
        for pname, count in prog.items():
            lines.append(f"    {pname:<42} {count:>5} chunks")
    lines.append("")

    # ── Chunk statistics ───────────────────────────────────────────────────
    cs = report.get("chunk_stats", {})
    lines += ["-" * width, "Chunk Statistics", "-" * width]
    lines.append(f"  Average Size:   {cs.get('average_chars', 0):.0f} chars")
    lines.append(f"  Smallest Chunk: {cs.get('min_chars', 0)} chars")
    lines.append(f"  Largest Chunk:  {cs.get('max_chars', 0)} chars")
    lines.append(f"  Empty Chunks:   {cs.get('empty_chunks', 0)}")
    short_info = cs.get("short_chunks", {})
    lines.append(
        f"  Short Chunks:   {short_info.get('count', 0)}  "
        f"(< {short_info.get('threshold_chars', _SHORT_CHUNK_THRESHOLD)} chars)"
    )
    lines.append("")

    # ── Metadata health ─────────────────────────────────────────────────────
    mh = report.get("metadata_health", {})
    lines += ["-" * width, "Metadata Health", "-" * width]
    total_c = mh.get("total_chunks", 0)
    for field in ("url", "chunk_id", "page_type", "title"):
        missing = mh.get(f"missing_{field}", 0)
        present = total_c - missing
        status_flag = "!" if missing > 0 else " "
        lines.append(
            f"  {status_flag} {field:<20} {present:>5}/{total_c}  "
            f"({'OK' if missing == 0 else f'{missing} missing'})"
        )
    cc = mh.get("content_category_coverage", {})
    if cc:
        lines.append(
            f"    content_category     {cc.get('with_value', 0):>5}/{total_c}  "
            f"({cc.get('without_value', 0)} without — expected for generic pages)"
        )
    lines.append("")

    # ── Duplicate tracking ──────────────────────────────────────────────────
    dt = report.get("duplicate_tracking", {})
    lines += ["-" * width, "Duplicate Tracking", "-" * width]
    dup_count = dt.get("duplicate_chunk_id_count", 0)
    extra     = dt.get("total_extra_copies", 0)
    lines.append(f"  Duplicate chunk_ids: {dup_count}  (total extra copies: {extra})")
    for d in dt.get("known_duplicates", []):
        lines.append(f"    chunk_id={d['chunk_id']}  appears {d['count']}x")
    if dup_count == 0:
        lines.append("  No duplicate chunk_ids detected.")
    lines.append("")

    # ── Footer ──────────────────────────────────────────────────────────────
    lines.append("=" * width)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# JSON report
# ---------------------------------------------------------------------------

_OBS_REPORTS_DIR = Path(__file__).parent / "reports"


def write_json_report(
    report: dict,
    path: Optional[Path] = None,
) -> Path:
    """
    Write the health report as a JSON file.

    Args:
        report: Dict returned by inspect_kb().
        path:   Output path.  Defaults to obs/reports/latest_kb_health.json.

    Returns:
        The Path the file was written to.
    """
    out_path = path or (_OBS_REPORTS_DIR / "latest_kb_health.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    return out_path


# ---------------------------------------------------------------------------
# Helpers
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
        prog="kb_health_report",
        description="Phase 9B knowledge-base health report — CSULB Grad Center AI Assistant",
    )
    p.add_argument(
        "--json", action="store_true",
        help="Write a JSON report to obs/reports/latest_kb_health.json",
    )
    p.add_argument(
        "--json-path", type=Path, default=None,
        help="Write a JSON report to the specified path (implies --json)",
    )
    return p.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    report = inspect_kb()
    print(format_console_report(report))
    if args.json or args.json_path:
        out = write_json_report(report, path=args.json_path)
        print(f"\nJSON report written to: {out}")
