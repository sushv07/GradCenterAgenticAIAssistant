"""
rag/masters_catalog_report.py
Markdown rendering for the full-catalog build audit (Phase 8).

Rendering only: consumes a finished CatalogBuildStats and produces the audit
report deterministically. No I/O, no acquisition, no measurement.
"""
from __future__ import annotations

from rag.masters_catalog_metrics import CatalogBuildStats


def render_report(stats: CatalogBuildStats, *, top_n: int = 10) -> str:
    """Deterministic markdown audit report for one full-catalog build."""
    per_prog = {k: v for k, v in stats.chunks_per_program.items()
                if k != "(unattributed)"}
    ranked = sorted(per_prog.items(), key=lambda kv: (-kv[1], kv[0]))
    n_prog = len(per_prog) or 1
    avg_chunks = round(sum(per_prog.values()) / n_prog, 1)

    L = ["# Master's Full-Catalog Acquisition — Build & Quality Audit (Phase 8)", "",
         "## Directory discovery", "",
         f"- programs discovered: {stats.programs_discovered}",
         f"- unique seed URLs: {stats.unique_seed_urls}",
         f"- seed hosts: {dict(sorted(stats.seed_hosts.items()))}",
         f"- programs with discovery warnings: {stats.programs_with_warnings}",
         f"- index content hash: `{stats.index_content_hash}`", "",
         "## Nested page discovery", "",
         f"- unique pages: {stats.unique_pages} "
         f"(seed {stats.seed_pages} · nested {stats.nested_pages})",
         f"- shared pages (>1 program): {stats.shared_pages}",
         f"- programs skipped (no seed): {stats.skipped_no_seed}",
         f"- fetches: {stats.fetch_attempts} attempts · "
         f"{stats.fetch_failures} failures", "",
         "### Pages by classification", ""]
    for cat, n in sorted(stats.pages_by_category.items()):
        L.append(f"- {cat}: {n}")
    L += ["", "### Skipped by hygiene guards (Phase 9A)", ""]
    if stats.skipped_pages:
        L += [f"- `{url}` — {reason}"
              for url, reason in sorted(stats.skipped_pages.items())]
    else:
        L.append("(none)")
    L += ["", "## Extraction / validation", "",
          f"- pages processed: {stats.pages_processed}",
          f"- documents accepted: {stats.documents_accepted} "
          f"(+ {stats.directory_card_documents} directory cards)",
          f"- documents rejected: {stats.documents_rejected}",
          f"- empty pages: {stats.empty_pages}",
          f"- duplicate document IDs: {stats.duplicate_document_ids}",
          f"- redirects followed (final != requested): {stats.redirects_followed}", "",
          "### Rejections by reason", ""]
    for reason, n in sorted(stats.rejections_by_reason.items()):
        L.append(f"- {reason}: {n}")
    if not stats.rejections_by_reason:
        L.append("(none)")
    L += ["", "### Missing optional metadata (accepted docs)", ""]
    for k, v in sorted(stats.missing_metadata.items()):
        L.append(f"- {k}: {v}")
    L += ["", "## Program coverage", "",
          f"- programs with page content: {len(stats.programs_with_page_content)}",
          f"- programs WITHOUT page content: "
          f"{len(stats.programs_without_page_content)}", ""]
    if stats.programs_without_page_content:
        L += ["### Programs without any page document (cards only)", ""]
        L += [f"- {p}" for p in stats.programs_without_page_content]
    L += ["", "## Store", "",
          f"- master's chunks: {stats.masters_chunks}",
          f"- base-source chunks: {stats.base_chunks}",
          f"- total chunks: {stats.total_chunks}",
          f"- indexed vectors: {stats.indexed_vectors}",
          f"- avg chunks/program (attributed): {avg_chunks}", "",
          f"### Largest programs (top {top_n} by chunks)", ""]
    L += [f"- {name}: {n}" for name, n in ranked[:top_n]]
    L += ["", f"### Smallest programs (bottom {top_n} by chunks)", ""]
    L += [f"- {name}: {n}" for name, n in ranked[-top_n:][::-1]]
    L += ["", "## Stage timings (seconds)", ""]
    for k, v in stats.timings_s.items():
        L.append(f"- {k}: {v}")
    return "\n".join(L) + "\n"
