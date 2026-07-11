import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class NoRagRuntimeTests(unittest.TestCase):
    def test_runtime_sources_do_not_reference_removed_rag_stack(self):
        paths = [ROOT / "backend", ROOT / "frontend" / "src"]
        forbidden = (
            "chromadb",
            "vectorstore",
            "rag_service",
            "/rag/query",
            "/api/search",
            "semanticresults",
            "searchmode",
        )
        matches = []

        for base in paths:
            for path in base.rglob("*"):
                if path.suffix not in {".py", ".js", ".vue", ".txt"} or "tests" in path.parts:
                    continue
                content = path.read_text(encoding="utf-8", errors="ignore").lower()
                for token in forbidden:
                    if token in content:
                        matches.append(f"{path.relative_to(ROOT)}: {token}")

        self.assertEqual([], matches)

    def test_requirements_do_not_install_chromadb(self):
        matches = []
        for path in (ROOT / "backend").glob("requirements*.txt"):
            if "chromadb" in path.read_text(encoding="utf-8", errors="ignore").lower():
                matches.append(str(path.relative_to(ROOT)))
        self.assertEqual([], matches)

    def test_runtime_uses_only_sqlite_background_jobs(self):
        forbidden = ("core.task_manager", "core.task_queue")
        matches = []
        for path in (ROOT / "backend").rglob("*.py"):
            if "tests" in path.parts:
                continue
            content = path.read_text(encoding="utf-8", errors="ignore").lower()
            for token in forbidden:
                if token in content:
                    matches.append(f"{path.relative_to(ROOT)}: {token}")
        self.assertEqual([], matches)

    def test_web_runtime_does_not_call_whisper_in_process(self):
        matches = []
        for path in (ROOT / "backend").rglob("*.py"):
            if "tests" in path.parts or path.name == "whisper_worker.py":
                continue
            content = path.read_text(encoding="utf-8", errors="ignore")
            if "transcribe_video_async(" in content or "transcribe_video(" in content:
                matches.append(str(path.relative_to(ROOT)))
        self.assertEqual([], matches)


if __name__ == "__main__":
    unittest.main()
