from __future__ import annotations

import io
import json
import os
import shutil
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
    BuildProvenanceExporter,
    BuildProvenanceManifest,
    CompileManifestExporter,
    RevisionWorkerInputAssembler,
    RoslynWorkerRunner,
)
from aeh_change_lens.snapshot import SnapshotResolver, SnapshotStaleError  # noqa: E402
from tests.contract.test_contracts import validate  # noqa: E402


WORKER_DLL = (
    ROOT / "worker/ChangeLens.Analyzer/bin/Release/net8.0/ChangeLens.Analyzer.dll"
)


def git(root: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", "-C", os.fspath(root), *arguments],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    ).stdout.strip()


class BuildProvenanceRepository:
    def __init__(self, root: Path) -> None:
        self.root = root
        unity = root / "Unity"
        for relative in (
            "Assets/Game", "Assets/Dependency", "ProjectSettings", "Packages",
            "Library/ScriptAssemblies",
        ):
            (unity / relative).mkdir(parents=True, exist_ok=True)
        (root / ".gitignore").write_text("*.csproj\nLibrary/\n", encoding="utf-8")
        (unity / "ProjectSettings/ProjectVersion.txt").write_text(
            "m_EditorVersion: 2022.3.62f1\n", encoding="utf-8"
        )
        (unity / "Packages/packages-lock.json").write_text(
            '{"dependencies":{}}\n', encoding="utf-8"
        )
        (unity / "Assets/Game/Game.asmdef").write_text(
            '{"name":"Game","references":["Dependency"],"noEngineReferences":true}\n',
            encoding="utf-8",
        )
        (unity / "Assets/Dependency/Dependency.asmdef").write_text(
            '{"name":"Dependency","noEngineReferences":true}\n', encoding="utf-8"
        )
        (unity / "Assets/Game/Game.cs").write_text(
            "namespace Fixture; public sealed class Game {}\n", encoding="utf-8"
        )
        (unity / "Assets/Dependency/Dependency.cs").write_text(
            "namespace Fixture; public sealed class Dependency {}\n", encoding="utf-8"
        )
        (unity / "Dependency.csproj").write_text("""<Project>
  <PropertyGroup><DefineConstants>UNITY_EDITOR</DefineConstants></PropertyGroup>
  <ItemGroup><Compile Include="Assets/Dependency/**/*.cs" /></ItemGroup>
</Project>
""", encoding="utf-8")
        (unity / "Game.csproj").write_text("""<Project>
  <PropertyGroup><DefineConstants>UNITY_EDITOR</DefineConstants></PropertyGroup>
  <ItemGroup>
    <ProjectReference Include="Dependency.csproj"><Name>Dependency</Name></ProjectReference>
    <Compile Include="Assets/Game/**/*.cs" />
  </ItemGroup>
</Project>
""", encoding="utf-8")
        if not WORKER_DLL.is_file():
            raise RuntimeError("repository-owned Roslyn worker must be built before tests")
        self.dependency_output = unity / "Library/ScriptAssemblies/Dependency.dll"
        shutil.copyfile(WORKER_DLL, self.dependency_output)
        shutil.copyfile(WORKER_DLL, unity / "Library/ScriptAssemblies/Game.dll")
        git(root, "init", "-q")
        git(root, "config", "user.name", "Change Lens Test")
        git(root, "config", "user.email", "change-lens@example.invalid")
        compile_exporter = CompileManifestExporter(root, "Unity")
        for assembly in ("Dependency", "Game"):
            compile_exporter.write(compile_exporter.build(assembly))
        build_exporter = BuildProvenanceExporter(root, "Unity")
        build_exporter.write(build_exporter.build("Dependency"))
        git(root, "add", ".")
        git(root, "commit", "-qm", "attested baseline")
        self.head = git(root, "rev-parse", "HEAD")


class BuildProvenanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        subprocess.run(
            ["dotnet", "build", os.fspath(
                ROOT / "worker/ChangeLens.Analyzer/ChangeLens.Analyzer.csproj"
            ), "-c", "Release", "--nologo"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()
        self.repository = BuildProvenanceRepository(self.root)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_manifest_is_portable_schema_valid_and_round_trips(self) -> None:
        path = self.root / "Unity/.aeh-change-lens/build-manifests/Dependency.json"
        manifest = BuildProvenanceManifest.from_bytes(path.read_bytes())

        validate("build-provenance.schema.json", manifest.to_dict())
        self.assertEqual("ATTESTED_HASH_CLOSURE", manifest.assurance)
        self.assertEqual("EXTERNAL_UNITY_BUILD", manifest.producer)
        self.assertNotIn(os.fspath(self.root), json.dumps(manifest.to_dict()))
        self.assertEqual("Dependency.dll", manifest.output.name)

    def test_revision_input_accepts_attested_project_reference_and_worker(self) -> None:
        resolver = SnapshotResolver(self.root)
        assembly = RevisionWorkerInputAssembler(resolver, "Unity").assemble(
            resolver.resolve_revision(self.repository.head, "OLD"),
            "Game",
            "ATTESTED-OLD",
        )

        references = assembly.worker_input.unity_context["references"]
        self.assertEqual({"PROJECT_ATTESTED"}, {item["kind"] for item in references})
        self.assertTrue(any("外部构建哈希证明" in item for item in assembly.limitations))
        self.assertEqual("PARTIAL", assembly.context_completeness)
        result = RoslynWorkerRunner().run(assembly.worker_input)
        self.assertIn(result["status"], {"COMPLETE", "PARTIAL"})

    def test_root_build_attestation_closes_direct_project_input_hash(self) -> None:
        manifest = BuildProvenanceExporter(self.root, "Unity").build("Game")

        validate("build-provenance.schema.json", manifest.to_dict())
        self.assertEqual(1, len(manifest.project_inputs))
        self.assertEqual("Dependency", manifest.project_inputs[0].assembly_name)
        self.assertEqual(
            BuildProvenanceExporter(self.root, "Unity").build("Dependency").output.sha256,
            manifest.project_inputs[0].output_sha256,
        )

    def test_worktree_output_change_fails_closed(self) -> None:
        self.repository.dependency_output.write_bytes(b"changed external output")
        resolver = SnapshotResolver(self.root)

        with self.assertRaisesRegex(SnapshotStaleError, "output digest mismatch"):
            RevisionWorkerInputAssembler(resolver, "Unity").assemble(
                resolver.resolve_worktree("NEW"), "Game", "STALE-OUTPUT"
            )

    def test_export_rejects_output_older_than_reexported_sources(self) -> None:
        source = self.root / "Unity/Assets/Dependency/Dependency.cs"
        source.write_text(
            "namespace Fixture; public sealed class Dependency { int Changed; }\n",
            encoding="utf-8",
        )
        future = self.repository.dependency_output.stat().st_mtime + 10
        os.utime(source, (future, future))
        compile_exporter = CompileManifestExporter(self.root, "Unity")
        compile_exporter.write(compile_exporter.build("Dependency"))

        with self.assertRaisesRegex(ValueError, "predates an observed compile input"):
            BuildProvenanceExporter(self.root, "Unity").build("Dependency")

    def test_old_revision_with_unavailable_output_degrades_instead_of_substituting(self) -> None:
        self.repository.dependency_output.write_bytes(b"new revision output")
        resolver = SnapshotResolver(self.root)

        assembly = RevisionWorkerInputAssembler(resolver, "Unity").assemble(
            resolver.resolve_revision(self.repository.head, "OLD"),
            "Game",
            "OLD-OUTPUT-UNAVAILABLE",
        )

        self.assertFalse(any(
            item["kind"] == "PROJECT_ATTESTED"
            for item in assembly.worker_input.unity_context["references"]
        ))
        self.assertEqual("PARTIAL", assembly.context_completeness)

    def test_cli_dry_run_and_tamper_rejection(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            exit_code = main([
                "export-build-provenance", os.fspath(self.root), "Unity",
                "--assembly", "Dependency", "--dry-run",
            ])
        self.assertEqual(0, exit_code)
        result = json.loads(output.getvalue())
        self.assertEqual("VALIDATED", result["status"])
        validate("build-provenance.schema.json", result["manifest"])

        tampered = result["manifest"]
        tampered["output"]["sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "canonical digest mismatch"):
            BuildProvenanceManifest.from_bytes(json.dumps(tampered).encode("utf-8"))


if __name__ == "__main__":
    unittest.main()
