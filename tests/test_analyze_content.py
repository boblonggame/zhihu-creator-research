from __future__ import annotations

import copy
import importlib.util
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills" / "creator-content-analyzer" / "scripts" / "analyze_content.py"
SPEC = importlib.util.spec_from_file_location("analyze_content", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


class AnalyzeContentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = json.loads((ROOT / "tests" / "fixtures" / "sample-corpus.json").read_text(encoding="utf-8"))

    def test_valid_partial_corpus(self):
        self.assertEqual(MODULE.validate_corpus(self.fixture), [])

    def test_keyword_counts_title_and_body_separately(self):
        summary = MODULE.create_summary(self.fixture, ["复盘", "证据"])
        self.assertEqual(summary["keywords"]["复盘"]["title_count"], 1)
        self.assertEqual(summary["keywords"]["复盘"]["body_count"], 3)
        self.assertEqual(summary["keywords"]["证据"]["item_count"], 3)
        self.assertTrue(summary["keywords"]["证据"]["evidence"][0]["source_url"].startswith("https://"))

    def test_empty_corpus_is_valid_but_has_no_sample(self):
        empty = copy.deepcopy(self.fixture)
        empty["items"] = []
        empty["errors"] = []
        empty["meta"]["coverage"] = {"discovered": 0, "collected": 0, "failed": 0, "complete": True, "note": ""}
        empty["meta"]["time_range"] = {"start": None, "end": None}
        self.assertEqual(MODULE.validate_corpus(empty), [])
        self.assertEqual(MODULE.create_summary(empty, ["证据"])["sample"]["total_items"], 0)

    def test_duplicate_and_missing_source_are_rejected(self):
        broken = copy.deepcopy(self.fixture)
        broken["items"][1]["id"] = broken["items"][0]["id"]
        broken["items"][1]["type"] = broken["items"][0]["type"]
        broken["items"][2]["source_url"] = ""
        errors = MODULE.validate_corpus(broken)
        self.assertTrue(any("重复 type/id" in error for error in errors))
        self.assertTrue(any("source_url" in error for error in errors))

    def test_complete_cannot_hide_partial_failure(self):
        broken = copy.deepcopy(self.fixture)
        broken["meta"]["coverage"]["complete"] = True
        self.assertTrue(any("complete=true" in error for error in MODULE.validate_corpus(broken)))

    def test_markdown_contains_coverage_warning(self):
        summary = MODULE.create_summary(self.fixture, ["证据"])
        markdown = MODULE.to_markdown(summary)
        self.assertIn("完整性：不完整", markdown)
        self.assertIn("合成的详情页不可达错误", markdown)


if __name__ == "__main__":
    unittest.main()
