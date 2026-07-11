import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"


def run_ai_capability(api_key: str) -> subprocess.CompletedProcess:
    with tempfile.TemporaryDirectory() as tmp:
        env = os.environ.copy()
        env.update(
            {
                "PYTHONPATH": str(BACKEND),
                "FEATURE_AI": "true",
                "AI_API_KEY": api_key,
                "AI_CONFIG_PATH": str(Path(tmp) / "ai_config.json"),
            }
        )
        code = """
import json, sys, types
sys.modules["anthropic"] = types.ModuleType("anthropic")
from core.features import is_ai_available
print(json.dumps({"available": is_ai_available()}))
"""
        return subprocess.run(
            [sys.executable, "-c", code],
            cwd=str(ROOT),
            env=env,
            text=True,
            capture_output=True,
            timeout=30,
        )


class FeatureCapabilityTests(unittest.TestCase):
    def test_ai_requires_effective_api_key(self):
        result = run_ai_capability("")
        self.assertEqual(0, result.returncode, result.stderr)
        payload = json.loads(result.stdout.strip().splitlines()[-1])
        self.assertFalse(payload["available"])

    def test_ai_is_available_with_sdk_and_api_key(self):
        result = run_ai_capability("test-api-key")
        self.assertEqual(0, result.returncode, result.stderr)
        payload = json.loads(result.stdout.strip().splitlines()[-1])
        self.assertTrue(payload["available"])


if __name__ == "__main__":
    unittest.main()
