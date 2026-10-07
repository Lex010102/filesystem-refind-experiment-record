import shutil
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from fs_memory_lab.evidence import (
    EvidenceValidationError,
    SourceCatalog,
    StoreSnapshotRef,
    VerifiedStoreManifest,
)
from fs_memory_lab.r1_tools import (
    FROZEN_R1_FILESYSTEM_TOOL_PROFILE_SHA256,
    FROZEN_R1_FILESYSTEM_TOOL_SCHEMA_SHA256,
    FROZEN_R1_FILESYSTEM_TOOL_WIRE_SHA256,
    FROZEN_R1_PROJECT_DEFAULTS_SHA256,
    FROZEN_R1_PROJECT_LIMITS_SHA256,
    LineCoverage,
    R1_FILESYSTEM_PROTOCOL_VERSION,
    R1_FILESYSTEM_TOOL_NAMES,
    R1_PROJECT_DEFAULTS,
    R1ReadOnlyFilesystem,
    R1ToolError,
    _regex_deadline,
    r1_filesystem_tool_profile_sha256,
    r1_filesystem_tool_schema_sha256,
    r1_filesystem_tool_schemas,
    r1_filesystem_tool_wire_sha256,
    r1_project_defaults_sha256,
    r1_project_limits_sha256,
    verify_r1_filesystem_tool_freeze,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_MAP = REPO_ROOT / "data" / "manifests" / "source_map.json"
RECORDS = REPO_ROOT / "data" / "processed" / "conv-50.jsonl"
EXPERIMENT = REPO_ROOT / "experiments" / "locomo-conv50-v1"
SOURCE_MAP_SHA256 = "6e99115961bae06a48bfb7e82dbdcc18dc32ccf6c5ce57e3c266dfc7a5d4d574"
RECORDS_SHA256 = "130a5a1e1b75083358ef27a98dd215a4e75c819ace6f2ee9b560ba394e0f0394"
S1_MANIFEST_SHA256 = "5c5900c333c8f85463f038448560cb4357f1161d6ed43e9fbc86809ba7916d3c"
S2_MANIFEST_SHA256 = "4858e430f3c197d4f718ea5839596597c3dbbd885e3d1fc654e982a90dc707ac"
S2_MARKER_SHA256 = "af329bf6749b5909d809d81f52e41079d898a18d86c8bb2d80db0170fbb8b6a9"


class R1ToolSchemaTest(unittest.TestCase):
    def test_exact_order_names_required_fields_and_frozen_hash(self):
        schemas = r1_filesystem_tool_schemas()
        self.assertEqual(R1_FILESYSTEM_PROTOCOL_VERSION, "center-table12-readonly-v1")
        self.assertEqual(
            tuple(schema["function"]["name"] for schema in schemas),
            R1_FILESYSTEM_TOOL_NAMES,
        )
        self.assertEqual(
            r1_filesystem_tool_schema_sha256(),
            FROZEN_R1_FILESYSTEM_TOOL_SCHEMA_SHA256,
        )
        self.assertEqual(
            r1_filesystem_tool_profile_sha256(),
            FROZEN_R1_FILESYSTEM_TOOL_PROFILE_SHA256,
        )
        self.assertEqual(
            r1_filesystem_tool_wire_sha256(),
            FROZEN_R1_FILESYSTEM_TOOL_WIRE_SHA256,
        )
        self.assertEqual(
            r1_project_defaults_sha256(), FROZEN_R1_PROJECT_DEFAULTS_SHA256
        )
        self.assertEqual(r1_project_limits_sha256(), FROZEN_R1_PROJECT_LIMITS_SHA256)
        verify_r1_filesystem_tool_freeze()
        required = {
            "view": ["path"],
            "grep": ["pattern"],
            "toc": ["path"],
            "section_read": ["path", "section_path"],
        }
        for schema in schemas:
            function = schema["function"]
            parameters = function["parameters"]
            self.assertFalse(parameters["additionalProperties"])
            self.assertEqual(parameters["required"], required[function["name"]])

    def test_schema_return_is_detached_and_mutation_is_detected(self):
        first = r1_filesystem_tool_schemas()
        first[0]["function"]["description"] = "caller mutation"
        self.assertNotEqual(
            first[0]["function"]["description"],
            r1_filesystem_tool_schemas()[0]["function"]["description"],
        )
        with patch.dict(
            "fs_memory_lab.r1_tools.TOOL_DEFINITIONS",
            {"view": {"type": "function"}},
            clear=True,
        ):
            with self.assertRaises(EvidenceValidationError):
                r1_filesystem_tool_schemas()

    def test_project_defaults_are_separate_from_paper_schema(self):
        schemas = r1_filesystem_tool_schemas()
        self.assertEqual(R1_PROJECT_DEFAULTS["view"], {"start_line": 1, "end_line": -1})
        self.assertEqual(
            R1_PROJECT_DEFAULTS["grep"],
            {"path": "/memories", "case_sensitive": False, "max_results": 100},
        )
        for schema in schemas:
            for field in schema["function"]["parameters"]["properties"].values():
                self.assertNotIn("default", field)


class R1ReadOnlyFilesystemTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = SourceCatalog.load(
            SOURCE_MAP,
            RECORDS,
            expected_source_map_sha256=SOURCE_MAP_SHA256,
            expected_records_sha256=RECORDS_SHA256,
            expected_conversation_id="conv-50",
        )

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(dir="/private/tmp")
        self.temp_root = Path(self.temporary.name)
        self.store = self.temp_root / "s1-flat"
        shutil.copytree(EXPERIMENT / "stores" / "s1-flat", self.store)
        self.manifest = VerifiedStoreManifest.load(
            root=self.store,
            store_id="s1",
            catalog=self.catalog,
            manifest_path=EXPERIMENT / "manifests" / "s1-flat.json",
            expected_manifest_sha256=S1_MANIFEST_SHA256,
        )
        self.snapshot = StoreSnapshotRef.capture(
            root=self.store,
            catalog=self.catalog,
            verified_manifest=self.manifest,
        )
        self.filesystem = R1ReadOnlyFilesystem(
            root=self.store,
            catalog=self.catalog,
            verified_manifest=self.manifest,
            snapshot=self.snapshot,
        )

    def tearDown(self):
        self.temporary.cleanup()

    def test_view_file_and_root_have_exact_coverage_semantics(self):
        root = self.filesystem.execute("view", {"path": "/memories"})
        self.assertTrue(root.root_survey)
        self.assertFalse(root.whole_tree_grep)
        self.assertEqual(root.coverage, ())
        self.assertEqual(root.result_count, 30)
        self.assertIn("/memories/session-01.md", root.content)
        self.assertIn("[description: Session 1 on", root.content)

        viewed = self.filesystem.execute(
            "view",
            {"path": "/memories/session-01.md", "start_line": 52, "end_line": 53},
        )
        self.assertEqual(
            viewed.canonical_args,
            {"path": "/memories/session-01.md", "start_line": 52, "end_line": 53},
        )
        self.assertEqual(
            viewed.coverage,
            (LineCoverage("/memories/session-01.md", 52, 53),),
        )
        self.assertIn("L53: [S1T13] (dia_id: D1:13)", viewed.content)

    def test_grep_is_stable_bounded_and_marks_only_returned_lines(self):
        result = self.filesystem.execute(
            "grep", {"pattern": "D1:13", "case_sensitive": True}
        )
        self.assertTrue(result.whole_tree_grep)
        self.assertFalse(result.truncated)
        self.assertEqual(result.result_count, 1)
        self.assertEqual(
            result.coverage,
            (LineCoverage("/memories/session-01.md", 53, 53),),
        )
        self.assertEqual(
            result,
            self.filesystem.execute(
                "grep", {"pattern": "D1:13", "case_sensitive": True}
            ),
        )

        limited = self.filesystem.execute("grep", {"pattern": ".", "max_results": 1})
        self.assertTrue(limited.truncated)
        self.assertFalse(limited.whole_tree_grep)
        self.assertEqual(limited.result_count, 1)
        self.assertEqual(len(limited.coverage), 1)
        self.assertTrue(limited.content.endswith("(max_results reached)"))

        absent = self.filesystem.execute("grep", {"pattern": "not-present-xyz"})
        self.assertEqual(absent.content, "(no matches)")
        self.assertTrue(absent.whole_tree_grep)
        self.assertEqual(absent.coverage, ())

    def test_toc_routes_only_and_section_read_exposes_exact_lines(self):
        toc = self.filesystem.execute(
            "toc", {"path": "/memories/session-01.md"}
        )
        self.assertEqual(toc.coverage, ())
        self.assertEqual(toc.content, "L6-72: # Session 1")
        section = self.filesystem.execute(
            "section_read",
            {"path": "/memories/session-01.md", "section_path": "# Session 1"},
        )
        self.assertEqual(
            section.coverage,
            (LineCoverage("/memories/session-01.md", 6, 72),),
        )
        self.assertTrue(section.content.startswith("L6: # Session 1"))
        self.assertIn("L72: [S1T19]", section.content)

    def test_headings_ignore_frontmatter_and_fenced_code(self):
        lines = [
            "---",
            "description: # not a heading",
            "---",
            "# Root",
            "```md",
            "## Not real",
            "```",
            "## Child",
            "### Grandchild",
            "# Next",
        ]
        headings = R1ReadOnlyFilesystem._headings(lines)
        self.assertEqual(
            [(line, level, label) for line, level, label, _path in headings],
            [
                (4, 1, "# Root"),
                (8, 2, "## Child"),
                (9, 3, "### Grandchild"),
                (10, 1, "# Next"),
            ],
        )
        self.assertEqual(headings[2][3], ("# Root", "## Child", "### Grandchild"))

    def test_arguments_and_paths_fail_closed(self):
        bad_calls = [
            ("view", {}),
            ("view", {"path": "/memories", "extra": 1}),
            ("view", {"path": "/memories/session-01.md", "start_line": True}),
            ("view", {"path": "/memories/session-01.md", "start_line": 9999}),
            ("view", {"path": "/memories//session-01.md"}),
            ("view", {"path": "/memories/../outside.md"}),
            ("grep", {"pattern": "x", "case_sensitive": "false"}),
            ("grep", {"pattern": "x", "max_results": 1001}),
            ("grep", {"pattern": "("}),
            ("toc", {"path": "/memories"}),
            (
                "section_read",
                {"path": "/memories/session-01.md", "section_path": "Session 1"},
            ),
            ("create", {"path": "/memories/new.md"}),
        ]
        for name, args in bad_calls:
            with self.subTest(name=name, args=args):
                with self.assertRaises(R1ToolError):
                    self.filesystem.execute(name, args)
        with self.assertRaises(R1ToolError):
            self.filesystem.execute(
                "view", {"path": "/memories", "start_line": 1}
            )

    def test_unpaired_unicode_surrogates_fail_as_stable_tool_errors(self):
        calls = [
            ("view", {"path": "/memories/\ud800.md"}),
            ("grep", {"pattern": "\ud800"}),
            (
                "section_read",
                {
                    "path": "/memories/session-01.md",
                    "section_path": "# \ud800",
                },
            ),
        ]
        for name, arguments in calls:
            with self.subTest(name=name):
                with self.assertRaises(R1ToolError) as raised:
                    self.filesystem.execute(name, arguments)
                self.assertEqual(raised.exception.code, "invalid_arguments")

    def test_missing_root_is_not_created_and_store_drift_is_fatal(self):
        missing = self.temp_root / "missing"
        with self.assertRaises(EvidenceValidationError):
            R1ReadOnlyFilesystem(
                root=missing,
                catalog=self.catalog,
                verified_manifest=self.manifest,
                snapshot=self.snapshot,
            )
        self.assertFalse(missing.exists())

        (self.store / "unauthorized-empty-directory").mkdir()
        with self.assertRaises(EvidenceValidationError):
            self.filesystem.execute("view", {"path": "/memories"})

    def test_mid_call_drift_is_detected_and_no_result_is_emitted(self):
        original = self.filesystem._read_verified_text
        changed = False

        def mutate_after_read(relative):
            nonlocal changed
            text = original(relative)
            if not changed:
                changed = True
                (self.store / "mid-call-empty-directory").mkdir()
            return text

        with patch.object(
            self.filesystem, "_read_verified_text", side_effect=mutate_after_read
        ):
            with self.assertRaises(EvidenceValidationError):
                self.filesystem.execute(
                    "view", {"path": "/memories/session-01.md"}
                )

    def test_recovery_style_mid_read_replacement_cannot_emit_content(self):
        relative = "session-01.md"
        target = self.store / relative
        original_payload = target.read_bytes()
        primitive = self.filesystem._read_file_bytes_no_follow

        def read_temporary_tamper(requested):
            self.assertEqual(requested, relative)
            target.write_bytes(b"---\ndescription: malicious\n---\n\n# Injected\n")
            try:
                malicious_payload = primitive(requested)
            finally:
                target.write_bytes(original_payload)
            return malicious_payload

        with patch.object(
            self.filesystem,
            "_read_file_bytes_no_follow",
            side_effect=read_temporary_tamper,
        ):
            with self.assertRaisesRegex(EvidenceValidationError, "Read payload differs"):
                self.filesystem.execute(
                    "view", {"path": "/memories/session-01.md"}
                )
        self.assertEqual(target.read_bytes(), original_payload)

    def test_regex_deadline_is_enforced_and_restored(self):
        with self.assertRaisesRegex(R1ToolError, "time limit") as raised:
            with _regex_deadline(10):
                while True:
                    pass
        self.assertEqual(raised.exception.code, "regex_timeout")

    def test_regex_compile_resource_failures_are_structured_and_postchecked(self):
        patterns = [
            "(" * 500,
            "a{" + "9" * 100 + "}",
        ]
        for pattern in patterns:
            with self.subTest(pattern=pattern[:20]):
                with patch.object(
                    self.filesystem,
                    "_validate_snapshot",
                    wraps=self.filesystem._validate_snapshot,
                ) as validate:
                    with self.assertRaises(R1ToolError) as raised:
                        self.filesystem.execute("grep", {"pattern": pattern})
                self.assertEqual(raised.exception.code, "invalid_regex")
                self.assertEqual(validate.call_count, 2)

    def test_s2_nested_store_uses_the_same_verified_executor(self):
        s2_root = self.temp_root / "s2-foldered"
        shutil.copytree(EXPERIMENT / "stores" / "s2-foldered", s2_root)
        manifest = VerifiedStoreManifest.load(
            root=s2_root,
            store_id="s2",
            catalog=self.catalog,
            manifest_path=EXPERIMENT / "manifests" / "s2-foldered.json",
            expected_manifest_sha256=S2_MANIFEST_SHA256,
            commit_marker_path=EXPERIMENT / "manifests" / "s2-foldered.COMMITTED",
            expected_commit_marker_sha256=S2_MARKER_SHA256,
            path_map_path=EXPERIMENT / "manifests" / "s2-foldered-path-map.json",
            trace_path=EXPERIMENT / "traces" / "s2-foldering.json",
        )
        snapshot = StoreSnapshotRef.capture(
            root=s2_root,
            catalog=self.catalog,
            verified_manifest=manifest,
        )
        filesystem = R1ReadOnlyFilesystem(
            root=s2_root,
            catalog=self.catalog,
            verified_manifest=manifest,
            snapshot=snapshot,
        )
        root = filesystem.execute("view", {"path": "/memories"})
        self.assertEqual(root.result_count, 34)
        self.assertIn("/memories/travel-and-outdoors/", root.content)
        self.assertIn(
            "/memories/travel-and-outdoors/session-01.md", root.content
        )
        match = filesystem.execute(
            "grep", {"pattern": "D1:13", "case_sensitive": True}
        )
        self.assertEqual(match.result_count, 1)
        self.assertEqual(
            match.coverage,
            (
                LineCoverage(
                    "/memories/travel-and-outdoors/session-01.md", 53, 53
                ),
            ),
        )

    def test_results_are_content_addressed_immutable_and_output_bounded(self):
        result = self.filesystem.execute("grep", {"pattern": "D1:13"})
        with self.assertRaisesRegex(EvidenceValidationError, "hash|identity"):
            replace(result, content=result.content + "tampered")
        with self.assertRaisesRegex(EvidenceValidationError, "coverage must be ordered"):
            replace(result, coverage={result.coverage[0]})
        with self.assertRaisesRegex(EvidenceValidationError, "tree drift"):
            replace(result, post_tree_sha256="0" * 64)
        with self.assertRaisesRegex(EvidenceValidationError, "root_survey"):
            replace(result, root_survey=True)
        tiny_limits = {
            "max_output_bytes": 10,
            "max_pattern_chars": 512,
            "max_results_limit": 1_000,
            "regex_timeout_millis": 1_000,
        }
        with patch("fs_memory_lab.r1_tools.R1_PROJECT_LIMITS", tiny_limits):
            with self.assertRaisesRegex(R1ToolError, "byte limit"):
                self.filesystem.execute("view", {"path": "/memories"})


if __name__ == "__main__":
    unittest.main()
