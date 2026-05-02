"""
CSULB Grad Center – Answer Agent
Consumes retrieved data from query_handler and extracts a precise,
structured answer. Extraction is purely rule-based over the JSON data;
no LLM call is made here.
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field
from typing import Any

from query_handler import handle_query, _tokenize


# ---------------------------------------------------------------------------
# Answer data structure
# ---------------------------------------------------------------------------

@dataclass
class Answer:
    query: str
    answer: Any                     # str | list | dict – whatever fits the answer
    answer_type: str                # "direct" | "list" | "table" | "faq" | "unknown"
    source_file: str
    source_url: str
    confidence: str                 # "high" | "medium" | "low"
    next_steps: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "query": self.query,
            "answer": self.answer,
            "answer_type": self.answer_type,
            "source_file": self.source_file,
            "source_url": self.source_url,
            "confidence": self.confidence,
            "next_steps": self.next_steps,
        }


# ---------------------------------------------------------------------------
# Extractors – each returns (value, answer_type) or None
# ---------------------------------------------------------------------------

def _extract_faq(result_block: dict, query_tokens: set[str]) -> tuple[Any, str] | None:
    """Pick the single best-matching FAQ entry."""
    faqs = result_block.get("faqs", [])
    if not faqs:
        return None

    # Score on both question and answer tokens so semantically rich answers rank higher
    def _faq_score(faq: dict) -> int:
        combined = _tokenize(faq.get("question", "")) | _tokenize(faq.get("answer", ""))
        return len(combined & query_tokens)

    best = max(faqs, key=_faq_score)
    return {"question": best["question"], "answer": best["answer"]}, "faq"


_DEADLINE_TRIGGERS = {"deadline", "deadlines", "when", "due", "submit", "submission", "window", "semester", "date"}


def _extract_deadlines(result_block: dict, query_tokens: set[str]) -> tuple[Any, str] | None:
    """Pull deadline/date tables only when the query is about timing."""
    if not (_DEADLINE_TRIGGERS & query_tokens):
        return None

    deadlines = []

    def _walk(node: Any, label: str = "") -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                if any(word in k.lower() for word in ("deadline", "submission_window", "submission_deadline", "submission_period", "semester", "paper_date")):
                    deadlines.append({"label": k, "value": v})
                else:
                    _walk(v, k)
        elif isinstance(node, list):
            for item in node:
                _walk(item, label)

    _walk(result_block)
    return (deadlines, "table") if deadlines else None


_STEP_TRIGGERS = {"steps", "step", "process", "procedure", "how", "checklist", "applying"}


def _extract_steps(result_block: dict, query_tokens: set[str]) -> tuple[Any, str] | None:
    """Return an ordered steps list only when the query asks about a process or steps."""
    if not (_STEP_TRIGGERS & query_tokens):
        return None

    def _walk(node: Any) -> list[dict] | None:
        if isinstance(node, list):
            if all(isinstance(i, dict) and "step" in i for i in node):
                return [
                    {"step": i["step"], "title": i.get("title", ""), "details": i.get("details", "")}
                    for i in node
                ]
        if isinstance(node, dict):
            for v in node.values():
                result = _walk(v)
                if result:
                    return result
        return None

    steps = _walk(result_block)
    return (steps, "list") if steps else None


def _extract_contact(result_block: dict, query_tokens: set[str]) -> tuple[Any, str] | None:
    """Extract contact information when the query asks for it."""
    contact_triggers = {"contact", "email", "phone", "location", "hours", "where", "reach"}
    if not (contact_triggers & query_tokens):
        return None

    contacts = []

    def _walk(node: Any, parent_key: str = "") -> None:
        if isinstance(node, dict):
            if any(k in node for k in ("email", "phone", "location", "hours")):
                contacts.append({**{"context": parent_key}, **node})
            else:
                for k, v in node.items():
                    _walk(v, k)
        elif isinstance(node, list):
            for item in node:
                _walk(item, parent_key)

    _walk(result_block)
    return (contacts, "list") if contacts else None


def _extract_amounts(result_block: dict, query_tokens: set[str]) -> tuple[Any, str] | None:
    """Pull out dollar amounts / award values when the query is about money."""
    money_triggers = {"amount", "cost", "fee", "stipend", "prize", "prizes", "award", "pay", "salary", "grant", "much"}
    if not (money_triggers & query_tokens):
        return None

    amounts = []

    def _walk(node: Any, label: str = "") -> None:
        if isinstance(node, dict):
            if any(k in node for k in ("amount", "prize", "prizes", "stipend")):
                entry = {"label": node.get("name", label)}
                for key in ("amount", "prizes", "prize", "stipend"):
                    if key in node:
                        entry[key] = node[key]
                amounts.append(entry)
                return  # don't recurse further into this node
            for k, v in node.items():
                _walk(v, k)
        elif isinstance(node, list):
            for item in node:
                _walk(item, label)
        elif isinstance(node, str) and re.search(r"\$[\d,]+", node):
            amounts.append({"label": label, "value": node})

    _walk(result_block)
    seen = []
    deduped = []
    for a in amounts:
        key = json.dumps(a, sort_keys=True)
        if key not in seen:
            seen.append(key)
            deduped.append(a)
    return (deduped, "list") if deduped else None


def _extract_eligibility(result_block: dict, query_tokens: set[str]) -> tuple[Any, str] | None:
    """Return eligibility criteria when the query is about requirements."""
    eligibility_triggers = {"eligible", "eligibility", "qualify", "requirement", "require", "gpa", "who", "can"}
    if not (eligibility_triggers & query_tokens):
        return None

    def _walk(node: Any) -> list | None:
        if isinstance(node, dict):
            if "eligibility" in node:
                return node["eligibility"]
            if "minimum_requirements" in node:
                return node["minimum_requirements"]
            if "gpa_requirements" in node:
                return node["gpa_requirements"]
            for v in node.values():
                result = _walk(v)
                if result:
                    return result
        if isinstance(node, list):
            for item in node:
                result = _walk(item)
                if result:
                    return result
        return None

    result = _walk(result_block)
    return (result, "list") if result else None


def _extract_programs(result_block: dict, query_tokens: set[str]) -> tuple[Any, str] | None:
    """Return program listings when the query is about programs."""
    program_triggers = {"program", "programs", "degree", "degrees", "major", "offer", "available"}
    if not (program_triggers & query_tokens):
        return None

    def _walk(node: Any) -> list | None:
        if isinstance(node, dict):
            if "programs" in node and isinstance(node["programs"], list):
                return node["programs"]
            for v in node.values():
                r = _walk(v)
                if r:
                    return r
        return None

    result = _walk(result_block)
    return (result, "list") if result else None


def _extract_generic(result_block: dict, query_tokens: set[str]) -> tuple[Any, str]:
    """
    Fallback: walk the block and collect string values whose text overlaps
    with the query. Returns the most content-dense matching section.
    """
    skip = {"file", "title", "source", "last_scraped"}

    def _score_leaf(value: Any) -> int:
        if isinstance(value, str):
            return len(_tokenize(value) & query_tokens)
        if isinstance(value, list):
            return sum(_score_leaf(i) for i in value)
        if isinstance(value, dict):
            return sum(_score_leaf(v) for v in value.values())
        return 0

    scored = {
        k: (v, _score_leaf(v))
        for k, v in result_block.items()
        if k not in skip and _score_leaf(v) > 0
    }

    if not scored:
        # Return whatever non-metadata keys exist
        content = {k: v for k, v in result_block.items() if k not in skip}
        return content or "I don't know. No specific answer found in the retrieved data.", "unknown"

    best_key = max(scored, key=lambda k: scored[k][1])
    return {best_key: scored[best_key][0]}, "direct"


# ---------------------------------------------------------------------------
# Source URL resolver
# ---------------------------------------------------------------------------

def _resolve_source_url(result_block: dict, index_data: dict | None = None) -> str:
    """Return the most specific source URL found in the result block."""
    # Prefer inline source fields over index-level source_url
    for key in ("source", "source_url"):
        val = result_block.get(key, "")
        if val and val.startswith("http"):
            return val

    # Walk one level deep for nested source keys
    for v in result_block.values():
        if isinstance(v, dict):
            for key in ("source", "source_url"):
                val = v.get(key, "")
                if val and val.startswith("http"):
                    return val

    return "https://www.csulb.edu/graduate-center"


# ---------------------------------------------------------------------------
# Confidence scoring
# ---------------------------------------------------------------------------

def _score_confidence(answer: Any, answer_type: str, query_tokens: set[str]) -> str:
    if answer_type == "faq":
        return "high"
    if answer_type in ("table", "list") and isinstance(answer, list) and answer:
        return "high"
    if answer_type == "direct":
        content_tokens = _tokenize(json.dumps(answer))
        overlap = len(content_tokens & query_tokens)
        return "high" if overlap >= 3 else "medium" if overlap >= 1 else "low"
    if answer_type == "unknown" or (isinstance(answer, str) and "don't know" in answer):
        return "low"
    return "medium"


# ---------------------------------------------------------------------------
# Extractor pipeline
# ---------------------------------------------------------------------------

_EXTRACTORS = [
    _extract_steps,
    _extract_amounts,
    _extract_eligibility,
    _extract_contact,
    _extract_programs,
    _extract_deadlines,
]


def _run_extractors(result_block: dict, query_tokens: set[str]) -> tuple[Any, str]:
    """Try each extractor in order; return first match or fall back to generic."""
    for extractor in _EXTRACTORS:
        try:
            result = extractor(result_block, query_tokens)
        except TypeError:
            # Extractors that don't take query_tokens
            result = extractor(result_block)
        if result is not None:
            return result
    return _extract_generic(result_block, query_tokens)


# ---------------------------------------------------------------------------
# Main answer agent
# ---------------------------------------------------------------------------

def answer(query: str, retrieved: dict) -> dict:
    """
    Extract a precise answer from retrieved data.

    Args:
        query:     Original user query string.
        retrieved: Output dict from query_handler.handle_query().

    Returns:
        Structured Answer dict.
    """
    results = retrieved.get("results", [])
    next_steps = retrieved.get("next_steps", [])

    if not results or (len(results) == 1 and "message" in results[0]):
        return Answer(
            query=query,
            answer="I don't know. No relevant data was found for this query.",
            answer_type="unknown",
            source_file="",
            source_url="https://www.csulb.edu/graduate-center",
            confidence="low",
            next_steps=["Contact GraduateCenter@csulb.edu for assistance"],
        ).to_dict()

    query_tokens = _tokenize(query)

    # Pass 1: scan every result block for FAQ matches (highest precision)
    for block in results:
        faq_result = _extract_faq(block, query_tokens)
        if faq_result is not None:
            answer_value, answer_type = faq_result
            return Answer(
                query=query,
                answer=answer_value,
                answer_type=answer_type,
                source_file=block.get("file", ""),
                source_url=_resolve_source_url(block),
                confidence=_score_confidence(answer_value, answer_type, query_tokens),
                next_steps=next_steps,
            ).to_dict()

    # Pass 2: run extractor pipeline on the highest-ranked result block
    primary = results[0]
    source_file = primary.get("file", "")
    source_url = _resolve_source_url(primary)

    answer_value, answer_type = _run_extractors(primary, query_tokens)

    # Pass 3: if primary is low quality, try the second result block
    if answer_type == "unknown" and len(results) > 1:
        secondary = results[1]
        alt_value, alt_type = _run_extractors(secondary, query_tokens)
        if alt_type != "unknown":
            answer_value, answer_type = alt_value, alt_type
            source_file = secondary.get("file", source_file)
            source_url = _resolve_source_url(secondary)

    confidence = _score_confidence(answer_value, answer_type, query_tokens)

    return Answer(
        query=query,
        answer=answer_value,
        answer_type=answer_type,
        source_file=source_file,
        source_url=source_url,
        confidence=confidence,
        next_steps=next_steps,
    ).to_dict()


def ask(query: str) -> dict:
    """Convenience wrapper: retrieve + answer in one call."""
    retrieved = handle_query(query)
    return answer(query, retrieved)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    query = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else input("Enter your query: ")
    result = ask(query)
    print(json.dumps(result, indent=2))
