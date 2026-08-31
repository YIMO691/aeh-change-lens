from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "integrations/codex/aeh-change-lens"


class CodexSkillIntegrationTests(unittest.TestCase):
    def test_skill_is_explicit_only_and_contains_no_scaffold_placeholders(self) -> None:
        instructions = (SKILL / "SKILL.md").read_text(encoding="utf-8")
        metadata = yaml.safe_load(
            (SKILL / "agents/openai.yaml").read_text(encoding="utf-8")
        )

        self.assertIn("name: aeh-change-lens", instructions)
        self.assertNotIn("TODO", instructions)
        self.assertFalse(metadata["policy"]["allow_implicit_invocation"])
        self.assertIn("$aeh-change-lens", metadata["interface"]["default_prompt"])
        self.assertIn("Never run `export-compile-manifest`", instructions)
        self.assertIn("--allow-syntax-partial", instructions)
        self.assertIn("quick understanding", instructions)
        self.assertIn("change-story.json", instructions)

        workflow = (SKILL / "references/workflow.md").read_text(encoding="utf-8")
        self.assertIn("D:\\ares2\\project\\ET6", workflow)
        self.assertIn("--allow-syntax-partial", workflow)
        self.assertIn("--progress", workflow)
        self.assertIn("--story-output", workflow)
        self.assertIn("quick_view.summary_zh", workflow)
        self.assertIn("deep_dive.stages", workflow)

    def test_source_checkout_runner_needs_no_package_install(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(ROOT / "run_change_lens.py"), "--help"],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            encoding="utf-8",
        )

        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertIn("explain", completed.stdout)
        self.assertIn("生成快速理解/详细拆解 Change Story", completed.stdout)


if __name__ == "__main__":
    unittest.main()
