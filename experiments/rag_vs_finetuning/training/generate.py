"""
experiments/rag_vs_finetuning/training/generate.py
Deterministic SFT example generation from the FROZEN corpus (Phase P8.0).

Sources of truth: the frozen projected documents (grounded answerable facts) and
the frozen canonical records (which fields are source_missing/unknown -> refusal
examples). NOTHING is generated from Track A responses, evaluation outputs, or
benchmark questions. Templates are deliberately distinct from the evaluation
question templates; validation additionally rejects any exact benchmark-question
overlap. Facts are never invented or paraphrased beyond light readability.
"""
from __future__ import annotations

import json
from pathlib import Path

from experiments.rag_vs_finetuning.training.models import TrainingExample

GENERATION_VERSION = "ft-gen-0.1"
SCHEMA_VERSION = "ft-schema-1"
REFUSAL = "I don't have enough information in the provided Graduate Center data to answer that."

DATA_ROOT = Path("experiments/rag_vs_finetuning/data")

# Instruction templates — distinct from the evaluation benchmark templates.
_TEMPLATES = {
    "overview": ["Describe the {name} graduate program at CSULB.",
                 "Give an overview of the {name} program."],
    "application": ["List the application deadlines for the {name} program.",
                    "What is the fall application timeline for {name}?"],
    "contact": ["Provide the advisor and contact details for the {name} program.",
                "How can I reach the {name} program office?"],
    "admissions": ["Summarize the admission requirements for {name}.",
                   "State the published GPA/test requirements for {name}."],
}
_REFUSAL_TEMPLATES = {
    "stem": "Does the {name} program carry a STEM (OPT) designation?",
    "college": "What college is the {name} program part of?",
    "gpa": "Does {name} publish a specific minimum GPA requirement?",
    "tests": "Does the {name} program require the GRE for admission?",
}


def _load_canonical() -> dict:
    out = {}
    for p in sorted((DATA_ROOT / "frozen_subset" / "programs").glob("*.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        pid = d["identity"]["program_id"]
        missing = set()
        if d["admissions"]["minimum_gpa"]["data_status"] in ("source_missing", "unknown"):
            missing.add("gpa")
        if d["overview"]["stem_designated"]["data_status"] in ("source_missing", "unknown"):
            missing.add("stem")
        if d["identity"]["college"]["data_status"] in ("source_missing", "unknown"):
            missing.add("college")
        if d["admissions"]["tests"]["data_status"] in ("source_missing", "unknown"):
            missing.add("tests")
        out[pid] = {"name": d["identity"]["canonical_name"],
                    "degree": d["identity"]["degree_type_official"],
                    "missing": missing}
    return out


def _load_projected() -> dict:
    docs = {}
    lines = (DATA_ROOT / "projected_documents" / "documents.jsonl").read_text("utf-8").splitlines()
    for l in lines:
        if not l.strip():
            continue
        d = json.loads(l)
        docs[(d["program_id"], d["section"])] = (d["document_id"], d["content"])
    return docs


def generate_examples() -> list[TrainingExample]:
    canonical = _load_canonical()
    projected = _load_projected()
    examples: list[TrainingExample] = []
    n = 0

    def add(program, category, instruction, output, answerable, grounded):
        nonlocal n
        n += 1
        examples.append(TrainingExample(
            id=f"FT-{n:04d}", program=program, category=category,
            instruction=instruction, input="", output=output,
            answerable=answerable, grounded_in=grounded))

    # ── answerable examples from grounded projected sections ──────────────
    for pid, info in canonical.items():
        name = info["name"]
        for section in ("overview", "application", "contact", "admissions"):
            key = (pid, section)
            if key not in projected:
                continue
            doc_id, content = projected[key]
            for tmpl in _TEMPLATES[section]:
                add(pid, section, tmpl.format(name=name), content, True, [doc_id])

    # ── multi-field examples (combine grounded sections) ──────────────────
    for pid, info in canonical.items():
        name = info["name"]
        parts, grounded = [], []
        for section in ("overview", "application", "contact"):
            if (pid, section) in projected:
                did, content = projected[(pid, section)]
                parts.append(content)
                grounded.append(did)
        if len(parts) >= 2:
            add(pid, "multi_field",
                f"For the {name} program, give the degree overview, application "
                f"deadlines, and advisor contact.",
                " ".join(parts), True, grounded)

    # ── refusal examples for source_missing / unknown fields ──────────────
    for pid, info in canonical.items():
        name = info["name"]
        for field in ("stem", "college", "gpa", "tests"):
            if field in info["missing"]:
                add(pid, "refusal", _REFUSAL_TEMPLATES[field].format(name=name),
                    REFUSAL, False, [f"canonical:{field}=source_missing"])

    return examples
