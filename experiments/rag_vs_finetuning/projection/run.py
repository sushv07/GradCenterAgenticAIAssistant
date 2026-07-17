"""
experiments/rag_vs_finetuning/projection/run.py
Project the whole frozen corpus and persist deterministic artifacts (Phase P5).

Output format: a single deterministic JSONL file (documents.jsonl), lines sorted
by document_id. Chosen over one-file-per-document because it is a single
checksummable artifact, streams cleanly into P6 chunking, and has a stable,
diff-friendly ordering. No chunking, embedding, or Chroma work happens here.
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from domain.programs.models import CanonicalProgram
from experiments.rag_vs_finetuning.projection.models import RetrievalDocument
from experiments.rag_vs_finetuning.projection.project import (
    project_program, projection_checksum,
)


def project_corpus(data_root: Path) -> tuple[list[RetrievalDocument], dict]:
    data_root = Path(data_root)
    manifest = json.loads((data_root / "manifests" / "freeze_manifest.json").read_text("utf-8"))
    projection_version = manifest.get("projection_version", "projection-0.1")

    documents: list[RetrievalDocument] = []
    warnings: list[str] = []
    omitted_unknown = omitted_source_missing = 0
    by_degree = Counter()

    for rec in sorted(manifest["records"], key=lambda r: r["program_id"]):
        program = CanonicalProgram.model_validate(
            json.loads((data_root / rec["record_path"]).read_text("utf-8")))
        by_degree[rec["degree_type"]] += 1
        res = project_program(program, record_hash=rec["record_checksum"],
                              projection_version=projection_version)
        documents.extend(res.documents)
        warnings.extend(res.warnings)
        omitted_unknown += res.omitted_unknown
        omitted_source_missing += res.omitted_source_missing

    documents.sort(key=lambda d: d.document_id)
    by_section = Counter(d.section for d in documents)
    n_programs = len(manifest["records"])
    report = {
        "projection_version": projection_version,
        "frozen_program_count": n_programs,
        "frozen_source_count": sum(r["source_count"] for r in manifest["records"]),
        "projected_document_count": len(documents),
        "documents_by_section": dict(sorted(by_section.items())),
        "documents_by_degree_type": dict(sorted(by_degree.items())),
        "source_backed_section_coverage_pct": round(
            100 * len(documents) / (n_programs * 4), 1) if n_programs else 0.0,
        "omitted_unknown_facts": omitted_unknown,
        "omitted_source_missing_facts": omitted_source_missing,
        "stale_facts": sum(1 for d in documents if d.freshness_status == "stale"),
        "conflicting_source_warnings": sum(1 for w in warnings if "conflicting" in w),
        "projection_warnings": warnings,
        "aggregate_projection_checksum": projection_checksum(documents),
    }
    return documents, report


def persist_projection(documents: list[RetrievalDocument], report: dict, out_dir: Path) -> None:
    out_dir = Path(out_dir)
    docs_dir = out_dir / "projected_documents"
    docs_dir.mkdir(parents=True, exist_ok=True)
    lines = [
        json.dumps(d.model_dump(mode="json"), ensure_ascii=False, sort_keys=True)
        for d in sorted(documents, key=lambda d: d.document_id)
    ]
    (docs_dir / "documents.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (out_dir / "projection_report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
