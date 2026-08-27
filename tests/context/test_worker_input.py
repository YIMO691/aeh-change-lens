from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from aeh_change_lens.languages.csharp import (  # noqa: E402
    UnityContextBuilder,
    WorkerInputAssembler,
)
from aeh_change_lens.snapshot import SnapshotResolver, SnapshotStaleError  # noqa: E402
from aeh_change_lens.cli import main as cli_main  # noqa: E402
from tests.contract.test_contracts import validate  # noqa: E402


def git(root: Path, *arguments: str) -> None:
    subprocess.run(
        ["git", "-C", os.fspath(root), *arguments],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


class WorkerInputAssemblerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()
        (self.root / "Assets/Game").mkdir(parents=True)
        (self.root / "ProjectSettings").mkdir()
        (self.root / "Managed").mkdir()
        (self.root / "Assets/Game/Game.asmdef").write_text(
            '{"name":"Game"}\n', encoding="utf-8"
        )
        self.source = self.root / "Assets/Game/Entry.cs"
        self.source.write_text("class Entry {}\n", encoding="utf-8")
        (self.root / "ProjectSettings/ProjectVersion.txt").write_text(
            "m_EditorVersion: 2022.3.62f1\n", encoding="utf-8"
        )
        reference = self.root / "Managed/UnityEngine.CoreModule.dll"
        reference.write_bytes(b"fixture reference")
        (self.root / "Game.csproj").write_text(f"""<Project>
  <PropertyGroup><DefineConstants>UNITY_EDITOR</DefineConstants></PropertyGroup>
  <ItemGroup>
    <Reference Include="UnityEngine.CoreModule"><HintPath>{reference}</HintPath></Reference>
    <Compile Include="Assets/Game/**/*.cs" />
  </ItemGroup>
</Project>
""", encoding="utf-8")
        git(self.root, "init", "--initial-branch=main")
        git(self.root, "config", "user.name", "Change Lens Tests")
        git(self.root, "config", "user.email", "change-lens@example.invalid")
        git(self.root, "add", ".")
        git(self.root, "commit", "-m", "fixture")
        self.resolver = SnapshotResolver(self.root)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_assembles_only_snapshot_bound_source_bytes(self) -> None:
        binding = self.resolver.resolve_worktree("NEW")
        context = UnityContextBuilder(self.root).build("Game")

        payload = WorkerInputAssembler(self.resolver, self.root).assemble(
            binding, context, "FIXTURE-NEW"
        ).to_dict()

        validate("analyzer-worker-input.schema.json", payload)
        self.assertEqual("Assets/Game/Entry.cs", payload["source_files"][0]["path"])
        expected = hashlib.sha256(self.source.read_bytes()).hexdigest()
        self.assertEqual(expected, payload["source_files"][0]["content_hash"])
        self.assertEqual(expected, payload["source_files"][0]["snapshot_content_hash"])
        self.assertEqual("UTF-8", payload["source_files"][0]["source_encoding"])
        self.assertEqual({"UNITY"}, {
            item["kind"] for item in payload["unity_context"]["references"]
        })

    def test_source_mutation_after_binding_fails_closed(self) -> None:
        binding = self.resolver.resolve_worktree("NEW")
        context = UnityContextBuilder(self.root).build("Game")
        self.source.write_text("class Entry { int Changed; }\n", encoding="utf-8")

        with self.assertRaises(SnapshotStaleError):
            WorkerInputAssembler(self.resolver, self.root).assemble(binding, context, "STALE")

    def test_generated_project_mutation_after_context_binding_fails_closed(self) -> None:
        binding = self.resolver.resolve_worktree("NEW")
        context = UnityContextBuilder(self.root).build("Game")
        project = self.root / "Game.csproj"
        project.write_text(
            project.read_text(encoding="utf-8").replace("UNITY_EDITOR", "UNITY_STANDALONE"),
            encoding="utf-8",
        )

        with self.assertRaisesRegex(SnapshotStaleError, "compilation context changed"):
            WorkerInputAssembler(self.resolver, self.root).assemble(binding, context, "STALE-CONTEXT")

    def test_gb18030_source_preserves_raw_snapshot_digest(self) -> None:
        legacy = "class Entry { string Text = \"中文\"; }\n"
        self.source.write_bytes(legacy.encode("gb18030"))
        binding = self.resolver.resolve_worktree("NEW")
        context = UnityContextBuilder(self.root).build("Game")

        payload = WorkerInputAssembler(self.resolver, self.root).assemble(
            binding, context, "LEGACY-ENCODING"
        ).to_dict()
        source = payload["source_files"][0]

        self.assertEqual("GB18030", source["source_encoding"])
        self.assertEqual(legacy, source["content"])
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).hexdigest(), source["snapshot_content_hash"])
        self.assertEqual(hashlib.sha256(legacy.encode("utf-8")).hexdigest(), source["content_hash"])
        validate("analyzer-worker-input.schema.json", payload)

    def test_cli_emits_snapshot_bound_worker_input(self) -> None:
        output = StringIO()
        with redirect_stdout(output):
            exit_code = cli_main([
                "roslyn-input", os.fspath(self.root), os.fspath(self.root),
                "--assembly", "Game", "--request-id", "CLI-FIXTURE",
            ])
        self.assertEqual(0, exit_code)
        payload = json.loads(output.getvalue())
        self.assertEqual("CLI-FIXTURE", payload["request_id"])
        validate("analyzer-worker-input.schema.json", payload)


@unittest.skipUnless(os.environ.get("CHANGE_LENS_UNITY_PROJECT"), "real Unity pilot not configured")
class RealUnityWorkerInputPilotTests(unittest.TestCase):
    def test_et6_source_snapshot_assembles_without_target_writes(self) -> None:
        unity_root = Path(os.environ["CHANGE_LENS_UNITY_PROJECT"]).resolve()
        repository = Path(os.environ.get("CHANGE_LENS_REPOSITORY", unity_root.parent)).resolve()
        assembly = os.environ.get("CHANGE_LENS_UNITY_ASSEMBLY", "Unity.Model")
        status_before = subprocess.check_output([
            "git", "-C", os.fspath(repository), "status", "--porcelain=v1",
            "--untracked-files=all",
        ])

        resolver = SnapshotResolver(repository)
        binding = resolver.resolve_worktree("NEW")
        builder = UnityContextBuilder(unity_root)
        context = builder.build(assembly)
        graph = builder.build_graph(assembly)
        payload = WorkerInputAssembler(resolver, unity_root).assemble(
            binding, context, "REAL-UNITY-SNAPSHOT"
        ).to_dict()

        status_after = subprocess.check_output([
            "git", "-C", os.fspath(repository), "status", "--porcelain=v1",
            "--untracked-files=all",
        ])
        self.assertEqual(status_before, status_after)
        self.assertEqual(len(context.source_files), len(payload["source_files"]))
        self.assertEqual("PARTIAL", graph.completeness)
        self.assertTrue(any(
            item["source_encoding"] == "GB18030" for item in payload["source_files"]
        ))
        validate("analyzer-worker-input.schema.json", payload)


if __name__ == "__main__":
    unittest.main()
