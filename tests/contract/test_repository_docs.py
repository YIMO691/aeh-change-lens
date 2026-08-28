from __future__ import annotations

import re
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]


class RepositoryDocumentationTests(unittest.TestCase):
    def test_standard_community_files_exist(self) -> None:
        required = (
            "README.md",
            "README.en.md",
            "LICENSE",
            "CONTRIBUTING.md",
            "SECURITY.md",
            "SUPPORT.md",
            "CODE_OF_CONDUCT.md",
            ".github/PULL_REQUEST_TEMPLATE.md",
            ".github/ISSUE_TEMPLATE/bug_report.yml",
            ".github/ISSUE_TEMPLATE/feature_request.yml",
            ".github/ISSUE_TEMPLATE/config.yml",
        )
        for relative in required:
            self.assertTrue((ROOT / relative).is_file(), relative)

    def test_issue_forms_have_required_metadata_and_body(self) -> None:
        template_dir = ROOT / ".github" / "ISSUE_TEMPLATE"
        for name in ("bug_report.yml", "feature_request.yml"):
            document = yaml.safe_load((template_dir / name).read_text(encoding="utf-8"))
            self.assertIsInstance(document.get("name"), str, name)
            self.assertIsInstance(document.get("description"), str, name)
            self.assertTrue(document.get("body"), name)
            ids = [item.get("id") for item in document["body"] if item.get("id")]
            self.assertEqual(len(ids), len(set(ids)), name)

        config = yaml.safe_load((template_dir / "config.yml").read_text(encoding="utf-8"))
        self.assertFalse(config["blank_issues_enabled"])
        self.assertTrue(config["contact_links"])

    def test_local_markdown_links_resolve(self) -> None:
        markdown_files = (
            ROOT / "README.md",
            ROOT / "README.en.md",
            ROOT / "CONTRIBUTING.md",
            ROOT / "SECURITY.md",
            ROOT / "SUPPORT.md",
            ROOT / "CODE_OF_CONDUCT.md",
            ROOT / "docs" / "README.md",
        )
        pattern = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")
        failures: list[str] = []
        for markdown in markdown_files:
            text = markdown.read_text(encoding="utf-8")
            for raw_target in pattern.findall(text):
                target = raw_target.split("#", 1)[0]
                if not target or "://" in target or target.startswith("mailto:"):
                    continue
                resolved = (markdown.parent / target).resolve()
                if not resolved.exists():
                    failures.append(f"{markdown.relative_to(ROOT)} -> {raw_target}")
        self.assertEqual([], failures)


if __name__ == "__main__":
    unittest.main()
