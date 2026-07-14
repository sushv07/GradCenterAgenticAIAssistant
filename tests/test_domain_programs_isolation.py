"""
tests/test_domain_programs_isolation.py
Architecture-invariant guards for the domain.programs foundation (Phase P1.1).

Engine independence is verified with AST-based import inspection (not string
matching): the canonical domain package must depend only on the standard
library, Pydantic, and domain-local modules — never on RAG/Chroma/embeddings/
inference/serving/experiment/web-framework packages.

Also verifies: production never imports experiments, the canonical domain never
imports production RAG, tracked " 2" duplicate files are never referenced,
sample records never live under the production corpus path, and no vector store
or model artifact is created by this phase.

Run: pytest tests/test_domain_programs_isolation.py -v
"""
from __future__ import annotations

import ast
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

ROOT = Path(__file__).parent.parent
DOMAIN_PKG = ROOT / "domain"
_SKIP_DIRS = {".venv", "venv", "__pycache__", ".git", "node_modules", "chroma_db"}

# Infrastructure / framework roots the canonical domain must never import.
_FORBIDDEN_IMPORT_ROOTS = {
    "langchain", "langchain_community", "langchain_core", "langchain_text_splitters",
    "chromadb", "chroma", "sentence_transformers", "torch", "transformers",
    "ollama", "openai", "fastapi", "starlette", "streamlit", "uvicorn",
    "faiss", "pinecone", "peft", "trl", "bitsandbytes", "accelerate", "datasets",
    # in-repo infrastructure / production wiring the domain must stay free of
    "rag", "retrieval", "agents", "orchestrator", "routing", "responses",
    "api", "backend", "services", "tools", "experiments", "ingestion",
}

_DUP2_IMPORT = re.compile(r"(from|import)\s+[\w.]* 2(\.|\s|$)")


def _py_files(*roots: Path):
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*.py"):
            if any(part in _SKIP_DIRS for part in path.parts):
                continue
            if " 2." in path.name:  # never read tracked duplicate files
                continue
            yield path


def _imported_roots(path: Path) -> set[str]:
    """Top-level module names imported by a file, via AST (not string match)."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                roots.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.level and node.level > 0:
                continue  # relative import → domain-local, always allowed
            if node.module:
                roots.add(node.module.split(".")[0])
    return roots


class TestCanonicalDomainEngineIndependence(unittest.TestCase):
    def test_domain_imports_no_infrastructure(self):
        offenders = []
        for path in _py_files(DOMAIN_PKG):
            forbidden = _imported_roots(path) & _FORBIDDEN_IMPORT_ROOTS
            if forbidden:
                offenders.append(f"{path.relative_to(ROOT)}: {sorted(forbidden)}")
        self.assertEqual(offenders, [], f"domain imports infrastructure: {offenders}")

    def test_domain_import_roots_are_allowlisted(self):
        allowed = {"domain", "pydantic", "typing", "typing_extensions"}
        # plus anything in the standard library
        stdlib = set(getattr(sys, "stdlib_module_names", set()))
        offenders = []
        for path in _py_files(DOMAIN_PKG):
            for root in _imported_roots(path):
                if root in allowed or root in stdlib:
                    continue
                offenders.append(f"{path.relative_to(ROOT)}: {root}")
        self.assertEqual(offenders, [], f"unexpected imports in domain: {offenders}")


class TestProductionDoesNotImportExperiment(unittest.TestCase):
    def test_no_production_module_imports_experiments(self):
        offenders = []
        for path in _py_files(ROOT):
            rel = path.relative_to(ROOT)
            if rel.parts and rel.parts[0] in ("tests", "experiments"):
                continue
            if "experiments" in _imported_roots(path):
                offenders.append(str(rel))
        self.assertEqual(offenders, [], f"production imports experiments: {offenders}")


class TestNoDuplicateFileReferences(unittest.TestCase):
    def test_domain_and_new_tests_avoid_space2_imports(self):
        offenders = []
        targets = list(_py_files(DOMAIN_PKG))
        targets += list((ROOT / "tests").glob("test_domain_programs_*.py"))
        for path in targets:
            for line in path.read_text(encoding="utf-8").splitlines():
                if _DUP2_IMPORT.search(line):
                    offenders.append(f"{path.name}: {line.strip()}")
        self.assertEqual(offenders, [], f"references to ' 2' files: {offenders}")


class TestFixturesNotInProductionCorpus(unittest.TestCase):
    _NAMES = ("well_documented", "sparse", "domestic_international")

    def test_samples_live_under_fixtures(self):
        fx = ROOT / "tests" / "fixtures" / "masters_programs"
        for name in self._NAMES:
            self.assertTrue((fx / f"{name}.json").exists(), name)

    def test_no_samples_under_production_path(self):
        prod = ROOT / "data" / "masters" / "programs"
        if prod.exists():
            for name in self._NAMES:
                self.assertFalse((prod / f"{name}.json").exists(),
                                 f"{name} must not be in the production corpus")


class TestNoHeavyArtifactsCreated(unittest.TestCase):
    def test_experiment_persist_dir_absent(self):
        persist = ROOT / "experiments" / "rag_vs_finetuning" / "artifacts" / "chroma" / "frozen_v1"
        self.assertFalse(persist.exists(), "experiment vector store must not be created in P1")

    def test_no_model_weight_files_added(self):
        for pattern in ("*.safetensors", "*.bin", "*.gguf", "*.pt"):
            hits = [
                p for p in ROOT.rglob(pattern)
                if not any(part in _SKIP_DIRS for part in p.parts)
            ]
            self.assertEqual(hits, [], f"unexpected model weight files: {hits}")


if __name__ == "__main__":
    unittest.main()
