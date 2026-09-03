from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills" / "zhihu-public-content-collector" / "scripts" / "normalize_content.py"
SPEC = importlib.util.spec_from_file_location("normalize_content", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


class NormalizeContentTests(unittest.TestCase):
    def test_clean_html_and_unicode(self):
        cleaned = MODULE.clean_text("<p>中文&nbsp;<strong>证据</strong></p><script>bad()</script>")
        self.assertEqual(cleaned, "中文 证据")

    def test_dates_accept_unix_date_and_reject_invalid(self):
        self.assertEqual(MODULE.normalize_datetime(1735689600), "2025-01-01T00:00:00Z")
        self.assertEqual(MODULE.normalize_datetime("2025-02-03"), "2025-02-03T00:00:00Z")
        with self.assertRaisesRegex(ValueError, "非法日期"):
            MODULE.normalize_datetime("not-a-date")

    def test_build_corpus_deduplicates_and_records_failures(self):
        raw_path = ROOT / "tests" / "fixtures" / "raw-mixed.json"
        corpus = MODULE.build_corpus(
            [raw_path],
            "https://www.zhihu.com/people/example-author",
            "示例作者",
            "zhihu",
            "synthetic-test",
            True,
            None,
            "",
        )
        self.assertEqual(len(corpus["items"]), 2)
        self.assertEqual(len(corpus["errors"]), 2)
        self.assertFalse(corpus["meta"]["coverage"]["complete"])
        self.assertEqual(corpus["meta"]["requested_types"], ["answer", "article", "pin"])
        self.assertNotIn("secret()", corpus["items"][0]["body"])

    def test_cli_writes_utf8_json(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "corpus.json"
            status = MODULE.main(
                [
                    str(ROOT / "tests" / "fixtures" / "raw-mixed.json"),
                    "--profile-url",
                    "https://www.zhihu.com/people/example-author",
                    "--author-name",
                    "示例作者",
                    "--output",
                    str(output),
                ]
            )
            self.assertEqual(status, 0)
            parsed = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(parsed["author"]["name"], "示例作者")


if __name__ == "__main__":
    unittest.main()
