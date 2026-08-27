from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from aeh_change_lens.languages.csharp import UnityContextBuilder  # noqa: E402
from tests.contract.test_contracts import validate  # noqa: E402


class UnityContextBuilderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()
        (self.root / "Assets/Game").mkdir(parents=True)
        (self.root / "ProjectSettings").mkdir()
        (self.root / "Managed").mkdir()
        (self.root / "ProjectSettings/ProjectVersion.txt").write_text(
            "m_EditorVersion: 2022.3.62f1\n", encoding="utf-8"
        )
        (self.root / "Assets/Game/Game.asmdef").write_text(json.dumps({
            "name": "Game",
            "rootNamespace": "Fixture",
            "references": ["Dependency"],
            "includePlatforms": ["Editor"],
            "excludePlatforms": [],
            "defineConstraints": ["FEATURE_X"],
            "noEngineReferences": False,
        }), encoding="utf-8")
        (self.root / "Assets/Game/Entry.cs").write_text("class Entry {}\n", encoding="utf-8")
        (self.root / "Managed/UnityEngine.CoreModule.dll").write_bytes(b"fixture metadata bytes")
        (self.root / "Dependency.csproj").write_text("<Project />\n", encoding="utf-8")
        hint = self.root / "Managed/UnityEngine.CoreModule.dll"
        (self.root / "Game.csproj").write_text(f"""<Project>
  <PropertyGroup><DefineConstants>UNITY_EDITOR;FEATURE_X</DefineConstants></PropertyGroup>
  <ItemGroup>
    <Reference Include="UnityEngine.CoreModule"><HintPath>{hint}</HintPath></Reference>
    <ProjectReference Include="Dependency.csproj" />
    <Compile Include="Assets/Game/**/*.cs" />
  </ItemGroup>
</Project>
""", encoding="utf-8")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_builds_deterministic_digest_bound_partial_context(self) -> None:
        first = UnityContextBuilder(self.root).build("Game")
        second = UnityContextBuilder(self.root).build("Game")
        self.assertEqual(first, second)
        self.assertEqual("PARTIAL", first.completeness)
        self.assertEqual("2022.3.62f1", first.unity_version)
        self.assertEqual(("FEATURE_X", "UNITY_EDITOR"), first.defines)
        self.assertEqual("Game", first.assembly.name)
        self.assertEqual("Assets/Game/Game.asmdef", first.assembly.path)
        self.assertEqual(1, len(first.metadata_references))
        self.assertEqual("UNITY", first.metadata_references[0].kind)
        self.assertEqual(64, len(first.metadata_references[0].sha256))
        self.assertTrue(any("ProjectReference" in item for item in first.limitations))
        self.assertEqual(("Assets/Game/Entry.cs",), first.source_files)
        validate("unity-context.schema.json", first.to_dict())

    def test_reference_byte_change_changes_context_digest(self) -> None:
        before = UnityContextBuilder(self.root).build("Game")
        (self.root / "Managed/UnityEngine.CoreModule.dll").write_bytes(b"mutated metadata bytes")
        after = UnityContextBuilder(self.root).build("Game")
        self.assertNotEqual(before.context_digest, after.context_digest)
        self.assertNotEqual(before.metadata_references[0].sha256, after.metadata_references[0].sha256)

    def test_duplicate_assembly_name_fails_closed(self) -> None:
        duplicate = self.root / "Assets/Other/Game.asmdef"
        duplicate.parent.mkdir()
        duplicate.write_text('{"name":"Game"}\n', encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "duplicate asmdef"):
            UnityContextBuilder(self.root).build("Game")

    def test_active_project_reference_outside_unity_root_is_not_followed(self) -> None:
        project = self.root / "Game.csproj"
        project.write_text(
            project.read_text(encoding="utf-8").replace(
                "Dependency.csproj", "../Outside.csproj"
            ),
            encoding="utf-8",
        )
        graph = UnityContextBuilder(self.root).build_graph("Game")
        self.assertEqual("OUTSIDE_UNITY_ROOT", graph.dependencies[0].status)
        self.assertEqual(1, len(graph.assemblies))
        self.assertEqual("PARTIAL", graph.completeness)

    def test_build_graph_follows_project_reference_without_trusting_output(self) -> None:
        (self.root / "Assets/Dependency").mkdir()
        (self.root / "Assets/Dependency/Dependency.asmdef").write_text(
            '{"name":"Dependency"}\n', encoding="utf-8"
        )
        (self.root / "Assets/Dependency/Dependency.cs").write_text(
            "class Dependency {}\n", encoding="utf-8"
        )
        hint = self.root / "Managed/UnityEngine.CoreModule.dll"
        (self.root / "Dependency.csproj").write_text(f"""<Project>
  <PropertyGroup><DefineConstants>UNITY_EDITOR</DefineConstants></PropertyGroup>
  <ItemGroup>
    <Reference Include="UnityEngine.CoreModule"><HintPath>{hint}</HintPath></Reference>
    <Compile Include="Assets/Dependency/**/*.cs" />
  </ItemGroup>
</Project>
""", encoding="utf-8")
        game_project = (self.root / "Game.csproj").read_text(encoding="utf-8")
        (self.root / "Game.csproj").write_text(
            game_project.replace(
                '<ProjectReference Include="Dependency.csproj" />',
                '<ProjectReference Include="Dependency.csproj"><Name>Dependency</Name></ProjectReference>',
            ),
            encoding="utf-8",
        )
        output = self.root / "Library/ScriptAssemblies/Dependency.dll"
        output.parent.mkdir(parents=True)
        output.write_bytes(b"unverified generated output")

        graph = UnityContextBuilder(self.root).build_graph("Game")

        self.assertEqual({"Game", "Dependency"}, {
            item.assembly.name for item in graph.assemblies if item.assembly
        })
        self.assertEqual(1, len(graph.dependencies))
        self.assertEqual("BOUND_UNVERIFIED", graph.dependencies[0].status)
        game = next(item for item in graph.assemblies if item.assembly.name == "Game")
        self.assertEqual("PROJECT_UNVERIFIED", game.project_references[0].script_assembly.kind)
        self.assertEqual("PARTIAL", graph.completeness)
        validate("unity-assembly-graph.schema.json", graph.to_dict())


@unittest.skipUnless(os.environ.get("CHANGE_LENS_UNITY_PROJECT"), "real Unity pilot not configured")
class RealUnityReadOnlyPilotTests(unittest.TestCase):
    def test_generated_context_binds_real_unity_metadata(self) -> None:
        unity_root = Path(os.environ["CHANGE_LENS_UNITY_PROJECT"])
        assembly = os.environ.get("CHANGE_LENS_UNITY_ASSEMBLY", "Unity.Model")
        before = (unity_root / "ProjectSettings/ProjectVersion.txt").read_bytes()
        context = UnityContextBuilder(unity_root).build(assembly)
        after = (unity_root / "ProjectSettings/ProjectVersion.txt").read_bytes()
        self.assertEqual(before, after)
        self.assertIsNotNone(context.assembly)
        self.assertTrue(context.unity_version)
        self.assertTrue(any(
            Path(item.path).name.casefold() == "unityengine.coremodule.dll"
            for item in context.metadata_references
        ))
        self.assertEqual(64, len(context.context_digest))


if __name__ == "__main__":
    unittest.main()
