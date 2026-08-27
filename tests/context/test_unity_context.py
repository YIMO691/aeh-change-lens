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
        self.assertEqual("Game.csproj", first.generated_project.path)
        self.assertEqual(64, len(first.generated_project.sha256))
        self.assertEqual("Assets/Game/Game.asmdef", first.assembly.path)
        self.assertEqual("APPLICABLE", first.applicability.status)
        self.assertEqual(("Editor",), first.applicability.active_platforms)
        self.assertTrue(first.applicability.define_constraints[0].satisfied)
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

    def test_generated_project_byte_change_changes_context_digest(self) -> None:
        before = UnityContextBuilder(self.root).build("Game")
        project = self.root / "Game.csproj"
        project.write_text(
            project.read_text(encoding="utf-8") + "\n<!-- bound change -->\n",
            encoding="utf-8",
        )
        after = UnityContextBuilder(self.root).build("Game")
        self.assertNotEqual(before.context_digest, after.context_digest)
        self.assertNotEqual(
            before.generated_project.sha256, after.generated_project.sha256
        )

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

    def test_define_constraint_or_and_negation_are_evaluated(self) -> None:
        asmdef = self.root / "Assets/Game/Game.asmdef"
        value = json.loads(asmdef.read_text(encoding="utf-8"))
        value["defineConstraints"] = [
            "MISSING || FEATURE_X",
            "!ENABLE_IL2CPP",
        ]
        asmdef.write_text(json.dumps(value), encoding="utf-8")

        context = UnityContextBuilder(self.root).build("Game")

        self.assertEqual("APPLICABLE", context.applicability.status)
        self.assertEqual((True, True), tuple(
            item.satisfied for item in context.applicability.define_constraints
        ))

    def test_excluded_define_constraint_is_explicit(self) -> None:
        asmdef = self.root / "Assets/Game/Game.asmdef"
        value = json.loads(asmdef.read_text(encoding="utf-8"))
        value["defineConstraints"] = ["REQUIRES_MISSING_DEFINE"]
        asmdef.write_text(json.dumps(value), encoding="utf-8")

        context = UnityContextBuilder(self.root).build("Game")

        self.assertEqual("EXCLUDED", context.applicability.status)
        self.assertEqual("PARTIAL", context.completeness)
        self.assertTrue(any("不兼容" in item for item in context.limitations))
        validate("unity-context.schema.json", context.to_dict())

    def test_platform_include_mismatch_is_explicit(self) -> None:
        asmdef = self.root / "Assets/Game/Game.asmdef"
        value = json.loads(asmdef.read_text(encoding="utf-8"))
        value["includePlatforms"] = ["Android"]
        asmdef.write_text(json.dumps(value), encoding="utf-8")

        context = UnityContextBuilder(self.root).build("Game")

        self.assertEqual(("Editor",), context.applicability.active_platforms)
        self.assertEqual("EXCLUDED", context.applicability.platform_status)
        self.assertEqual("EXCLUDED", context.applicability.status)

    def test_invalid_define_constraint_is_serialized_as_unknown(self) -> None:
        asmdef = self.root / "Assets/Game/Game.asmdef"
        value = json.loads(asmdef.read_text(encoding="utf-8"))
        value["defineConstraints"] = ["FEATURE_X ||"]
        asmdef.write_text(json.dumps(value), encoding="utf-8")

        context = UnityContextBuilder(self.root).build("Game")

        evaluation = context.applicability.define_constraints[0]
        self.assertFalse(evaluation.valid)
        self.assertIsNone(evaluation.satisfied)
        self.assertEqual("UNKNOWN", context.applicability.status)
        validate("unity-context.schema.json", context.to_dict())

    def test_version_defines_use_bound_package_and_unity_versions(self) -> None:
        packages = self.root / "Packages"
        packages.mkdir()
        (packages / "packages-lock.json").write_text(json.dumps({
            "dependencies": {
                "com.example.feature": {
                    "version": "1.5.0-preview.2",
                    "source": "registry",
                }
            }
        }), encoding="utf-8")
        asmdef = self.root / "Assets/Game/Game.asmdef"
        value = json.loads(asmdef.read_text(encoding="utf-8"))
        value["versionDefines"] = [
            {"name": "com.example.feature", "expression": "[1.4,2.0)", "define": "HAS_FEATURE"},
            {"name": "Unity", "expression": "[2022.3,2023)", "define": "SUPPORTED_UNITY"},
            {"name": "com.missing", "expression": "1.0", "define": "MISSING_PACKAGE"},
        ]
        value["defineConstraints"] = ["HAS_FEATURE", "SUPPORTED_UNITY"]
        asmdef.write_text(json.dumps(value), encoding="utf-8")

        context = UnityContextBuilder(self.root).build("Game")

        evaluations = {item.define: item for item in context.applicability.version_defines}
        self.assertEqual("DEFINED", evaluations["HAS_FEATURE"].status)
        self.assertEqual("DEFINED", evaluations["SUPPORTED_UNITY"].status)
        self.assertEqual("NOT_DEFINED", evaluations["MISSING_PACKAGE"].status)
        self.assertTrue({"HAS_FEATURE", "SUPPORTED_UNITY"}.issubset(context.defines))
        self.assertEqual("APPLICABLE", context.applicability.status)
        self.assertEqual("Packages/packages-lock.json", context.package_manifest.path)
        validate("unity-context.schema.json", context.to_dict())

    def test_unparseable_version_define_is_partial_not_guessed(self) -> None:
        packages = self.root / "Packages"
        packages.mkdir()
        (packages / "packages-lock.json").write_text(json.dumps({
            "dependencies": {
                "com.example.git": {
                    "version": "https://example.invalid/repo.git#v1.2.3",
                    "source": "git",
                }
            }
        }), encoding="utf-8")
        asmdef = self.root / "Assets/Game/Game.asmdef"
        value = json.loads(asmdef.read_text(encoding="utf-8"))
        value["versionDefines"] = [{
            "name": "com.example.git", "expression": "1.2", "define": "GIT_FEATURE"
        }]
        asmdef.write_text(json.dumps(value), encoding="utf-8")

        context = UnityContextBuilder(self.root).build("Game")

        self.assertEqual("UNKNOWN", context.applicability.version_defines[0].status)
        self.assertNotIn("GIT_FEATURE", context.defines)
        self.assertTrue(any("Version Define" in item for item in context.limitations))

    def test_missing_unity_version_define_is_unknown(self) -> None:
        (self.root / "ProjectSettings/ProjectVersion.txt").unlink()
        asmdef = self.root / "Assets/Game/Game.asmdef"
        value = json.loads(asmdef.read_text(encoding="utf-8"))
        value["versionDefines"] = [{
            "name": "Unity", "expression": "2022.3", "define": "SUPPORTED_UNITY"
        }]
        asmdef.write_text(json.dumps(value), encoding="utf-8")

        context = UnityContextBuilder(self.root).build("Game")

        self.assertEqual("UNKNOWN", context.applicability.version_defines[0].status)
        self.assertNotIn("SUPPORTED_UNITY", context.defines)
        self.assertEqual("PARTIAL", context.completeness)

    def test_version_define_expression_boundaries_are_explicit(self) -> None:
        packages = self.root / "Packages"
        packages.mkdir()
        (packages / "packages-lock.json").write_text(json.dumps({
            "dependencies": {
                "com.example.feature": {
                    "version": "1.5.0-preview.2",
                    "source": "registry",
                }
            }
        }), encoding="utf-8")
        asmdef = self.root / "Assets/Game/Game.asmdef"
        value = json.loads(asmdef.read_text(encoding="utf-8"))
        value["versionDefines"] = [
            {"name": "com.example.feature", "expression": "[1.5.0-preview.2]", "define": "EXACT"},
            {"name": "com.example.feature", "expression": "(1.5.0-preview.2,2.0)", "define": "LOWER_EXCLUSIVE"},
            {"name": "com.example.feature", "expression": "1.5.0-preview.1", "define": "MINIMUM"},
            {"name": "com.example.feature", "expression": "1.5.*", "define": "WILDCARD"},
            {"name": "com.example.feature", "expression": "[1.0, 2.0)", "define": "WHITESPACE"},
        ]
        asmdef.write_text(json.dumps(value), encoding="utf-8")

        context = UnityContextBuilder(self.root).build("Game")

        statuses = {
            item.define: item.status for item in context.applicability.version_defines
        }
        self.assertEqual("DEFINED", statuses["EXACT"])
        self.assertEqual("NOT_DEFINED", statuses["LOWER_EXCLUSIVE"])
        self.assertEqual("DEFINED", statuses["MINIMUM"])
        self.assertEqual("INVALID", statuses["WILDCARD"])
        self.assertEqual("INVALID", statuses["WHITESPACE"])
        self.assertTrue({"EXACT", "MINIMUM"}.issubset(context.defines))
        self.assertFalse({"LOWER_EXCLUSIVE", "WILDCARD", "WHITESPACE"} & set(context.defines))
        self.assertEqual("PARTIAL", context.completeness)
        validate("unity-context.schema.json", context.to_dict())

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
        self.assertEqual("APPLICABLE", context.applicability.status)
        self.assertTrue(any(
            Path(item.path).name.casefold() == "unityengine.coremodule.dll"
            for item in context.metadata_references
        ))
        self.assertEqual(64, len(context.context_digest))


if __name__ == "__main__":
    unittest.main()
