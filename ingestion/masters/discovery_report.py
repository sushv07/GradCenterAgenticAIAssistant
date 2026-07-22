"""
ingestion/masters/discovery_report.py
Quality report for a Stage-1 master's DiscoveryManifest.

Pure (stdlib + the manifest model only): given a DiscoveryManifest it computes
inventory statistics and surfaces manual-review candidates (duplicate URLs,
ambiguous names, missing advisor/deadline fields, discovery warnings). It never
fetches, normalizes, or mutates — it only summarizes what discovery produced, so
the report is the reviewable baseline before nested crawling begins.
"""
from __future__ import annotations

from collections import Counter
from typing import Any

from ingestion.masters.manifest import DiscoveredProgram, DiscoveryManifest


def _has_deadline(p: DiscoveredProgram) -> bool:
    return any([p.spring_application_deadline, p.fall_application_deadline,
                p.spring_accept_decline_deadline, p.fall_accept_decline_deadline])


def _label(p: DiscoveredProgram) -> str:
    return f"{p.normalized_program_name} ({p.degree_label or '?'})"


def build_discovery_report(manifest: DiscoveryManifest) -> dict[str, Any]:
    """Compute an inventory + data-quality report from a DiscoveryManifest."""
    progs = manifest.programs

    url_counts = Counter(p.official_program_url for p in progs if p.official_program_url)
    name_counts = Counter(p.normalized_program_name for p in progs)

    duplicate_urls = {
        url: sorted(_label(p) for p in progs if p.official_program_url == url)
        for url, n in url_counts.items() if n > 1
    }
    duplicate_names = {
        name: sorted(p.degree_label or "?" for p in progs if p.normalized_program_name == name)
        for name, n in name_counts.items() if n > 1
    }

    missing_url = [_label(p) for p in progs if not p.official_program_url]
    missing_advisor = [_label(p) for p in progs
                       if not (p.advisor_email or p.advisor_office or p.phone)]
    missing_email = [_label(p) for p in progs if not p.advisor_email]
    missing_deadline = [_label(p) for p in progs if not _has_deadline(p)]
    with_warnings = {_label(p): p.warnings for p in progs if p.warnings}

    return {
        "discovery_source_url": manifest.discovery_source_url,
        "discovery_source_hash": manifest.discovery_source_hash,
        "statistics": {
            "programs_discovered": len(progs),
            "urls_extracted": sum(1 for p in progs if p.official_program_url),
            "unique_urls": len(url_counts),
            "unique_normalized_names": len(name_counts),
            "advisors_with_email": sum(1 for p in progs if p.advisor_email),
            "advisors_with_office": sum(1 for p in progs if p.advisor_office),
            "advisors_with_phone": sum(1 for p in progs if p.phone),
            "programs_with_deadline": sum(1 for p in progs if _has_deadline(p)),
            "stem_designated": sum(1 for p in progs if p.stem_designated),
            "programs_with_warnings": sum(1 for p in progs if p.warnings),
            "degree_labels": sorted({p.degree_label for p in progs if p.degree_label}),
        },
        "manual_review": {
            "duplicate_urls": duplicate_urls,             # shared department pages
            "duplicate_normalized_names": duplicate_names,  # same name, diff degree/format
            "missing_url": missing_url,
            "missing_advisor_all_fields": missing_advisor,
            "missing_advisor_email": missing_email,
            "missing_deadline": missing_deadline,
            "programs_with_warnings": with_warnings,
        },
        "manifest_warnings": list(manifest.warnings),
    }


def render_markdown(report: dict[str, Any]) -> str:
    s = report["statistics"]
    mr = report["manual_review"]
    L = ["# Master's Directory Discovery — Baseline Report", "",
         f"- source: {report['discovery_source_url']}",
         f"- source hash: `{report['discovery_source_hash']}`", "",
         "## Discovery statistics", "",
         f"- programs discovered: **{s['programs_discovered']}**",
         f"- URLs extracted: {s['urls_extracted']} ({s['unique_urls']} unique department pages)",
         f"- unique normalized names: {s['unique_normalized_names']}",
         f"- advisors parsed: email={s['advisors_with_email']} · office={s['advisors_with_office']} · phone={s['advisors_with_phone']}",
         f"- programs with a deadline: {s['programs_with_deadline']}",
         f"- STEM-designated (from index cards): {s['stem_designated']}",
         f"- programs with warnings: {s['programs_with_warnings']}",
         f"- degree labels: {', '.join(s['degree_labels'])}", "",
         "## Manual-review candidates", "",
         f"### Duplicate URLs ({len(mr['duplicate_urls'])}) — concentrations sharing one department page (nested crawl dedupes by URL)", ""]
    for url, who in sorted(mr["duplicate_urls"].items()):
        L.append(f"- `{url}`")
        L.append(f"  - {', '.join(who)}")
    L += ["", f"### Duplicate normalized names ({len(mr['duplicate_normalized_names'])}) — same name, different degree/format", ""]
    for name, degs in sorted(mr["duplicate_normalized_names"].items()):
        L.append(f"- **{name}** — degrees: {', '.join(degs)}")
    L += ["", "### Missing data", "",
          f"- missing URL: {len(mr['missing_url'])} {mr['missing_url'] or ''}",
          f"- missing all advisor fields: {len(mr['missing_advisor_all_fields'])} {mr['missing_advisor_all_fields'] or ''}",
          f"- missing advisor email: {len(mr['missing_advisor_email'])} {mr['missing_advisor_email'] or ''}",
          f"- missing deadline: {len(mr['missing_deadline'])} {mr['missing_deadline'] or ''}", "",
          f"### Discovery warnings ({len(mr['programs_with_warnings'])})", ""]
    for label, warns in sorted(mr["programs_with_warnings"].items()):
        L.append(f"- {label}: {'; '.join(warns)}")
    if report["manifest_warnings"]:
        L += ["", "### Manifest-level warnings", ""] + [f"- {w}" for w in report["manifest_warnings"]]
    return "\n".join(L) + "\n"
