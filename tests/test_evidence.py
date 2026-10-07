import json
import math
import shutil
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from fs_memory_lab.evidence import (
    AttributionIndex,
    AttributionUnit,
    BudgetRecord,
    EvidenceBundle,
    EvidenceValidationError,
    GlobalFallbackProof,
    QuestionInput,
    RetrievalFailureArtifact,
    SourceCatalog,
    StopRecord,
    StoreSnapshotRef,
    TokenizerRef,
    VerifiedStoreManifest,
    build_evidence_item,
    canonical_json_bytes,
    sha256_bytes,
    validate_evidence_bundle,
    validate_evidence_item,
    validate_retrieval_failure_artifact,
    validate_r1_evidence_bundle_profile,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_MAP = REPO_ROOT / "data" / "manifests" / "source_map.json"
RECORDS = REPO_ROOT / "data" / "processed" / "conv-50.jsonl"
SOURCE_MAP_SHA256 = "6e99115961bae06a48bfb7e82dbdcc18dc32ccf6c5ce57e3c266dfc7a5d4d574"
RECORDS_SHA256 = "130a5a1e1b75083358ef27a98dd215a4e75c819ace6f2ee9b560ba394e0f0394"
EXPERIMENT = REPO_ROOT / "experiments" / "locomo-conv50-v1"
S1_MANIFEST_SHA256 = "5c5900c333c8f85463f038448560cb4357f1161d6ed43e9fbc86809ba7916d3c"
S2_MANIFEST_SHA256 = "4858e430f3c197d4f718ea5839596597c3dbbd885e3d1fc654e982a90dc707ac"
S2_MARKER_SHA256 = "af329bf6749b5909d809d81f52e41079d898a18d86c8bb2d80db0170fbb8b6a9"


class EvidenceSchemaTest(unittest.TestCase):
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
        # Use the canonical macOS temp prefix so path-safety checks do not see
        # the public /var -> /private/var compatibility symlink.
        self.temporary = tempfile.TemporaryDirectory(dir="/private/tmp")
        self.temp_root = Path(self.temporary.name)
        self.s1_root = self.temp_root / "s1-flat"
        shutil.copytree(EXPERIMENT / "stores" / "s1-flat", self.s1_root)
        self.s1_manifest = VerifiedStoreManifest.load(
            root=self.s1_root,
            store_id="s1",
            catalog=self.catalog,
            manifest_path=EXPERIMENT / "manifests" / "s1-flat.json",
            expected_manifest_sha256=S1_MANIFEST_SHA256,
        )
        self.s1_snapshot = StoreSnapshotRef.capture(
            root=self.s1_root,
            catalog=self.catalog,
            verified_manifest=self.s1_manifest,
        )
        self.s3_root = self.temp_root / "s3-curated"
        self.s3_root.mkdir()
        self.question = QuestionInput.from_mapping({
            "schema_version": 1,
            "question_set_id": "dev",
            "run_position": 1,
            "question_id": "conv-50-q001",
            "conversation_id": "conv-50",
            "question": "What happened?",
        })

    def tearDown(self):
        self.temporary.cleanup()

    @staticmethod
    def curated_memory() -> str:
        return (
            "---\nname: notes\ndescription: Curated fixture.\n---\n\n"
            "# Combined\n\n"
            "- Calvin planned to visit Japan [S1T13].\n"
            "- Dave later encouraged him [S2T2].\n"
        )

    def write_curated(self, text=None, name="notes.md") -> Path:
        path = self.s3_root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text or self.curated_memory(), encoding="utf-8")
        return path

    def make_s3_manifest(self, source_index=None):
        source_index = source_index or {
            "[S1T13]": [{"file": "notes.md", "line": 8}],
            "[S2T2]": [{"file": "notes.md", "line": 9}],
        }
        files = {}
        total_bytes = 0
        for path in sorted(self.s3_root.rglob("*.md")):
            relative = path.relative_to(self.s3_root).as_posix()
            payload = path.read_bytes()
            text = payload.decode("utf-8")
            locators = [
                locator
                for locator, occurrences in source_index.items()
                if any(item["file"] == relative for item in occurrences)
            ]
            files[relative] = {
                "bytes": len(payload),
                "cross_references": [],
                "headings": sum(line.startswith("#") for line in text.splitlines()),
                "lines": len(text.splitlines()),
                "locator_mentions": sum(text.count(locator) for locator in locators),
                "sha256": sha256_bytes(payload),
                "section_cross_references": [],
                "unique_locators": sorted(set(locators)),
            }
            total_bytes += len(payload)
        directories = sorted(
            path.relative_to(self.s3_root).as_posix()
            for path in self.s3_root.rglob("*")
            if path.is_dir()
        )
        store_sha = sha256_bytes(
            canonical_json_bytes({name: files[name]["sha256"] for name in sorted(files)})
        )
        run_id = "20261008T000000000000Z-12345678"
        finished_at = "2026-10-08T00:00:00Z"
        trace_dir = self.temp_root / "s3-management"
        trace_dir.mkdir(exist_ok=True)
        trace_file = trace_dir / "index.json"
        trace_file.write_text('{"status":"completed"}\n', encoding="utf-8")
        trace_tree_sha = sha256_bytes(
            canonical_json_bytes({"index.json": sha256_bytes(trace_file.read_bytes())})
        )
        manifest = {
            "schema_version": 1,
            "artifact_id": "locomo/conv-50/s3-curated/v1",
            "build": {
                "run_id": run_id,
                "mode": "formal",
                "finished_at": finished_at,
                "chunks_completed": 85,
            },
            "counts": {"files": len(files), "bytes": total_bytes},
            "directories": directories,
            "files": files,
            "source_index": source_index,
            "source": {
                "stream_manifest_sha256": "1" * 64,
                "prompt_contract_sha256": "2" * 64,
                "runtime_contract_sha256": "3" * 64,
            },
            "store": {"directory_name": "s3-curated", "tree_sha256": store_sha},
            "trace": {
                "directory_name": "s3-management",
                "tree_sha256": trace_tree_sha,
            },
            "verification": {
                "all_85_chunks_completed_in_order": True,
                "formal_outputs_published_from_staging": True,
            },
        }
        manifest_payload = (
            json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        ).encode("utf-8")
        manifest_path = self.temp_root / "s3-curated.json"
        manifest_path.write_bytes(manifest_payload)
        marker = {
            "schema_version": 1,
            "artifact_id": manifest["artifact_id"],
            "run_id": run_id,
            "committed_at": finished_at,
            "store_tree_sha256": store_sha,
            "trace_tree_sha256": trace_tree_sha,
            "manifest_sha256": sha256_bytes(manifest_payload),
            "stream_manifest_sha256": "1" * 64,
            "prompt_contract_sha256": "2" * 64,
            "runtime_contract_sha256": "3" * 64,
        }
        marker_payload = (
            json.dumps(marker, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        ).encode("utf-8")
        marker_path = self.temp_root / "s3-curated.COMMITTED"
        marker_path.write_bytes(marker_payload)
        verified = VerifiedStoreManifest.load(
            root=self.s3_root,
            store_id="s3",
            catalog=self.catalog,
            manifest_path=manifest_path,
            expected_manifest_sha256=sha256_bytes(manifest_payload),
            commit_marker_path=marker_path,
            expected_commit_marker_sha256=sha256_bytes(marker_payload),
            trace_path=trace_dir,
        )
        return verified, manifest_path, marker_path

    def raw_item(self, snapshot=None, verified=None, **overrides):
        verified = verified or self.s1_manifest
        span = verified.attribution_index.occurrences("[S1T13]")[0]
        values = {
            "root": self.s1_root,
            "catalog": self.catalog,
            "verified_manifest": verified,
            "snapshot": snapshot or self.s1_snapshot,
            "path": "/memories/" + span.path,
            "line_start": span.line_start,
            "line_end": span.line_end,
            "retrieval_round": 2,
            "observation_ids": ["obs-0001"],
            "selection_ordinal": 1,
            "query_terms": ["Japan", "trip"],
        }
        values.update(overrides)
        return build_evidence_item(**values)

    def curated_context(self, source_index=None):
        self.write_curated()
        verified, _, _ = self.make_s3_manifest(source_index)
        snapshot = StoreSnapshotRef.capture(
            root=self.s3_root,
            catalog=self.catalog,
            verified_manifest=verified,
        )
        return verified, snapshot

    def curated_item(self, verified, snapshot, **overrides):
        values = {
            "root": self.s3_root,
            "catalog": self.catalog,
            "verified_manifest": verified,
            "snapshot": snapshot,
            "path": "/memories/notes.md",
            "line_start": 8,
            "line_end": 9,
            "retrieval_round": 2,
            "observation_ids": ["obs-0001"],
            "selection_ordinal": 1,
            "query_terms": ["Japan", "trip"],
        }
        values.update(overrides)
        return build_evidence_item(**values)

    def bundle_kwargs(self, item, snapshot, retrieval_id="r1"):
        used = len(item.text.encode("utf-8"))
        return {
            "status": "completed",
            "question": self.question,
            "condition": {
                "condition_id": "E1",
                "store_id": snapshot.store_id,
                "retrieval_id": retrieval_id,
            },
            "store_snapshot": snapshot,
            "prompt_contract": {
                "paper_prompt_id": "prompt-7",
                "paper_prompt_sha256": "a" * 64,
                "derived_prompt_sha256": "b" * 64,
                "filesystem_tools_sha256": "c" * 64,
                "orchestration_actions_sha256": "d" * 64,
            },
            "runtime_contract": {
                "runtime_sha256": "e" * 64,
                "round_limit": 20,
                "evidence_budget_unit": "bytes",
                "evidence_budget_limit": 50_000,
            },
            "search_actions": [],
            "evidence_items": [item],
            "stop": StopRecord("evidence_sufficient", False, (), 0, None),
            "budget": BudgetRecord("bytes", None, 50_000, used, 0, False),
            "metrics": {
                "provider_rounds": 2,
                "model_calls": 2,
                "provider_request_attempts": 2,
                "filesystem_tool_calls": 1,
                "orchestration_calls": 2,
                "prompt_tokens": None,
                "completion_tokens": None,
                "total_tokens": None,
                "token_usage_available": False,
            },
            "model": {"requested_model": "coding", "served_models": ["qwen3.8:27b"]},
            "integrity": {
                "store_unchanged": True,
                "pre_tree_sha256": snapshot.tree_sha256,
                "post_tree_sha256": snapshot.tree_sha256,
                "verified": True,
            },
        }

    def test_question_input_exact_schema_and_direct_constructor(self):
        value = self.question.to_dict()
        value["answer"] = "secret"
        with self.assertRaisesRegex(EvidenceValidationError, "forbidden gold"):
            QuestionInput.from_mapping(value)
        value = self.question.to_dict()
        value["extra"] = "not frozen"
        with self.assertRaisesRegex(EvidenceValidationError, "keys must be exactly"):
            QuestionInput.from_mapping(value)

    def test_source_catalog_resolves_and_hash_checks(self):
        record = self.catalog.resolve("[S1T13]")
        self.assertEqual(record.dia_id, "D1:13")
        self.assertEqual(record.speaker, "Calvin")
        with self.assertRaisesRegex(EvidenceValidationError, "not in the frozen catalog"):
            self.catalog.resolve("[S99T1]")
        with self.assertRaisesRegex(EvidenceValidationError, "frozen hash"):
            SourceCatalog.load(
                SOURCE_MAP,
                RECORDS,
                expected_source_map_sha256="0" * 64,
                expected_records_sha256=RECORDS_SHA256,
                expected_conversation_id="conv-50",
            )

    def test_checked_in_s1_and_s2_are_hash_pinned_and_attributed(self):
        s2 = VerifiedStoreManifest.load(
            root=EXPERIMENT / "stores" / "s2-foldered",
            store_id="s2",
            catalog=self.catalog,
            manifest_path=EXPERIMENT / "manifests" / "s2-foldered.json",
            expected_manifest_sha256=S2_MANIFEST_SHA256,
            commit_marker_path=EXPERIMENT / "manifests" / "s2-foldered.COMMITTED",
            expected_commit_marker_sha256=S2_MARKER_SHA256,
            path_map_path=EXPERIMENT / "manifests" / "s2-foldered-path-map.json",
            trace_path=EXPERIMENT / "traces" / "s2-foldering.json",
        )
        self.assertEqual(len(self.s1_manifest.attribution_index._by_locator), 568)
        self.assertEqual(len(s2.attribution_index._by_locator), 568)
        self.assertEqual(self.s1_manifest.manifest_sha256, S1_MANIFEST_SHA256)
        self.assertEqual(s2.manifest_sha256, S2_MANIFEST_SHA256)

    def test_manifest_rejects_wrong_external_hash_and_tampered_store(self):
        with self.assertRaisesRegex(EvidenceValidationError, "frozen hash"):
            VerifiedStoreManifest.load(
                root=self.s1_root,
                store_id="s1",
                catalog=self.catalog,
                manifest_path=EXPERIMENT / "manifests" / "s1-flat.json",
                expected_manifest_sha256="0" * 64,
            )
        path = self.s1_root / "session-01.md"
        path.write_text(path.read_text().replace("explore the city", "change the city"), encoding="utf-8")
        with self.assertRaisesRegex(EvidenceValidationError, "bytes differ"):
            VerifiedStoreManifest.load(
                root=self.s1_root,
                store_id="s1",
                catalog=self.catalog,
                manifest_path=EXPERIMENT / "manifests" / "s1-flat.json",
                expected_manifest_sha256=S1_MANIFEST_SHA256,
            )

    def test_snapshot_capture_rejects_post_manifest_empty_directory(self):
        (self.s1_root / "unauthorized-empty-directory").mkdir()
        with self.assertRaisesRegex(EvidenceValidationError, "tree differs"):
            StoreSnapshotRef.capture(
                root=self.s1_root,
                catalog=self.catalog,
                verified_manifest=self.s1_manifest,
            )

    def test_verified_manifest_rejects_byte_identical_copy_at_another_mount(self):
        copied_root = self.temp_root / "not-s1"
        shutil.copytree(self.s1_root, copied_root)
        with self.assertRaisesRegex(EvidenceValidationError, "published root"):
            StoreSnapshotRef.capture(
                root=copied_root,
                catalog=self.catalog,
                verified_manifest=self.s1_manifest,
            )
        with self.assertRaisesRegex(EvidenceValidationError, "published root"):
            self.raw_item(root=copied_root)

    def test_snapshot_rejects_catalog_different_from_manifest_verification(self):
        records = [json.loads(line) for line in RECORDS.read_text().splitlines()]
        for record in records:
            if record["session_id"] == "session_1":
                record["session_date"] = "2023-03-24"
                record["session_datetime"] = record["session_datetime"].replace(
                    "2023-03-23", "2023-03-24"
                )
        records_payload = "".join(
            json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            + "\n"
            for record in records
        ).encode("utf-8")
        source_map = json.loads(SOURCE_MAP.read_text())
        source_map["record_sha256"] = sha256_bytes(records_payload)
        source_map["record_bytes"] = len(records_payload)
        source_map["sessions"]["session_1"]["session_date"] = "2023-03-24"
        source_map["sessions"]["session_1"]["session_datetime"] = (
            source_map["sessions"]["session_1"]["session_datetime"].replace(
                "2023-03-23", "2023-03-24"
            )
        )
        source_map_payload = (
            json.dumps(source_map, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        ).encode("utf-8")
        records_path = self.temp_root / "mismatched-records.jsonl"
        source_map_path = self.temp_root / "mismatched-source-map.json"
        records_path.write_bytes(records_payload)
        source_map_path.write_bytes(source_map_payload)
        mismatched_catalog = SourceCatalog.load(
            source_map_path,
            records_path,
            expected_source_map_sha256=sha256_bytes(source_map_payload),
            expected_records_sha256=sha256_bytes(records_payload),
            expected_conversation_id="conv-50",
        )
        with self.assertRaisesRegex(EvidenceValidationError, "Catalog identity"):
            StoreSnapshotRef.capture(
                root=self.s1_root,
                catalog=mismatched_catalog,
                verified_manifest=self.s1_manifest,
            )

    def test_verified_manifest_capability_cannot_be_replaced(self):
        with self.assertRaisesRegex(TypeError, "InitVar.*must be specified"):
            replace(self.s1_manifest, verified_tree_sha256="0" * 64)
        with self.assertRaisesRegex(EvidenceValidationError, "produced by its loader"):
            replace(self.s1_manifest, _verification_seal=object())

    def test_raw_manifest_must_cover_every_canonical_locator(self):
        manifest = json.loads((EXPERIMENT / "manifests" / "s1-flat.json").read_text())
        manifest["source_index"].pop("[S1T13]")
        payload = (json.dumps(manifest, sort_keys=True, indent=2) + "\n").encode()
        path = self.temp_root / "partial-s1.json"
        path.write_bytes(payload)
        with self.assertRaisesRegex(EvidenceValidationError, "does not cover"):
            VerifiedStoreManifest.load(
                root=self.s1_root,
                store_id="s1",
                catalog=self.catalog,
                manifest_path=path,
                expected_manifest_sha256=sha256_bytes(payload),
            )

    def test_s2_requires_hash_pinned_committed_marker(self):
        kwargs = dict(
            root=EXPERIMENT / "stores" / "s2-foldered",
            store_id="s2",
            catalog=self.catalog,
            manifest_path=EXPERIMENT / "manifests" / "s2-foldered.json",
            expected_manifest_sha256=S2_MANIFEST_SHA256,
        )
        with self.assertRaisesRegex(EvidenceValidationError, "requires.*COMMITTED"):
            VerifiedStoreManifest.load(**kwargs)
        with self.assertRaisesRegex(EvidenceValidationError, "frozen hash"):
            VerifiedStoreManifest.load(
                **kwargs,
                commit_marker_path=EXPERIMENT / "manifests" / "s2-foldered.COMMITTED",
                expected_commit_marker_sha256="0" * 64,
            )

        manifest = json.loads(
            (EXPERIMENT / "manifests" / "s2-foldered.json").read_text()
        )
        marker = json.loads(
            (EXPERIMENT / "manifests" / "s2-foldered.COMMITTED").read_text()
        )
        manifest["path_map"]["sha256"] = "0" * 64
        marker["path_map_sha256"] = "0" * 64
        manifest_payload = (
            json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        ).encode()
        marker["manifest_sha256"] = sha256_bytes(manifest_payload)
        marker_payload = (
            json.dumps(marker, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        ).encode()
        manifest_path = self.temp_root / "s2-mismatched.json"
        marker_path = self.temp_root / "s2-mismatched.COMMITTED"
        manifest_path.write_bytes(manifest_payload)
        marker_path.write_bytes(marker_payload)
        with self.assertRaisesRegex(EvidenceValidationError, "artifact hash mismatch"):
            VerifiedStoreManifest.load(
                root=EXPERIMENT / "stores" / "s2-foldered",
                store_id="s2",
                catalog=self.catalog,
                manifest_path=manifest_path,
                expected_manifest_sha256=sha256_bytes(manifest_payload),
                commit_marker_path=marker_path,
                expected_commit_marker_sha256=sha256_bytes(marker_payload),
                path_map_path=EXPERIMENT / "manifests" / "s2-foldered-path-map.json",
                trace_path=EXPERIMENT / "traces" / "s2-foldering.json",
            )

    def test_s3_duplicate_occurrences_are_semantically_deduplicated(self):
        self.write_curated(
            self.curated_memory().replace(
                "[S1T13].", "[S1T13][S1T13]."
            )
        )
        duplicate = {
            "[S1T13]": [
                {"file": "notes.md", "line": 8},
                {"file": "notes.md", "line": 8},
            ],
            "[S2T2]": [{"file": "notes.md", "line": 9}],
        }
        verified, _, _ = self.make_s3_manifest(duplicate)
        self.assertEqual(len(verified.attribution_index.occurrences("[S1T13]")), 1)
        deduped = AttributionIndex.from_source_index(
            store_id="s3",
            source_index={
                "[S1T13]": [{"file": "notes.md", "line": 8}],
                "[S2T2]": [{"file": "notes.md", "line": 9}],
            },
            catalog=self.catalog,
        )
        self.assertNotEqual(verified.attribution_index.index_sha256, deduped.index_sha256)

    def test_store_snapshot_detects_file_and_empty_directory_changes(self):
        path = self.s1_root / "session-01.md"
        path.write_text(path.read_text().replace("Japan", "Tokyo", 1), encoding="utf-8")
        with self.assertRaisesRegex(EvidenceValidationError, "snapshot|canonical turn"):
            self.raw_item(snapshot=self.s1_snapshot)
        shutil.copyfile(EXPERIMENT / "stores" / "s1-flat" / "session-01.md", path)
        (self.s1_root / "new-empty-route").mkdir()
        with self.assertRaisesRegex(EvidenceValidationError, "snapshot"):
            self.raw_item(snapshot=self.s1_snapshot)

    def test_raw_item_requires_complete_source_turns(self):
        item = self.raw_item()
        self.assertEqual(item.source_locators, ("[S1T13]",))
        self.assertIn("[S1T13] (dia_id: D1:13)", item.text)
        self.assertEqual(item.attribution_units[0].kind, "raw_turn")
        validate_evidence_item(
            item,
            root=self.s1_root,
            catalog=self.catalog,
            verified_manifest=self.s1_manifest,
            snapshot=self.s1_snapshot,
        )
        with self.assertRaisesRegex(EvidenceValidationError, "complete source-turn"):
            self.raw_item(line_end=item.line_end - 1)

    def test_raw_multi_turn_item_tracks_each_attribution(self):
        first = self.s1_manifest.attribution_index.occurrences("[S1T13]")[0]
        second = self.s1_manifest.attribution_index.occurrences("[S1T14]")[0]
        item = self.raw_item(line_start=first.line_start, line_end=second.line_end)
        self.assertEqual(item.source_locators, ("[S1T13]", "[S1T14]"))
        self.assertEqual(len(item.attribution_units), 2)
        self.assertIsNone(item.speaker)

    def test_curated_item_requires_locator_on_every_fact_line(self):
        verified, snapshot = self.curated_context()
        item = self.curated_item(verified, snapshot)
        self.assertEqual(item.source_locators, ("[S1T13]", "[S2T2]"))
        self.assertEqual(len(item.attribution_units), 2)
        bad = self.curated_memory().replace(
            "- Dave later encouraged him [S2T2].",
            "- This model-authored claim has no source.",
        )
        self.write_curated(bad)
        with self.assertRaisesRegex(EvidenceValidationError, "snapshot|line mismatch"):
            self.curated_item(verified, snapshot)

    def test_curated_rejects_heading_frontmatter_and_malformed_locator(self):
        verified, snapshot = self.curated_context()
        with self.assertRaisesRegex(EvidenceValidationError, "Frontmatter"):
            self.curated_item(verified, snapshot, line_start=2, line_end=3)
        with self.assertRaisesRegex(EvidenceValidationError, "routing metadata"):
            self.curated_item(verified, snapshot, line_start=6, line_end=8)
        self.write_curated(self.curated_memory().replace("[S2T2]", "[S2Tx]"))
        with self.assertRaises(EvidenceValidationError):
            self.make_s3_manifest()

    def test_noncanonical_paths_symlinks_and_invalid_utf8_are_rejected(self):
        for path in ("/memories/./session-01.md", "/memories//session-01.md"):
            with self.assertRaisesRegex(EvidenceValidationError, "canonical POSIX|unsafe"):
                self.raw_item(path=path)
        alias = self.s1_root / "alias.md"
        try:
            alias.symlink_to(self.s1_root / "session-01.md")
        except OSError as exc:
            self.skipTest(f"symlinks unavailable: {exc}")
        with self.assertRaisesRegex(EvidenceValidationError, "symlink"):
            VerifiedStoreManifest.load(
                root=self.s1_root,
                store_id="s1",
                catalog=self.catalog,
                manifest_path=EXPERIMENT / "manifests" / "s1-flat.json",
                expected_manifest_sha256=S1_MANIFEST_SHA256,
            )
        alias.unlink()
        (self.s1_root / "session-01.md").write_bytes(b"\xff\xfe")
        with self.assertRaisesRegex(EvidenceValidationError, "UTF-8|bytes differ"):
            VerifiedStoreManifest.load(
                root=self.s1_root,
                store_id="s1",
                catalog=self.catalog,
                manifest_path=EXPERIMENT / "manifests" / "s1-flat.json",
                expected_manifest_sha256=S1_MANIFEST_SHA256,
            )

    def test_bundle_identity_is_deterministic_frozen_and_tamper_evident(self):
        item = self.raw_item()
        kwargs = self.bundle_kwargs(item, self.s1_snapshot)
        first = EvidenceBundle.create(**kwargs)
        second = EvidenceBundle.create(**kwargs)
        self.assertEqual(first, second)
        kwargs["model"]["served_models"].append("mutated")
        self.assertEqual(first.model["served_models"], ("qwen3.8:27b",))
        validate_evidence_bundle(
            first,
            root=self.s1_root,
            catalog=self.catalog,
            verified_manifest=self.s1_manifest,
        )
        validate_r1_evidence_bundle_profile(first)
        mutable_condition = dict(first.condition)
        replaced = replace(first, condition=mutable_condition)
        mutable_condition["store_id"] = "s3"
        self.assertEqual(replaced.condition["store_id"], "s1")
        validate_evidence_bundle(
            replaced,
            root=self.s1_root,
            catalog=self.catalog,
            verified_manifest=self.s1_manifest,
        )
        with self.assertRaisesRegex(EvidenceValidationError, "identity"):
            validate_evidence_bundle(
                replace(first, bundle_id="bundle-" + "0" * 64),
                root=self.s1_root,
                catalog=self.catalog,
                verified_manifest=self.s1_manifest,
            )

    def test_evidence_item_rejects_mutable_optional_scalars_and_wrong_children(self):
        item = self.raw_item()
        for field in ("section", "session_id", "timestamp", "speaker"):
            with self.subTest(field=field):
                with self.assertRaises(EvidenceValidationError):
                    replace(item, **{field: []})
        with self.assertRaisesRegex(EvidenceValidationError, "source_records"):
            replace(item, source_records=(object(),))
        with self.assertRaisesRegex(EvidenceValidationError, "attribution_units"):
            replace(item, attribution_units=(object(),))
        with self.assertRaisesRegex(EvidenceValidationError, "ordered list or tuple"):
            replace(item, query_terms="Japan")
        with self.assertRaisesRegex(EvidenceValidationError, "ordered list or tuple"):
            self.raw_item(query_terms="Japan")

    def test_protocol_arrays_reject_unordered_or_mapping_inputs(self):
        item = self.raw_item()
        with self.assertRaisesRegex(EvidenceValidationError, "ordered list or tuple"):
            self.raw_item(observation_ids={"obs-0001"})
        with self.assertRaisesRegex(EvidenceValidationError, "ordered list or tuple"):
            self.raw_item(query_terms={"Japan", "trip"})
        with self.assertRaisesRegex(EvidenceValidationError, "ordered list or tuple"):
            replace(item, source_locators={"[S1T13]"})
        with self.assertRaisesRegex(EvidenceValidationError, "ordered list or tuple"):
            replace(item, source_records={item.source_records[0]})
        with self.assertRaisesRegex(EvidenceValidationError, "ordered list or tuple"):
            replace(item, attribution_units={item.attribution_units[0]})
        with self.assertRaisesRegex(EvidenceValidationError, "ordered list or tuple"):
            self.catalog.resolve_many({"[S1T13]"})
        with self.assertRaisesRegex(EvidenceValidationError, "ordered list or tuple"):
            StopRecord("evidence_sufficient", False, {"topic"}, 0, None)

        kwargs = self.bundle_kwargs(item, self.s1_snapshot)
        kwargs["search_actions"] = {"unexpected": "mapping"}
        with self.assertRaisesRegex(EvidenceValidationError, "ordered list or tuple"):
            EvidenceBundle.create(**kwargs)
        kwargs = self.bundle_kwargs(item, self.s1_snapshot)
        kwargs["evidence_items"] = {"unexpected": "mapping"}
        with self.assertRaisesRegex(EvidenceValidationError, "ordered list or tuple"):
            EvidenceBundle.create(**kwargs)
        kwargs = self.bundle_kwargs(item, self.s1_snapshot)
        kwargs["errors"] = {"unexpected": "mapping"}
        with self.assertRaisesRegex(EvidenceValidationError, "ordered list or tuple"):
            EvidenceBundle.create(**kwargs)

    def test_bundle_core_objects_and_fallback_proof_are_typed(self):
        class MutableProof:
            def __init__(self):
                self.value = []

            def to_dict(self):
                return {"value": self.value}

        with self.assertRaisesRegex(EvidenceValidationError, "fallback_proof"):
            StopRecord("not_found_after_global_fallback", False, (), 0, MutableProof())
        item = self.raw_item()
        kwargs = self.bundle_kwargs(item, self.s1_snapshot)
        kwargs["question"] = {}
        with self.assertRaisesRegex(EvidenceValidationError, "question type"):
            EvidenceBundle.create(**kwargs)
        kwargs = self.bundle_kwargs(item, self.s1_snapshot)
        kwargs["evidence_items"] = [object()]
        with self.assertRaisesRegex(EvidenceValidationError, "item type"):
            EvidenceBundle.create(**kwargs)

    def test_shared_bundle_allows_ranked_r2_but_r1_profile_does_not(self):
        ranked = self.raw_item(rank=1, score=0.75)
        r2 = EvidenceBundle.create(
            **self.bundle_kwargs(ranked, self.s1_snapshot, retrieval_id="r2")
        )
        validate_evidence_bundle(
            r2,
            root=self.s1_root,
            catalog=self.catalog,
            verified_manifest=self.s1_manifest,
        )
        self.assertEqual(r2.evidence_items[0].rank, 1)
        self.assertEqual(r2.evidence_items[0].score, 0.75)
        with self.assertRaisesRegex(EvidenceValidationError, "retrieval_id"):
            validate_r1_evidence_bundle_profile(r2)
        ranked_r1 = EvidenceBundle.create(
            **self.bundle_kwargs(ranked, self.s1_snapshot, retrieval_id="r1")
        )
        with self.assertRaisesRegex(EvidenceValidationError, "rank or score"):
            validate_r1_evidence_bundle_profile(ranked_r1)

    def test_integer_and_float_scores_have_one_canonical_representation(self):
        integer_item = self.raw_item(rank=1, score=1)
        float_item = self.raw_item(rank=1, score=1.0)
        negative_zero_item = self.raw_item(rank=1, score=-0.0)
        self.assertIsInstance(integer_item.score, float)
        self.assertEqual(integer_item, float_item)
        self.assertEqual(negative_zero_item.score, 0.0)
        integer_bundle = EvidenceBundle.create(
            **self.bundle_kwargs(integer_item, self.s1_snapshot, retrieval_id="r2")
        )
        float_bundle = EvidenceBundle.create(
            **self.bundle_kwargs(float_item, self.s1_snapshot, retrieval_id="r2")
        )
        self.assertEqual(integer_bundle.bundle_id, float_bundle.bundle_id)
        self.assertEqual(
            canonical_json_bytes(integer_bundle.to_dict()),
            canonical_json_bytes(float_bundle.to_dict()),
        )

    def test_bundle_rejects_unknown_schema_mixed_store_and_false_budget(self):
        item = self.raw_item()
        kwargs = self.bundle_kwargs(item, self.s1_snapshot)
        kwargs["condition"]["nested"] = []
        with self.assertRaisesRegex(EvidenceValidationError, "keys must be exactly"):
            EvidenceBundle.create(**kwargs)
        kwargs = self.bundle_kwargs(item, self.s1_snapshot)
        kwargs["evidence_items"] = [replace(item, store_id="s3", source_kind="curated")]
        with self.assertRaisesRegex(EvidenceValidationError, "differs from bundle store"):
            EvidenceBundle.create(**kwargs)
        kwargs = self.bundle_kwargs(item, self.s1_snapshot)
        kwargs["budget"] = replace(kwargs["budget"], used=0)
        with self.assertRaisesRegex(EvidenceValidationError, "does not match"):
            EvidenceBundle.create(**kwargs)

    def test_bundle_selection_ordinals_follow_serialized_order(self):
        second_span = self.s1_manifest.attribution_index.occurrences("[S1T14]")[0]
        first = self.raw_item(selection_ordinal=2)
        second = self.raw_item(
            path="/memories/" + second_span.path,
            line_start=second_span.line_start,
            line_end=second_span.line_end,
            selection_ordinal=1,
        )
        kwargs = self.bundle_kwargs(first, self.s1_snapshot)
        kwargs["evidence_items"] = [first, second]
        kwargs["budget"] = replace(
            kwargs["budget"],
            used=len(first.text.encode("utf-8")) + len(second.text.encode("utf-8")),
        )
        with self.assertRaisesRegex(EvidenceValidationError, "strictly increasing"):
            EvidenceBundle.create(**kwargs)

        duplicate = replace(second, selection_ordinal=2)
        kwargs["evidence_items"] = [first, duplicate]
        with self.assertRaisesRegex(EvidenceValidationError, "strictly increasing"):
            EvidenceBundle.create(**kwargs)

    def test_bundle_rejects_overlapping_ranges_from_the_same_path(self):
        first_span = self.s1_manifest.attribution_index.occurrences("[S1T13]")[0]
        second_span = self.s1_manifest.attribution_index.occurrences("[S1T14]")[0]
        single = self.raw_item(selection_ordinal=1)
        overlapping = self.raw_item(
            line_start=first_span.line_start,
            line_end=second_span.line_end,
            selection_ordinal=2,
        )
        kwargs = self.bundle_kwargs(single, self.s1_snapshot)
        kwargs["evidence_items"] = [single, overlapping]
        kwargs["budget"] = replace(
            kwargs["budget"],
            used=len(single.text.encode("utf-8"))
            + len(overlapping.text.encode("utf-8")),
        )
        with self.assertRaisesRegex(EvidenceValidationError, "overlapping or adjacent"):
            EvidenceBundle.create(**kwargs)

        verified, snapshot = self.curated_context()
        first_fact = self.curated_item(
            verified, snapshot, line_start=8, line_end=8, selection_ordinal=1
        )
        adjacent_fact = self.curated_item(
            verified, snapshot, line_start=9, line_end=9, selection_ordinal=2
        )
        kwargs = self.bundle_kwargs(first_fact, snapshot)
        kwargs["evidence_items"] = [first_fact, adjacent_fact]
        kwargs["budget"] = replace(
            kwargs["budget"],
            used=len(first_fact.text.encode("utf-8"))
            + len(adjacent_fact.text.encode("utf-8")),
        )
        with self.assertRaisesRegex(EvidenceValidationError, "overlapping or adjacent"):
            EvidenceBundle.create(**kwargs)

    def test_bundle_rejects_unreported_round_and_missing_served_model(self):
        item = self.raw_item(retrieval_round=3)
        with self.assertRaisesRegex(EvidenceValidationError, "retrieval_round"):
            EvidenceBundle.create(**self.bundle_kwargs(item, self.s1_snapshot))
        item = self.raw_item()
        kwargs = self.bundle_kwargs(item, self.s1_snapshot)
        kwargs["model"]["served_models"] = []
        with self.assertRaisesRegex(EvidenceValidationError, "served model"):
            EvidenceBundle.create(**kwargs)

    def test_stop_status_matrix_and_fallback_proof(self):
        with self.assertRaisesRegex(EvidenceValidationError, "fallback proof"):
            StopRecord("not_found_after_global_fallback", False, (), 0, None)
        proof = GlobalFallbackProof("obs-0001", "obs-0002")
        with self.assertRaisesRegex(EvidenceValidationError, "No-progress"):
            StopRecord("no_progress_after_global_fallback", False, (), 0, proof)
        with self.assertRaisesRegex(EvidenceValidationError, "at least two"):
            StopRecord("no_progress_after_global_fallback", False, (), 1, proof)
        StopRecord("no_progress_after_global_fallback", False, (), 2, proof)
        with self.assertRaisesRegex(EvidenceValidationError, "ordered list or tuple"):
            StopRecord("evidence_sufficient", False, "topic", 0, None)
        item = self.raw_item()
        impossible = self.bundle_kwargs(item, self.s1_snapshot)
        impossible["stop"] = StopRecord(
            "evidence_sufficient", False, (), 999, None
        )
        with self.assertRaisesRegex(EvidenceValidationError, "exceeds reported"):
            EvidenceBundle.create(**impossible)
        kwargs = self.bundle_kwargs(item, self.s1_snapshot)
        kwargs["status"] = "capped"
        kwargs["stop"] = StopRecord("round_limit", True, (), 0, None)
        with self.assertRaisesRegex(EvidenceValidationError, "reach the configured"):
            EvidenceBundle.create(**kwargs)
        kwargs["metrics"].update(
            provider_rounds=20, model_calls=20, provider_request_attempts=20
        )
        EvidenceBundle.create(**kwargs)

    def test_failure_artifact_is_separate_and_tamper_evident(self):
        item = self.raw_item()
        kwargs = self.bundle_kwargs(item, self.s1_snapshot)
        failure = RetrievalFailureArtifact.create(
            question=self.question,
            condition=kwargs["condition"],
            store_snapshot=self.s1_snapshot,
            prompt_contract=kwargs["prompt_contract"],
            runtime_contract=kwargs["runtime_contract"],
            search_actions=[],
            metrics=kwargs["metrics"],
            model=kwargs["model"],
            integrity={
                "store_unchanged": False,
                "pre_tree_sha256": self.s1_snapshot.tree_sha256,
                "post_tree_sha256": "0" * 64,
                "verified": False,
            },
            failure_kind="store_drift",
            errors=[{"code": "STORE_DRIFT", "safe_message": "store changed"}],
        )
        validate_retrieval_failure_artifact(failure)
        mutable_condition = dict(failure.condition)
        frozen_copy = replace(failure, condition=mutable_condition)
        mutable_condition["store_id"] = "s3"
        self.assertEqual(frozen_copy.condition["store_id"], "s1")
        validate_retrieval_failure_artifact(frozen_copy)
        with self.assertRaisesRegex(EvidenceValidationError, "identity"):
            validate_retrieval_failure_artifact(
                replace(failure, failure_id="failure-" + "0" * 64)
            )
        with self.assertRaisesRegex(EvidenceValidationError, "ordered list or tuple"):
            replace(failure, search_actions={"unexpected": "mapping"})
        with self.assertRaisesRegex(EvidenceValidationError, "ordered list or tuple"):
            replace(failure, errors={"unexpected": "mapping"})

    def test_attribution_unit_and_budget_fail_closed(self):
        with self.assertRaisesRegex(EvidenceValidationError, "multiple dia_ids"):
            AttributionUnit(
                1,
                1,
                "curated_fact",
                ("[S1T1]", "[S1T1]"),
                ("D1:1", "D1:2"),
                "a" * 64,
            )
        with self.assertRaisesRegex(EvidenceValidationError, "ordered list or tuple"):
            AttributionUnit(
                1,
                1,
                "curated_fact",
                {"[S1T1]"},
                ("D1:1",),
                "a" * 64,
            )
        BudgetRecord("bytes", None, 100, 90, 0, False)
        with self.assertRaisesRegex(EvidenceValidationError, "disabled"):
            BudgetRecord("tokens", None, 100, 90, 0, False)
        with self.assertRaisesRegex(EvidenceValidationError, "cannot claim"):
            BudgetRecord("bytes", TokenizerRef("tok", "1", "f" * 64), 100, 90, 0, False)
        with self.assertRaisesRegex(EvidenceValidationError, "never be truncated"):
            BudgetRecord("bytes", None, 100, 90, 0, True)

    def test_canonical_json_and_score_reject_nonfinite_values(self):
        for value in (math.nan, math.inf, -math.inf):
            with self.assertRaises(EvidenceValidationError):
                canonical_json_bytes({"bad": value})
            with self.assertRaises(EvidenceValidationError):
                self.raw_item(score=value)
        with self.assertRaises(EvidenceValidationError):
            canonical_json_bytes({"bad": {1, 2}})
        value = {"é": "东京", "a": 1}
        self.assertEqual(
            canonical_json_bytes(value),
            canonical_json_bytes(json.loads(canonical_json_bytes(value))),
        )


if __name__ == "__main__":
    unittest.main()
