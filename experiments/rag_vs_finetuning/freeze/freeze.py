"""
experiments/rag_vs_finetuning/freeze/freeze.py
Deterministic freeze tool for the reviewed master's experiment corpus (Phase P5).

Materializes exactly the approved 12 programs (ingestion.masters.review_corpus.
SELECTED_PROGRAMS) into an immutable experiment corpus: canonical JSON records +
their exact source snapshots + a checksummed freeze manifest. It fails loudly on
any freeze-readiness violation and never writes into the production data path.

Reads frozen canonical records read-only; imports no LangChain / Chroma /
embedding / production-RAG code. Records are byte-identical to the reviewed
ingestion output (same code + same snapshot bytes + a fixed freeze timestamp).
"""
from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from domain.programs.models import CanonicalProgram
from ingestion.masters.persistence import load_program
from ingestion.masters.pipeline import _INDEX_SOURCE_ID
from ingestion.masters.review_corpus import (
    SELECTED_PROGRAMS, build_review_corpus, iter_record_facts,
)
from ingestion.masters.snapshots import SnapshotStore


def _snapshot_dir(source_id: str, program_id: str) -> str:
    """The shared index snapshot lives under _index/; program pages under their
    own program_id/."""
    return "_index" if source_id == _INDEX_SOURCE_ID else program_id

APPROVED_PROGRAMS: tuple[str, ...] = SELECTED_PROGRAMS  # the finalized 12
PROJECTION_VERSION = "projection-0.1"

# Programs excluded during review and why (recorded in the manifest).
EXCLUDED_NOTE = {
    "cla_source_granularity": [
        "Creative Writing", "Economics", "English", "Geography", "History",
    ],
    "ambiguous_shared_page_or_name": [
        "Anthropology / Anthropology - Applied", "Linguistics family", "Dance (MA/MFA)",
        "Public Administration variants",
    ],
}
SELECTION_AXES = ["college_diversity", "degree_type_diversity", "page_layout_host_diversity"]


class FreezeError(Exception):
    """Raised when the corpus is not freeze-ready or integrity fails."""


def _sha256_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _file_checksum(path: Path) -> str:
    return _sha256_bytes(Path(path).read_bytes())


def _aggregate_checksum(record_checksums: list[str]) -> str:
    joined = "\n".join(sorted(record_checksums)).encode("utf-8")
    return _sha256_bytes(joined)


def _has_fabricated(program: CanonicalProgram) -> bool:
    for term in (program.application.terms.value or []):
        if term.deadline is not None or term.accept_decline_deadline is not None:
            return True
    return False


def _overview_freeze_ready(review) -> bool:
    return not any(("boilerplate" in f or "overview not source-backed" in f)
                   for f in review.needs_review)


def _rationale(review) -> str:
    host = urlparse(review.url or "").netloc or "unknown-host"
    return f"{review.degree_official or 'n/a'} · layout host {host}"


def freeze_corpus(
    *,
    fetcher,
    data_root: Path,
    freeze_id: str,
    corpus_version: str,
    code_baseline_commit: str,
    schema_version: str,
    now: datetime,
    selection: tuple[str, ...] = APPROVED_PROGRAMS,
    approved: tuple[str, ...] = APPROVED_PROGRAMS,
) -> dict:
    """Materialize + verify the frozen corpus; return the freeze manifest dict.

    Idempotent: an identical rerun (same inputs, same corpus_version) is a no-op;
    a changed rerun without a new corpus_version raises FreezeError (drift).
    """
    data_root = Path(data_root)
    frozen = data_root / "frozen_subset"
    programs_dir = frozen / "programs"
    sources_dir = frozen / "sources"
    manifests_dir = data_root / "manifests"
    manifest_path = manifests_dir / "freeze_manifest.json"

    # ── build into a staging area first (never clobber committed frozen data) ─
    with tempfile.TemporaryDirectory() as stage:
        stage = Path(stage)
        stage_programs = stage / "programs"
        stage_sources = stage / "sources"
        report = build_review_corpus(
            fetcher=fetcher, snapshot_store=SnapshotStore(stage_sources),
            out_dir=stage_programs, selection=selection, now=now,
        )

        # ── freeze-readiness gate (fail loudly) ──────────────────────────────
        if report.ambiguous:
            raise FreezeError(f"ambiguous/missing programs: {report.ambiguous}")
        got = sorted(r.canonical_name for r in report.reviews)
        if got != sorted(approved):
            raise FreezeError(f"built set differs from approved allowlist: got={got} approved={sorted(approved)}")

        manifest_records: list[dict] = []
        for review in sorted(report.reviews, key=lambda r: r.program_id):
            if review.errors:
                raise FreezeError(f"{review.program_id}: validation errors {review.errors}")
            if not _overview_freeze_ready(review):
                raise FreezeError(f"{review.program_id}: overview not freeze-ready {review.needs_review}")
            program = load_program(Path(review.canonical_path))
            if _has_fabricated(program):
                raise FreezeError(f"{review.program_id}: fabricated placeholder/date value")
            # resolve source references
            known = {s.source_id for s in program.sources}
            for _path, fact in iter_record_facts(program):
                for ref in fact.all_source_refs():
                    if ref not in known:
                        raise FreezeError(f"{review.program_id}: unresolved source_ref {ref}")
            # snapshot files must exist
            for src in program.sources:
                digest = src.content_hash.split(":", 1)[1]
                snap = stage_sources / _snapshot_dir(src.source_id, review.program_id) / f"{digest}.html"
                if not snap.exists():
                    raise FreezeError(f"{review.program_id}: missing snapshot for {src.source_id}")

        # ── compute per-record checksums (over the staged record files) ──────
        for review in sorted(report.reviews, key=lambda r: r.program_id):
            program = load_program(Path(review.canonical_path))
            record_checksum = _file_checksum(Path(review.canonical_path))
            sources_meta = []
            for src in program.sources:
                digest = src.content_hash.split(":", 1)[1]
                snap_dir = _snapshot_dir(src.source_id, review.program_id)
                sources_meta.append({
                    "source_id": src.source_id, "source_url": src.source_url,
                    "content_hash": src.content_hash,
                    "snapshot_path": f"frozen_subset/sources/{snap_dir}/{digest}.html",
                    "source_type": src.source_type.value,
                    "fetched_at": src.fetched_at.isoformat(),
                    "last_verified": src.last_verified.isoformat() if src.last_verified else None,
                })
            manifest_records.append({
                "program_id": program.identity.program_id,
                "record_id": program.record_id,
                "canonical_name": program.identity.canonical_name,
                "degree_type": program.identity.degree_type.value,
                "record_path": f"frozen_subset/programs/{program.identity.program_id}.json",
                "record_checksum": record_checksum,
                "validation_status": program.quality.validation_status.value,
                "review_status": "freeze_approved",
                "source_count": len(program.sources),
                "sources": sources_meta,
                "selection_rationale": _rationale(review),
            })

        aggregate = _aggregate_checksum([r["record_checksum"] for r in manifest_records])
        manifest = {
            "freeze_id": freeze_id,
            "freeze_timestamp": now.isoformat(),
            "code_baseline_commit": code_baseline_commit,
            "schema_version": schema_version,
            "corpus_version": corpus_version,
            "projection_version": PROJECTION_VERSION,
            "record_count": len(manifest_records),
            "approved_program_ids": [r["program_id"] for r in manifest_records],
            "aggregate_corpus_checksum": aggregate,
            "selection_axes_covered": SELECTION_AXES,
            "excluded_programs": EXCLUDED_NOTE,
            "immutability_notice": (
                "The frozen corpus is immutable. Do not edit records or snapshots "
                "in place. Any change requires a new freeze_id / corpus_version."
            ),
            "records": manifest_records,
        }

        # ── idempotent no-op / drift detection ───────────────────────────────
        if manifest_path.exists():
            existing = json.loads(manifest_path.read_text(encoding="utf-8"))
            if existing.get("corpus_version") == corpus_version:
                if existing.get("aggregate_corpus_checksum") == aggregate:
                    return existing  # deterministic no-op
                raise FreezeError(
                    "corpus content changed but corpus_version is unchanged; "
                    "bump corpus_version / freeze_id for any corpus change")

        # ── commit staging -> frozen dirs + manifest ─────────────────────────
        if programs_dir.exists():
            shutil.rmtree(programs_dir)
        if sources_dir.exists():
            shutil.rmtree(sources_dir)
        shutil.copytree(stage_programs, programs_dir)
        shutil.copytree(stage_sources, sources_dir)
        manifests_dir.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    verify_frozen_corpus(data_root)  # confirm integrity after writing
    return manifest


def verify_frozen_corpus(data_root: Path) -> None:
    """Recompute every record + source checksum from the committed files and
    confirm they match the manifest. Raises FreezeError on any mismatch."""
    data_root = Path(data_root)
    manifest_path = data_root / "manifests" / "freeze_manifest.json"
    if not manifest_path.exists():
        raise FreezeError("no freeze manifest present")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    record_checksums: list[str] = []
    for rec in manifest["records"]:
        rpath = data_root / rec["record_path"]
        if not rpath.exists():
            raise FreezeError(f"missing frozen record {rec['record_path']}")
        actual = _file_checksum(rpath)
        if actual != rec["record_checksum"]:
            raise FreezeError(f"record checksum mismatch for {rec['program_id']}")
        record_checksums.append(actual)
        for src in rec["sources"]:
            spath = data_root / src["snapshot_path"]
            if not spath.exists():
                raise FreezeError(f"missing snapshot {src['snapshot_path']}")
            if _file_checksum(spath) != src["content_hash"]:
                raise FreezeError(f"snapshot checksum mismatch for {src['source_id']}")

    if _aggregate_checksum(record_checksums) != manifest["aggregate_corpus_checksum"]:
        raise FreezeError("aggregate corpus checksum mismatch")
    if len(record_checksums) != manifest["record_count"]:
        raise FreezeError("record count mismatch")
