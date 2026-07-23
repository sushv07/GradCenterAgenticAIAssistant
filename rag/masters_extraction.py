"""
rag/masters_extraction.py
Master's content extraction → KnowledgeDocument conversion (Phase 3).

Composes existing pieces; introduces no new extraction or pipeline logic:

  DiscoveredPage (rag.masters_discovery)
      → fetch HTML (rag.ingestion.fetch_page, injectable for tests)
      → extract (ingestion.masters.extraction.extract_main_content_text — REUSED)
      → build record → KnowledgeDocument (ingestion.pipeline.loaders.masters — REUSED)
      → validate (ingestion.pipeline.validator.validate_document — REUSED)

Lives in rag/ because it consumes the crawler's output (rag.masters_discovery) and
fetches pages; `ingestion/` stays infra-free. Deterministic given a fixed fetch_fn.
Stops at validated KnowledgeDocuments — no chunking, embedding, or indexing.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional, Sequence

from ingestion.masters.extraction import extract_main_content_text
from ingestion.masters.manifest import DiscoveredProgram
from ingestion.masters.normalization import slugify
from ingestion.pipeline.documents import KnowledgeDocument
from ingestion.pipeline.loaders.masters import masters_page_to_document
from ingestion.pipeline.validator import ValidationIssue, validate_document
from rag.masters_discovery import DiscoveredPage, canonical_url


def fetch_page_final(url: str) -> tuple[Optional[str], str]:
    """Fetch a page and return (html, FINAL url after redirects).

    Phase 7 evidence: stale directory links (e.g. the CLA department pages)
    301-redirect to a college landing page; `rag.ingestion.fetch_page` follows
    the redirect but discards the final URL, so junk content was indexed under a
    misleading source URL. Capturing `resp.url` restores truthful provenance and
    lets redirect targets deduplicate. Same headers/timeout as rag.ingestion.
    """
    import requests
    from rag.ingestion import _FETCH_TIMEOUT, _HEADERS
    for attempt in (1, 2):
        try:
            resp = requests.get(url, timeout=_FETCH_TIMEOUT, headers=_HEADERS)
            if resp.status_code == 200 and resp.text:
                # Phase 9A: the downstream extractor parses HTML only. A
                # non-HTML Content-Type (e.g. application/pdf reached via an
                # extensionless URL or redirect) is unextractable — treat as
                # unfetchable rather than index a byte stream as text. An
                # absent header is assumed HTML (never observed on csulb.edu).
                ctype = (resp.headers.get("Content-Type") or "").lower()
                if ctype and "html" not in ctype:
                    return None, str(resp.url)
                return resp.text, str(resp.url)
        except requests.RequestException:
            pass
    return None, url


def _label(p: DiscoveredProgram) -> str:
    return f"{p.normalized_program_name} ({p.degree_label})" if p.degree_label \
        else p.normalized_program_name


@dataclass
class ConversionSummary:
    total_pages: int = 0
    documents_accepted: int = 0
    documents_rejected: int = 0
    empty_pages: int = 0
    duplicate_document_ids: int = 0
    avg_content_length: float = 0.0
    missing_metadata: dict[str, int] = field(default_factory=dict)
    rejections: list[tuple[str, str]] = field(default_factory=list)   # (url, reason)

    def render(self) -> str:
        L = ["# Master's KnowledgeDocument Conversion — Pilot Summary", "",
             f"- pages processed: {self.total_pages}",
             f"- documents accepted: {self.documents_accepted}",
             f"- documents rejected: {self.documents_rejected}",
             f"- empty pages: {self.empty_pages}",
             f"- duplicate document IDs: {self.duplicate_document_ids}",
             f"- average content length (accepted): {self.avg_content_length} chars", "",
             "## Missing optional metadata (accepted docs)", ""]
        for k, v in sorted(self.missing_metadata.items()):
            L.append(f"- {k}: {v}")
        if self.rejections:
            L += ["", "## Rejections", ""]
            L += [f"- {url}: {reason}" for url, reason in self.rejections]
        return "\n".join(L) + "\n"


def _record_for_page(page: DiscoveredPage, label_index: dict[str, DiscoveredProgram],
                     title: str, text: str) -> dict[str, Any]:
    program_name = degree = ""
    if len(page.programs) == 1:
        prog = label_index.get(page.programs[0])
        if prog is not None:
            program_name = prog.normalized_program_name
            degree = prog.degree_label or ""
    return {
        "source_url": page.url,
        "title": title or page.title,
        "text": text,
        "program_name": program_name,
        "degree": degree,
        "degree_level": "Masters",
        "department": "",              # deferred extraction (never fabricated)
        "college": "",
        "content_type": page.content_category,
        "workflow_priority": page.workflow_priority,
        "parent_program_url": page.parent_program_url,
        "crawl_depth": page.depth,
        "associated_programs": list(page.programs),
    }


def build_masters_documents(
    pages: Sequence[DiscoveredPage],
    programs: Sequence[DiscoveredProgram],
    *,
    fetch_fn: Optional[Callable[[str], Optional[str]]] = None,
    fetch_final_fn: Optional[Callable[[str], tuple[Optional[str], str]]] = None,
) -> tuple[list[KnowledgeDocument], ConversionSummary]:
    """Extract + convert discovered pages into validated KnowledgeDocuments.

    Fetching is redirect-aware: the document's source URL is the canonical FINAL
    URL, and pages whose final URLs collide (e.g. several stale department links
    all redirecting to one college landing page) are converted once. A plain
    `fetch_fn` (html only) may be injected for tests; it implies final == requested.
    """
    if fetch_final_fn is None:
        if fetch_fn is not None:
            def fetch_final_fn(u, _f=fetch_fn):
                return _f(u), u
        else:
            fetch_final_fn = fetch_page_final

    label_index = {_label(p): p for p in programs}
    summary = ConversionSummary(total_pages=len(pages))
    accepted: list[KnowledgeDocument] = []
    seen_ids: set[str] = set()
    seen_final_urls: set[str] = set()
    optional_fields = ("program_name", "degree", "department", "college")
    missing = {f: 0 for f in optional_fields}
    lengths: list[int] = []

    for page in pages:
        html, final_url = fetch_final_fn(page.url)
        if not html:
            summary.documents_rejected += 1
            summary.rejections.append((page.url, "fetch_failed"))
            continue
        final_url = canonical_url(final_url)
        if final_url in seen_final_urls:
            summary.documents_rejected += 1
            summary.rejections.append(
                (page.url, f"redirect_duplicate -> {final_url}"))
            continue
        seen_final_urls.add(final_url)
        if final_url != canonical_url(page.url):
            page = DiscoveredPage(**{**page.__dict__, "url": final_url})

        title, text = extract_main_content_text(html, fallback_title=page.title)
        record = _record_for_page(page, label_index, title, text)
        doc = masters_page_to_document(record)

        issues = validate_document(doc)
        errors = [i for i in issues if i.is_error]
        if not text.strip():
            summary.empty_pages += 1
        if errors:
            summary.documents_rejected += 1
            summary.rejections.append((page.url, "; ".join(i.code for i in errors)))
            continue

        if doc.document_id in seen_ids:
            summary.duplicate_document_ids += 1
        seen_ids.add(doc.document_id)

        for f in optional_fields:
            if not doc.metadata.get(f):
                missing[f] += 1
        lengths.append(len(doc.text))
        accepted.append(doc)

    summary.documents_accepted = len(accepted)
    summary.avg_content_length = round(sum(lengths) / len(lengths), 1) if lengths else 0.0
    summary.missing_metadata = missing
    return accepted, summary


# ---------------------------------------------------------------------------
# Directory-card documents (Phase 7)
# ---------------------------------------------------------------------------

def directory_card_documents(
    programs: Sequence[DiscoveredProgram], index_url: str,
) -> list[KnowledgeDocument]:
    """One KnowledgeDocument per directory card: advisor + deadline facts.

    Phase 6 evidence: advisor names/emails and per-term deadlines exist ONLY in
    the Graduate Studies directory cards, which were never indexed — the advisor
    eval category scored 0%. Each card becomes a small, self-contained document
    (mirroring the doctoral deadlines-page treatment) so these facts are
    retrievable through the same pipeline — no separate retrieval path.

    Only facts present on the card are written; nothing is fabricated. The
    source URL is the directory page plus a stable per-program fragment, giving
    each card a distinct deterministic document_id while remaining citable.
    """
    docs: list[KnowledgeDocument] = []
    for p in programs:
        label = _label(p)
        facts: list[str] = []
        if p.advisor_office:
            facts.append(f"Graduate Advisor / Office: {p.advisor_office}")
        if p.advisor_email:
            facts.append(f"Advisor Email: {p.advisor_email}")
        if p.phone:
            facts.append(f"Phone: {p.phone}")
        if p.fall_application_deadline:
            facts.append(f"Fall application deadline: {p.fall_application_deadline}")
        if p.fall_accept_decline_deadline:
            facts.append(f"Fall accept/decline deadline: {p.fall_accept_decline_deadline}")
        if p.spring_application_deadline:
            facts.append(f"Spring application deadline: {p.spring_application_deadline}")
        if p.spring_accept_decline_deadline:
            facts.append(f"Spring accept/decline deadline: {p.spring_accept_decline_deadline}")
        if p.term_availability:
            facts.append(f"Admission terms: {', '.join(p.term_availability)}")
        if p.stem_designated:
            facts.append("STEM designated: yes")
        if not facts:
            continue                     # card carried no facts — index nothing
        lines = [f"{label} — CSULB Master's Program Directory Information"] + facts
        if p.official_program_url:
            lines.append(f"Official program page: {p.official_program_url}")

        slug = slugify(f"{p.normalized_program_name}-{p.degree_label or ''}")
        record = {
            "source_url": f"{index_url}#{slug}",
            "title": f"{label} — Directory Information",
            "text": "\n".join(lines),
            "program_name": p.normalized_program_name,
            "degree": p.degree_label or "",
            "degree_level": "Masters",
            "content_type": "directory_card",
            "workflow_priority": 3,
            "parent_program_url": index_url,
            "crawl_depth": 0,
            "associated_programs": [label],
        }
        docs.append(masters_page_to_document(record))
    return docs
