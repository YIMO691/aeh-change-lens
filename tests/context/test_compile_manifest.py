from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from aeh_change_lens.cli import main  # noqa: E402
from aeh_change_lens.languages.csharp import (  # noqa: E402
    CompileManifest,
    CompileManifestExporter,
)
from tests.contract.test_contracts import validate  # noqa: E402


def git(root: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", "-C", os.fspath(root), *arguments],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    ).stdout.strip()


class CompileManifestTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()
        unity = self.root / "Unity"
        (unity / "Assets/Game").mkdir(parents=True)
        (unity / "ProjectSettings").mkdir()
        (unity / "Assets/Game/Game.asmdef").write_text(
            '{"name":"Game","noEngineReferences":true}\n', encoding="utf-8"
        )
        (unity / "Assets/Game/Game.cs").write_text(
            "namespace Fixture; public sealed class Game {}\n", encoding="utf-8"
        )
        (unity / "ProjectSettings/ProjectVersion.txt").write_text(
            "m_EditorVersion: 2022.3.62f1\n", encoding="utf-8"
        )
        (unity / "Game.csproj").write_text("""<Project>
  <PropertyGroup><DefineConstants>UNITY_EDITOR;FEATURE_X</DefineConstants></PropertyGroup>
  <ItemGroup><Compile Include="Assets/Game/**/*.cs" /></ItemGroup>
</Project>
""", encoding="utf-8")
        (self.root / ".gitignore").write_text("*.csproj\n", encoding="utf-8")
        git(self.root, "init", "-q")
        git(self.root, "config", "user.name", "Change Lens Test")
        git(self.root, "config", "user.email", "change-lens@example.invalid")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_export_is_deterministic_portable_and_schema_valid(self) -> None:
        exporter = CompileManifestExporter(self.root, "Unity")
        first = exporter.build("Game")
        second = exporter.build("Game")

        self.assertEqual(first, second)
        validate("compile-manifest.schema.json", first.to_dict())
        serialized = json.dumps(first.to_dict(), ensure_ascii=False)
        self.assertNotIn(os.fspath(self.root), serialized)
        self.assertEqual(("FEATURE_X", "UNITY_EDITOR"), first.defines)
        self.assertEqual("Assets/Game/Game.cs", first.source_files[0].path)
        self.assertEqual(CompileManifest.from_bytes(
            json.dumps(first.to_dict()).encode("utf-8")
        ), first)

    def test_tampered_manifest_digest_is_rejected(self) -> None:
        manifest = CompileManifestExporter(self.root, "Unity").build("Game").to_dict()
        manifest["defines"][0] = "FEATURE_Y"

        with self.assertRaisesRegex(ValueError, "canonical digest mismatch"):
            CompileManifest.from_bytes(json.dumps(manifest).encode("utf-8"))

    def test_version_define_is_recomputed_not_baked_into_manifest(self) -> None:
        asmdef = self.root / "Unity/Assets/Game/Game.asmdef"
        asmdef.write_text(json.dumps({
            "name": "Game",
            "noEngineReferences": True,
            "versionDefines": [{
                "name": "Unity", "expression": "2022.3", "define": "FROM_VERSION"
            }],
        }), encoding="utf-8")

        manifest = CompileManifestExporter(self.root, "Unity").build("Game")

        self.assertNotIn("FROM_VERSION", manifest.defines)
        self.assertEqual(("FEATURE_X", "UNITY_EDITOR"), manifest.defines)

    def test_cli_exports_fixed_snapshot_visible_path(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            exit_code = main([
                "export-compile-manifest", os.fspath(self.root), "Unity",
                "--assembly", "Game",
            ])

        self.assertEqual(0, exit_code)
        result = json.loads(output.getvalue())
        self.assertEqual("EXPORTED", result["status"])
        self.assertEqual(
            "Unity/.aeh-change-lens/compile-manifests/Game.json", result["path"]
        )
        validate("compile-manifest.schema.json", result["manifest"])
        git(self.root, "add", ".")
        self.assertIn(result["path"], git(self.root, "ls-files").splitlines())

    def test_dry_run_does_not_write(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            exit_code = main([
                "export-compile-manifest", os.fspath(self.root), "Unity",
                "--assembly", "Game", "--dry-run",
            ])

        self.assertEqual(0, exit_code)
        self.assertEqual("VALIDATED", json.loads(output.getvalue())["status"])
        self.assertFalse((
            self.root / "Unity/.aeh-change-lens/compile-manifests/Game.json"
        ).exists())


if __name__ == "__main__":
    unittest.main()
