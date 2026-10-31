"""Run lifecycle regressions for the shipped JavaScript without browser dependencies."""
from pathlib import Path
import shutil
import subprocess
import unittest


@unittest.skipUnless(shutil.which('node'), 'Node.js required for frontend lifecycle tests')
class PreviewFrontendTests(unittest.TestCase):
    def test_request_lifecycle(self):
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run(['node', str(root/'tests/frontend/preview.test.cjs')],
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
