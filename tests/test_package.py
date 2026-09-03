from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "validate_package.py"
SPEC = importlib.util.spec_from_file_location("validate_package", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


class PackageTests(unittest.TestCase):
    def test_package_contract(self):
        self.assertEqual(MODULE.validate(), [])


if __name__ == "__main__":
    unittest.main()
