import json
import shutil
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from fs_memory_lab.evidence import (
    EvidenceValidationError,
    SourceCatalog,
    StoreSnapshotRef,
    VerifiedStoreManifest,
    canonical_json_bytes,
    sha256_bytes,
)
from fs_memory_lab.r1_orchestration import (
    MODEL_FINISH_REASONS,
    MISSING_ASPECT_LABELS,
    R1_ORCHESTRATION_ACTION_NAMES,
    R1_ORCHESTRATION_LIMITS,
    R1_ORCHESTRATION_PROTOCOL_VERSION,
    R1_ROUND_LIMIT_BY_STORE,
    EvidenceNoteState,
    FinishSearchRequest,
    FinishSearchResolver,
    NoteSelector,
    ObservationLedger,
    ObservationRecord,
    ProviderRoundLedger,
    R1OrchestrationError,
    TakeNoteResolution,
    TakeNoteResolver,
    r1_orchestration_action_schemas,
    r1_orchestration_limits_sha256,
    r1_orchestration_profile_sha256,
    r1_orchestration_schema_sha256,
    r1_orchestration_wire_sha256,
)
from fs_memory_lab.r1_tools import LineCoverage, R1ReadOnlyFilesystem, ReadToolResult


REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_MAP = REPO_ROOT / "data" / "manifests" / "source_map.json"
RECORDS = REPO_ROOT / "data" / "processed" / "conv-50.jsonl"
EXPERIMENT = REPO_ROOT / "experiments" / "locomo-conv50-v1"
SOURCE_MAP_SHA256 = "6e99115961bae06a48bfb7e82dbdcc18dc32ccf6c5ce57e3c266dfc7a5d4d574"
RECORDS_SHA256 = "130a5a1e1b75083358ef27a98dd215a4e75c819ace6f2ee9b560ba394e0f0394"
S1_MANIFEST_SHA256 = "5c5900c333c8f85463f038448560cb4357f1161d6ed43e9fbc86809ba7916d3c"
S2_MANIFEST_SHA256 = "4858e430f3c197d4f718ea5839596597c3dbbd885e3d1fc654e982a90dc707ac"
S2_MARKER_SHA256 = "af329bf6749b5909d809d81f52e41079d898a18d86c8bb2d80db0170fbb8b6a9"


class R1OrchestrationSchemaTest(unittest.TestCase):
    def test_schema_names_order_and_capability_boundary(self):
        schemas = r1_orchestration_action_schemas()
        self.assertEqual(
            R1_ORCHESTRATION_PROTOCOL_VERSION, "r1-evidence-orchestration-v2"
        )
        self.assertEqual(
            tuple(item["function"]["name"] for item in schemas),
            R1_ORCHESTRATION_ACTION_NAMES,
        )
        self.assertEqual(R1_ORCHESTRATION_ACTION_NAMES, ("take_note", "finish_search"))
        take_note = schemas[0]["function"]["parameters"]
        self.assertEqual(
            take_note["required"],
            ["observation_ids", "path", "line_start", "line_end"],
        )
        self.assertFalse(take_note["additionalProperties"])
        self.assertNotIn("text", take_note["properties"])
        self.assertNotIn("answer", take_note["properties"])
        self.assertNotIn("source_locators", take_note["properties"])
        finish = schemas[1]["function"]["parameters"]
        self.assertEqual(finish["required"], ["reason", "missing_aspects"])
        self.assertEqual(
            finish["properties"]["reason"]["enum"], list(MODEL_FINISH_REASONS)
        )
        self.assertNotIn("round_limit", MODEL_FINISH_REASONS)
        self.assertNotIn("protocol_failure", MODEL_FINISH_REASONS)
        self.assertEqual(
            finish["properties"]["missing_aspects"]["items"]["enum"],
            list(MISSING_ASPECT_LABELS),
        )

    def test_schema_copy_is_detached_and_limits_are_explicit(self):
        first = r1_orchestration_action_schemas()
        first[0]["function"]["description"] = "caller mutation"
        self.assertNotEqual(
            first[0]["function"]["description"],
            r1_orchestration_action_schemas()[0]["function"]["description"],
        )
        self.assertEqual(R1_ORCHESTRATION_LIMITS["max_observation_ids_per_note"], 32)
        self.assertEqual(R1_ORCHESTRATION_LIMITS["max_missing_aspects"], 16)
        self.assertEqual(
            R1_ORCHESTRATION_LIMITS["missing_aspect_taxonomy_size"],
            len(MISSING_ASPECT_LABELS),
        )
        self.assertEqual(
            dict(R1_ROUND_LIMIT_BY_STORE),
            {"s1": 20, "s2": 20, "s3": 40},
        )
        self.assertEqual(
            dict(R1_ORCHESTRATION_LIMITS["round_limit_by_store"]),
            {"s1": 20, "s2": 20, "s3": 40},
        )

    def test_frozen_hashes_are_stable(self):
        self.assertRegex(r1_orchestration_profile_sha256(), r"^[0-9a-f]{64}$")
        self.assertRegex(r1_orchestration_schema_sha256(), r"^[0-9a-f]{64}$")
        self.assertRegex(r1_orchestration_wire_sha256(), r"^[0-9a-f]{64}$")
        self.assertRegex(r1_orchestration_limits_sha256(), r"^[0-9a-f]{64}$")


class ObservationLedgerTest(unittest.TestCase):
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
        self.store = Path(self.temporary.name) / "s1-flat"
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
        self.ledger = ObservationLedger.start(
            question_sha256="a" * 64,
            snapshot=self.snapshot,
        )
        self.resolver = TakeNoteResolver(
            root=self.store,
            catalog=self.catalog,
            verified_manifest=self.manifest,
            snapshot=self.snapshot,
            question_sha256="a" * 64,
        )
        self.note_state = EvidenceNoteState.start(
            question_sha256="a" * 64,
            snapshot=self.snapshot,
            budget_unit="bytes",
            budget_limit=100_000,
        )
        self.finish_resolver = FinishSearchResolver(
            root=self.store,
            catalog=self.catalog,
            verified_manifest=self.manifest,
            snapshot=self.snapshot,
            question_sha256="a" * 64,
        )

    def tearDown(self):
        self.temporary.cleanup()

    def append(self, ledger, result, provider_round, action_ordinal):
        arguments = dict(result.canonical_args)
        if result.tool_name == "view" and not result.coverage:
            arguments = {"path": arguments["path"]}
        return ledger.execute_and_append(
            filesystem=self.filesystem,
            tool_name=result.tool_name,
            arguments=arguments,
            provider_round=provider_round,
            action_ordinal=action_ordinal,
        )

    def accepted_note(self):
        span = self.manifest.attribution_index.occurrences("[S1T13]")[0]
        path = "/memories/" + span.path
        result = self.filesystem.execute(
            "view",
            {"path": path, "start_line": span.line_start, "end_line": span.line_end},
        )
        ledger, observation = self.append(self.ledger, result, 1, 1)
        resolution = self.resolver.resolve(
            ledger=ledger,
            state=self.note_state,
            arguments={
                "observation_ids": [observation.observation_id],
                "path": path,
                "line_start": span.line_start,
                "line_end": span.line_end,
            },
            current_round=2,
        )
        return ledger, resolution

    def test_successful_results_are_replayed_and_content_addressed(self):
        result = self.filesystem.execute("view", {"path": "/memories"})
        ledger, observation = self.append(self.ledger, result, 1, 1)
        self.assertEqual(observation.observation_id, "obs-0001")
        self.assertEqual(ledger.require("obs-0001"), observation)
        self.assertEqual(observation.result, result)
        self.assertNotIn("content", observation.to_action_dict())
        self.assertEqual(
            observation,
            self.append(self.ledger, result, 1, 1)[1],
        )
        with self.assertRaisesRegex(EvidenceValidationError, "content hash"):
            replace(observation, observation_sha256="0" * 64)
        with self.assertRaisesRegex(EvidenceValidationError, "action_ordinal"):
            self.append(ledger, result, 1, 1)

    def test_bare_or_forged_read_result_cannot_enter_the_episode_ledger(self):
        actual = self.filesystem.execute(
            "view",
            {"path": "/memories/session-01.md", "start_line": 52, "end_line": 53},
        )
        forged = ReadToolResult.create(
            tool_name="view",
            canonical_args=actual.canonical_args,
            content="L52: forged\nL53: forged",
            coverage=(LineCoverage("/memories/session-01.md", 52, 53),),
            truncated=False,
            result_count=2,
            root_survey=False,
            whole_tree_grep=False,
            pre_tree_sha256=self.snapshot.tree_sha256,
            post_tree_sha256=self.snapshot.tree_sha256,
        )
        self.assertFalse(hasattr(self.ledger, "append_success"))
        _ledger, genuine = self.ledger.execute_and_append(
            filesystem=self.filesystem,
            tool_name=actual.tool_name,
            arguments=actual.canonical_args,
            provider_round=1,
            action_ordinal=1,
        )
        with self.assertRaisesRegex(EvidenceValidationError, "receipt differs"):
            replace(genuine, result=forged)

    def test_resolvers_reject_another_question_and_direct_forged_ledger(self):
        span = self.manifest.attribution_index.occurrences("[S1T13]")[0]
        path = "/memories/" + span.path
        actual = self.filesystem.execute(
            "view",
            {"path": path, "start_line": span.line_start, "end_line": span.line_end},
        )
        other = ObservationLedger.start(
            question_sha256="b" * 64,
            snapshot=self.snapshot,
        )
        other, observation = other.execute_and_append(
            filesystem=self.filesystem,
            tool_name=actual.tool_name,
            arguments=actual.canonical_args,
            provider_round=1,
            action_ordinal=1,
        )
        with self.assertRaisesRegex(EvidenceValidationError, "Question"):
            self.resolver.resolve(
                ledger=other,
                state=self.note_state,
                arguments={
                    "observation_ids": [observation.observation_id],
                    "path": path,
                    "line_start": span.line_start,
                    "line_end": span.line_end,
                },
                current_round=2,
            )

        root_actual = self.filesystem.execute("view", {"path": "/memories"})
        forged_result = ReadToolResult.create(
            tool_name="view",
            canonical_args=root_actual.canonical_args,
            content=root_actual.content + "\nforged-entry.md",
            coverage=root_actual.coverage,
            truncated=root_actual.truncated,
            result_count=root_actual.result_count + 1,
            root_survey=True,
            whole_tree_grep=False,
            pre_tree_sha256=root_actual.pre_tree_sha256,
            post_tree_sha256=root_actual.post_tree_sha256,
        )
        genuine_ledger, genuine = self.append(self.ledger, root_actual, 1, 1)
        with self.assertRaisesRegex(EvidenceValidationError, "receipt differs"):
            replace(genuine, result=forged_result)
        other_empty = ObservationLedger.start(
            question_sha256="b" * 64,
            snapshot=self.snapshot,
        )
        with self.assertRaisesRegex(EvidenceValidationError, "identity differs"):
            replace(other_empty, observations=(genuine,))
        self.assertEqual(len(genuine_ledger.observations), 1)

    def test_coverage_union_is_gap_free_prior_round_only_and_contributory(self):
        first = self.filesystem.execute(
            "view",
            {"path": "/memories/session-01.md", "start_line": 52, "end_line": 53},
        )
        second = self.filesystem.execute(
            "view",
            {"path": "/memories/session-01.md", "start_line": 54, "end_line": 55},
        )
        root = self.filesystem.execute("view", {"path": "/memories"})
        ledger, one = self.append(self.ledger, first, 1, 1)
        ledger, two = self.append(ledger, second, 1, 2)
        ledger, root_observation = self.append(ledger, root, 1, 3)
        proven = ledger.prove_coverage(
            observation_ids=[two.observation_id, one.observation_id],
            path="/memories/session-01.md",
            line_start=52,
            line_end=55,
            current_round=2,
        )
        self.assertEqual(
            tuple(item.observation_id for item in proven),
            (one.observation_id, two.observation_id),
        )
        with self.assertRaisesRegex(EvidenceValidationError, "earlier provider round"):
            ledger.prove_coverage(
                observation_ids=[one.observation_id],
                path="/memories/session-01.md",
                line_start=52,
                line_end=53,
                current_round=1,
            )
        with self.assertRaisesRegex(EvidenceValidationError, "must cover part"):
            ledger.prove_coverage(
                observation_ids=[one.observation_id, root_observation.observation_id],
                path="/memories/session-01.md",
                line_start=52,
                line_end=53,
                current_round=2,
            )

        gap = self.filesystem.execute(
            "view",
            {"path": "/memories/session-01.md", "start_line": 57, "end_line": 57},
        )
        ledger, gap_observation = self.append(ledger, gap, 1, 4)
        with self.assertRaisesRegex(EvidenceValidationError, "unobserved gap"):
            ledger.prove_coverage(
                observation_ids=[two.observation_id, gap_observation.observation_id],
                path="/memories/session-01.md",
                line_start=54,
                line_end=57,
                current_round=2,
            )

    def test_toc_and_directory_view_never_prove_evidence_coverage(self):
        root = self.filesystem.execute("view", {"path": "/memories"})
        toc = self.filesystem.execute("toc", {"path": "/memories/session-01.md"})
        ledger, root_observation = self.append(self.ledger, root, 1, 1)
        ledger, toc_observation = self.append(ledger, toc, 1, 2)
        for observation in (root_observation, toc_observation):
            with self.subTest(observation=observation.observation_id):
                with self.assertRaisesRegex(
                    EvidenceValidationError, "must cover part|cannot expose"
                ):
                    ledger.prove_coverage(
                        observation_ids=[observation.observation_id],
                        path="/memories/session-01.md",
                        line_start=6,
                        line_end=6,
                        current_round=2,
                    )

    def test_global_fallback_requires_root_before_untruncated_whole_tree_grep(self):
        grep = self.filesystem.execute("grep", {"pattern": "never-present-xyz"})
        root = self.filesystem.execute("view", {"path": "/memories"})
        ledger, _ = self.append(self.ledger, grep, 1, 1)
        ledger, root_observation = self.append(ledger, root, 1, 2)
        self.assertIsNone(ledger.derive_global_fallback())
        ledger, grep_observation = self.append(ledger, grep, 2, 3)
        proof, completed_round = ledger.derive_global_fallback()
        self.assertEqual(
            proof.root_survey_observation_id, root_observation.observation_id
        )
        self.assertEqual(
            proof.whole_tree_grep_observation_id, grep_observation.observation_id
        )
        self.assertEqual(completed_round, 2)

    def test_take_note_builds_exact_host_verified_raw_turn(self):
        span = self.manifest.attribution_index.occurrences("[S1T13]")[0]
        result = self.filesystem.execute(
            "view",
            {
                "path": "/memories/" + span.path,
                "start_line": span.line_start,
                "end_line": span.line_end,
            },
        )
        ledger, observation = self.append(self.ledger, result, 1, 1)
        resolution = self.resolver.resolve(
            ledger=ledger,
            state=self.note_state,
            arguments={
                "observation_ids": [observation.observation_id],
                "path": "/memories/" + span.path,
                "line_start": span.line_start,
                "line_end": span.line_end,
            },
            current_round=2,
        )
        self.assertEqual(resolution.status, "accepted")
        self.assertTrue(resolution.new_evidence)
        self.assertEqual(len(resolution.state.evidence_items), 1)
        item = resolution.state.evidence_items[0]
        self.assertEqual(item.source_locators, ("[S1T13]",))
        self.assertEqual(item.dia_ids, ("D1:13",))
        self.assertEqual(item.observation_ids, (observation.observation_id,))
        self.assertEqual(item.retrieval_round, 2)
        self.assertEqual(item.query_terms, ())
        self.assertIsNone(item.rank)
        self.assertIsNone(item.score)
        self.assertEqual(
            resolution.state.to_budget_record().used,
            len(item.text.encode("utf-8")),
        )

    def test_take_note_rejects_model_text_partial_turn_and_extra_fields(self):
        span = self.manifest.attribution_index.occurrences("[S1T13]")[0]
        result = self.filesystem.execute(
            "view",
            {
                "path": "/memories/" + span.path,
                "start_line": span.line_start,
                "end_line": span.line_end,
            },
        )
        ledger, observation = self.append(self.ledger, result, 1, 1)
        base = {
            "observation_ids": [observation.observation_id],
            "path": "/memories/" + span.path,
            "line_start": span.line_start,
            "line_end": span.line_end,
        }
        for extra in ("text", "answer", "source_locators", "dia_ids"):
            with self.subTest(extra=extra):
                with self.assertRaises(R1OrchestrationError) as raised:
                    NoteSelector.from_mapping({**base, extra: "forged"})
                self.assertEqual(raised.exception.code, "invalid_arguments")
        with self.assertRaises(R1OrchestrationError) as raised:
            self.resolver.resolve(
                ledger=ledger,
                state=self.note_state,
                arguments={
                    **base,
                    "line_start": span.line_end,
                    "line_end": span.line_end,
                },
                current_round=2,
            )
        self.assertEqual(raised.exception.code, "invalid_evidence_selection")
        self.assertEqual(self.note_state.evidence_items, ())

    def test_duplicate_is_no_progress_and_expansion_merges_atomically(self):
        first = self.manifest.attribution_index.occurrences("[S1T13]")[0]
        second = self.manifest.attribution_index.occurrences("[S1T14]")[0]
        path = "/memories/" + first.path
        result = self.filesystem.execute(
            "view",
            {
                "path": path,
                "start_line": first.line_start,
                "end_line": second.line_end,
            },
        )
        ledger, observation = self.append(self.ledger, result, 1, 1)
        first_args = {
            "observation_ids": [observation.observation_id],
            "path": path,
            "line_start": first.line_start,
            "line_end": first.line_end,
        }
        accepted = self.resolver.resolve(
            ledger=ledger,
            state=self.note_state,
            arguments=first_args,
            current_round=2,
        )
        duplicate = self.resolver.resolve(
            ledger=ledger,
            state=accepted.state,
            arguments=first_args,
            current_round=3,
        )
        self.assertEqual(duplicate.status, "duplicate")
        self.assertFalse(duplicate.new_evidence)
        self.assertEqual(duplicate.state, accepted.state)

        expanded = self.resolver.resolve(
            ledger=ledger,
            state=accepted.state,
            arguments={
                **first_args,
                "line_end": second.line_end,
            },
            current_round=3,
        )
        self.assertEqual(expanded.status, "accepted")
        self.assertEqual(
            expanded.replaced_evidence_ids,
            (accepted.state.evidence_items[0].evidence_id,),
        )
        self.assertEqual(len(expanded.state.evidence_items), 1)
        merged = expanded.state.evidence_items[0]
        self.assertEqual(merged.source_locators, ("[S1T13]", "[S1T14]"))
        self.assertEqual(merged.selection_ordinal, 1)
        self.assertEqual(merged.retrieval_round, 3)
        self.assertEqual(expanded.state.next_selection_ordinal, 2)

    def test_budget_skip_keeps_old_state_and_never_truncates(self):
        span = self.manifest.attribution_index.occurrences("[S1T13]")[0]
        path = "/memories/" + span.path
        result = self.filesystem.execute(
            "view",
            {"path": path, "start_line": span.line_start, "end_line": span.line_end},
        )
        ledger, observation = self.append(self.ledger, result, 1, 1)
        tiny = EvidenceNoteState.start(
            question_sha256="a" * 64,
            snapshot=self.snapshot,
            budget_unit="bytes",
            budget_limit=1,
        )
        resolution = self.resolver.resolve(
            ledger=ledger,
            state=tiny,
            arguments={
                "observation_ids": [observation.observation_id],
                "path": path,
                "line_start": span.line_start,
                "line_end": span.line_end,
            },
            current_round=2,
        )
        self.assertEqual(resolution.status, "budget_skipped")
        self.assertFalse(resolution.new_evidence)
        self.assertEqual(resolution.state.evidence_items, ())
        self.assertEqual(resolution.state.next_selection_ordinal, 1)
        self.assertEqual(resolution.state.skipped_items, 1)
        self.assertFalse(resolution.state.to_budget_record().truncated)

    def test_store_drift_after_observation_is_fatal_not_a_selector_error(self):
        span = self.manifest.attribution_index.occurrences("[S1T13]")[0]
        path = "/memories/" + span.path
        result = self.filesystem.execute(
            "view",
            {"path": path, "start_line": span.line_start, "end_line": span.line_end},
        )
        ledger, observation = self.append(self.ledger, result, 1, 1)
        (self.store / span.path).write_text("tampered", encoding="utf-8")
        with self.assertRaises(EvidenceValidationError) as raised:
            self.resolver.resolve(
                ledger=ledger,
                state=self.note_state,
                arguments={
                    "observation_ids": [observation.observation_id],
                    "path": path,
                    "line_start": span.line_start,
                    "line_end": span.line_end,
                },
                current_round=2,
            )
        self.assertNotIsInstance(raised.exception, R1OrchestrationError)

    def test_finish_request_is_labels_only_and_host_reasons_are_forbidden(self):
        self.assertEqual(
            FinishSearchRequest.from_mapping(
                {"reason": "evidence_sufficient", "missing_aspects": []}
            ).missing_aspects,
            (),
        )
        invalid = [
            {"reason": "round_limit", "missing_aspects": ["support"]},
            {"reason": "protocol_failure", "missing_aspects": ["support"]},
            {"reason": "evidence_sufficient", "missing_aspects": ["date"]},
            {"reason": "evidence_budget_reached", "missing_aspects": []},
            {
                "reason": "not_found_after_global_fallback",
                "missing_aspects": ["x" * 65],
            },
            {
                "reason": "not_found_after_global_fallback",
                "missing_aspects": ["evidence at /memories/secret.md"],
            },
            {
                "reason": "not_found_after_global_fallback",
                "missing_aspects": ["claimed fact [S1T13]"],
            },
            {
                "reason": "not_found_after_global_fallback",
                "missing_aspects": ["line one\nline two"],
            },
            {
                "reason": "not_found_after_global_fallback",
                "missing_aspects": ["Alice became vegetarian in May 2026"],
            },
            {
                "reason": "not_found_after_global_fallback",
                "missing_aspects": ["date"],
                "answer": "forged",
            },
        ]
        for arguments in invalid:
            with self.subTest(arguments=arguments):
                with self.assertRaises(R1OrchestrationError):
                    FinishSearchRequest.from_mapping(arguments)

    def test_finish_sufficient_requires_evidence_and_closed_rounds(self):
        empty_rounds = ProviderRoundLedger.start(
            observations=self.ledger, notes=self.note_state
        ).close_round(
            round_number=1,
            resolutions=(),
            observations=self.ledger,
            resolver=self.resolver,
        )
        with self.assertRaisesRegex(R1OrchestrationError, "requires accepted"):
            self.finish_resolver.model_finish(
                arguments={"reason": "evidence_sufficient", "missing_aspects": []},
                observations=self.ledger,
                notes=self.note_state,
                rounds=empty_rounds,
            )

        rounds = ProviderRoundLedger.start(
            observations=self.ledger, notes=self.note_state
        )
        ledger, resolution = self.accepted_note()
        rounds = rounds.close_round(
            round_number=1,
            resolutions=(),
            observations=ledger,
            resolver=self.resolver,
        )
        with self.assertRaisesRegex(
            EvidenceValidationError, "note state|unclosed evidence"
        ):
            self.finish_resolver.model_finish(
                arguments={"reason": "evidence_sufficient", "missing_aspects": []},
                observations=ledger,
                notes=resolution.state,
                rounds=rounds,
            )
        rounds = rounds.close_round(
            round_number=2,
            resolutions=[resolution],
            observations=ledger,
            resolver=self.resolver,
        )
        rounds = rounds.close_round(
            round_number=3,
            resolutions=(),
            observations=ledger,
            resolver=self.resolver,
        )
        stop = self.finish_resolver.model_finish(
            arguments={"reason": "evidence_sufficient", "missing_aspects": []},
            observations=ledger,
            notes=resolution.state,
            rounds=rounds,
        )
        self.assertEqual(stop.reason, "evidence_sufficient")
        self.assertFalse(stop.hit_cap)

    def test_fallback_and_two_post_fallback_no_progress_rounds_are_proven(self):
        rounds = ProviderRoundLedger.start(
            observations=self.ledger, notes=self.note_state
        )
        root = self.filesystem.execute("view", {"path": "/memories"})
        grep = self.filesystem.execute("grep", {"pattern": "never-present-xyz"})
        ledger, _ = self.append(self.ledger, root, 1, 1)
        rounds = rounds.close_round(
            round_number=1,
            resolutions=(),
            observations=ledger,
            resolver=self.resolver,
        )
        with self.assertRaisesRegex(R1OrchestrationError, "fallback"):
            self.finish_resolver.model_finish(
                arguments={
                    "reason": "not_found_after_global_fallback",
                    "missing_aspects": ["event_or_fact"],
                },
                observations=ledger,
                notes=self.note_state,
                rounds=rounds,
            )
        ledger, _ = self.append(ledger, grep, 2, 2)
        rounds = rounds.close_round(
            round_number=2,
            resolutions=(),
            observations=ledger,
            resolver=self.resolver,
        )
        not_found = self.finish_resolver.model_finish(
            arguments={
                "reason": "not_found_after_global_fallback",
                "missing_aspects": ["event_or_fact"],
            },
            observations=ledger,
            notes=self.note_state,
            rounds=rounds,
        )
        self.assertTrue(not_found.global_fallback_done)
        self.assertEqual(rounds.fallback_round, 2)
        self.assertEqual(rounds.rounds_without_new_evidence, 0)

        rounds = rounds.close_round(
            round_number=3,
            resolutions=(),
            observations=ledger,
            resolver=self.resolver,
        )
        with self.assertRaisesRegex(R1OrchestrationError, "two completed"):
            self.finish_resolver.model_finish(
                arguments={
                    "reason": "no_progress_after_global_fallback",
                    "missing_aspects": ["event_or_fact"],
                },
                observations=ledger,
                notes=self.note_state,
                rounds=rounds,
            )
        rounds = rounds.close_round(
            round_number=4,
            resolutions=(),
            observations=ledger,
            resolver=self.resolver,
        )
        stopped = self.finish_resolver.model_finish(
            arguments={
                "reason": "no_progress_after_global_fallback",
                "missing_aspects": ["event_or_fact"],
            },
            observations=ledger,
            notes=self.note_state,
            rounds=rounds,
        )
        self.assertEqual(stopped.rounds_without_new_evidence, 2)

    def test_post_fallback_progress_resets_no_progress_counter(self):
        rounds = ProviderRoundLedger.start(
            observations=self.ledger, notes=self.note_state
        )
        root = self.filesystem.execute("view", {"path": "/memories"})
        grep = self.filesystem.execute("grep", {"pattern": "never-present-xyz"})
        ledger, _ = self.append(self.ledger, root, 1, 1)
        rounds = rounds.close_round(
            round_number=1,
            resolutions=(),
            observations=ledger,
            resolver=self.resolver,
        )
        ledger, _ = self.append(ledger, grep, 2, 2)
        rounds = rounds.close_round(
            round_number=2,
            resolutions=(),
            observations=ledger,
            resolver=self.resolver,
        )

        span = self.manifest.attribution_index.occurrences("[S1T13]")[0]
        path = "/memories/" + span.path
        viewed = self.filesystem.execute(
            "view",
            {"path": path, "start_line": span.line_start, "end_line": span.line_end},
        )
        ledger, observation = self.append(ledger, viewed, 3, 3)
        rounds = rounds.close_round(
            round_number=3,
            resolutions=(),
            observations=ledger,
            resolver=self.resolver,
        )
        self.assertEqual(rounds.rounds_without_new_evidence, 1)
        accepted = self.resolver.resolve(
            ledger=ledger,
            state=self.note_state,
            arguments={
                "observation_ids": [observation.observation_id],
                "path": path,
                "line_start": span.line_start,
                "line_end": span.line_end,
            },
            current_round=4,
        )
        rounds = rounds.close_round(
            round_number=4,
            resolutions=[accepted],
            observations=ledger,
            resolver=self.resolver,
        )
        self.assertEqual(rounds.rounds_without_new_evidence, 0)

        duplicate = self.resolver.resolve(
            ledger=ledger,
            state=accepted.state,
            arguments={
                "observation_ids": [observation.observation_id],
                "path": path,
                "line_start": span.line_start,
                "line_end": span.line_end,
            },
            current_round=5,
        )
        rounds = rounds.close_round(
            round_number=5,
            resolutions=[duplicate],
            observations=ledger,
            resolver=self.resolver,
        )
        self.assertEqual(rounds.rounds_without_new_evidence, 1)
        with self.assertRaisesRegex(R1OrchestrationError, "two completed"):
            self.finish_resolver.model_finish(
                arguments={
                    "reason": "no_progress_after_global_fallback",
                    "missing_aspects": ["corroborating_evidence"],
                },
                observations=ledger,
                notes=duplicate.state,
                rounds=rounds,
            )

    def test_round_ledger_rejects_unreported_or_cross_episode_state(self):
        rounds = ProviderRoundLedger.start(
            observations=self.ledger, notes=self.note_state
        )
        ledger, resolution = self.accepted_note()
        rounds = rounds.close_round(
            round_number=1,
            resolutions=(),
            observations=ledger,
            resolver=self.resolver,
        )
        with self.assertRaisesRegex(EvidenceValidationError, "note state"):
            self.finish_resolver.model_finish(
                arguments={"reason": "evidence_sufficient", "missing_aspects": []},
                observations=ledger,
                notes=resolution.state,
                rounds=rounds,
            )
        other = ObservationLedger.start(
            question_sha256="b" * 64,
            snapshot=self.snapshot,
        )
        with self.assertRaisesRegex(EvidenceValidationError, "different episodes"):
            rounds.close_round(
                round_number=2,
                resolutions=(),
                observations=other,
                resolver=self.resolver,
            )

    def test_round_close_replays_and_rejects_a_forged_budget_transition(self):
        forged_state = EvidenceNoteState(
            question_sha256="a" * 64,
            snapshot=self.snapshot,
            evidence_items=(),
            next_selection_ordinal=1,
            budget_unit="bytes",
            budget_limit=100_000,
            skipped_items=1,
        )
        selector = NoteSelector(
            observation_ids=("obs-9999",),
            path="/memories/session-01.md",
            line_start=1,
            line_end=1,
        )
        forged = TakeNoteResolution.create(
            question_sha256="a" * 64,
            observation_ledger_sha256=self.ledger.ledger_sha256,
            provider_round=1,
            status="budget_skipped",
            selector=selector,
            prior_state_sha256=self.note_state.state_sha256,
            state=forged_state,
            evidence_id=None,
            replaced_evidence_ids=(),
            contributing_observation_ids=("obs-9999",),
            new_evidence=False,
            budget_delta=1,
        )
        rounds = ProviderRoundLedger.start(
            observations=self.ledger,
            notes=self.note_state,
        )
        with self.assertRaises((EvidenceValidationError, R1OrchestrationError)):
            rounds.close_round(
                round_number=1,
                resolutions=[forged],
                observations=self.ledger,
                resolver=self.resolver,
            )

    def test_tampered_evidence_and_cross_question_resolution_replay_are_rejected(self):
        ledger, resolution = self.accepted_note()
        item = resolution.state.evidence_items[0]
        tampered_item = replace(item, source_map_sha256="b" * 64)
        with self.assertRaisesRegex(EvidenceValidationError, "identity differs"):
            EvidenceNoteState(
                question_sha256="a" * 64,
                snapshot=self.snapshot,
                evidence_items=(tampered_item,),
                next_selection_ordinal=2,
                budget_unit="bytes",
                budget_limit=100_000,
                skipped_items=0,
            )

        other_state = EvidenceNoteState.start(
            question_sha256="b" * 64,
            snapshot=self.snapshot,
            budget_unit="bytes",
            budget_limit=100_000,
        )
        other_resolver = TakeNoteResolver(
            root=self.store,
            catalog=self.catalog,
            verified_manifest=self.manifest,
            snapshot=self.snapshot,
            question_sha256="b" * 64,
        )
        other_ledger = ObservationLedger.start(
            question_sha256="b" * 64,
            snapshot=self.snapshot,
        )
        rounds = ProviderRoundLedger.start(
            observations=other_ledger,
            notes=other_state,
        )
        other_ledger, _ = other_ledger.execute_and_append(
            filesystem=self.filesystem,
            tool_name=ledger.observations[0].result.tool_name,
            arguments=ledger.observations[0].result.canonical_args,
            provider_round=1,
            action_ordinal=1,
        )
        rounds = rounds.close_round(
            round_number=1,
            resolutions=(),
            observations=other_ledger,
            resolver=other_resolver,
        )
        with self.assertRaisesRegex(
            EvidenceValidationError, "another question|trusted replay"
        ):
            rounds.close_round(
                round_number=2,
                resolutions=[resolution],
                observations=other_ledger,
                resolver=other_resolver,
            )

    def test_multiple_take_notes_in_one_round_form_one_verified_state_chain(self):
        rounds = ProviderRoundLedger.start(
            observations=self.ledger,
            notes=self.note_state,
        )
        first_span = self.manifest.attribution_index.occurrences("[S1T13]")[0]
        second_span = self.manifest.attribution_index.occurrences("[S1T15]")[0]
        path = "/memories/" + first_span.path
        result = self.filesystem.execute(
            "view",
            {
                "path": path,
                "start_line": first_span.line_start,
                "end_line": second_span.line_end,
            },
        )
        ledger, observation = self.append(self.ledger, result, 1, 1)
        rounds = rounds.close_round(
            round_number=1,
            resolutions=(),
            observations=ledger,
            resolver=self.resolver,
        )
        first = self.resolver.resolve(
            ledger=ledger,
            state=self.note_state,
            arguments={
                "observation_ids": [observation.observation_id],
                "path": path,
                "line_start": first_span.line_start,
                "line_end": first_span.line_end,
            },
            current_round=2,
        )
        second = self.resolver.resolve(
            ledger=ledger,
            state=first.state,
            arguments={
                "observation_ids": [observation.observation_id],
                "path": path,
                "line_start": second_span.line_start,
                "line_end": second_span.line_end,
            },
            current_round=2,
        )
        rounds = rounds.close_round(
            round_number=2,
            resolutions=[first, second],
            observations=ledger,
            resolver=self.resolver,
        )
        self.assertEqual(rounds.note_state, second.state)
        self.assertEqual(len(rounds.note_state.evidence_items), 2)
        self.assertEqual(
            rounds.records[-1].newly_accepted_evidence_ids,
            (first.evidence_id, second.evidence_id),
        )

    def test_direct_constructor_cannot_seed_initial_evidence(self):
        _ledger, resolution = self.accepted_note()
        base = ProviderRoundLedger.start(
            observations=self.ledger,
            notes=self.note_state,
        )
        with self.assertRaisesRegex(EvidenceValidationError, "empty note state"):
            ProviderRoundLedger(
                episode_id=base.episode_id,
                episode_key_id=base.episode_key_id,
                question_sha256=base.question_sha256,
                store_id=base.store_id,
                source_kind=base.source_kind,
                store_snapshot_sha256=base.store_snapshot_sha256,
                initial_note_state=resolution.state,
                note_state=resolution.state,
                initial_note_state_sha256=resolution.state.state_sha256,
                note_state_sha256=resolution.state.state_sha256,
                records=(),
            )

    def test_s1_round_limit_is_a_hard_construction_boundary(self):
        rounds = ProviderRoundLedger.start(
            observations=self.ledger,
            notes=self.note_state,
        )
        for round_number in range(1, 21):
            rounds = rounds.close_round(
                round_number=round_number,
                resolutions=(),
                observations=self.ledger,
                resolver=self.resolver,
            )
        stop = self.finish_resolver.host_round_limit(
            observations=self.ledger,
            notes=self.note_state,
            rounds=rounds,
        )
        self.assertTrue(stop.hit_cap)
        with self.assertRaisesRegex(EvidenceValidationError, "frozen store limit"):
            rounds.close_round(
                round_number=21,
                resolutions=(),
                observations=self.ledger,
                resolver=self.resolver,
            )
        with self.assertRaisesRegex(EvidenceValidationError, "frozen store limit"):
            self.ledger.execute_and_append(
                filesystem=self.filesystem,
                tool_name="view",
                arguments={"path": "/memories"},
                provider_round=21,
                action_ordinal=1,
            )
        last = rounds.records[-1]
        forged_body = {**last._body(), "round_number": 21}
        forged_record = replace(
            last,
            round_number=21,
            round_sha256=sha256_bytes(canonical_json_bytes(forged_body)),
        )
        with self.assertRaisesRegex(EvidenceValidationError, "exceeds frozen limit"):
            replace(rounds, records=(*rounds.records, forged_record))

    def test_episode_receipt_blocks_cross_question_and_cross_run_rebinding(self):
        result = self.filesystem.execute("view", {"path": "/memories"})
        first, observation = self.append(self.ledger, result, 1, 1)
        for question_sha256 in ("a" * 64, "b" * 64):
            other = ObservationLedger.start(
                question_sha256=question_sha256,
                snapshot=self.snapshot,
            )
            self.assertNotEqual(first.episode_id, other.episode_id)
            with self.assertRaisesRegex(EvidenceValidationError, "identity differs"):
                replace(other, observations=(observation,))
            other, rebound = other.execute_and_append(
                filesystem=self.filesystem,
                tool_name="view",
                arguments={"path": "/memories"},
                provider_round=1,
                action_ordinal=1,
            )
            self.assertEqual(rebound.result, observation.result)
            self.assertNotEqual(
                rebound._execution_receipt.receipt_mac,
                observation._execution_receipt.receipt_mac,
            )

    def test_receipt_hmac_tampering_and_unordered_resolution_ids_fail_closed(self):
        result = self.filesystem.execute("view", {"path": "/memories"})
        ledger, observation = self.append(self.ledger, result, 1, 1)
        receipt = observation._execution_receipt
        original_mac = receipt.receipt_mac
        try:
            receipt.receipt_mac = "0" * 64
            with self.assertRaisesRegex(EvidenceValidationError, "HMAC"):
                ledger.validate_authenticated(self.filesystem)
        finally:
            receipt.receipt_mac = original_mac
        serialized = json.dumps(ledger.to_dict(), sort_keys=True)
        self.assertIn("receipt_mac", serialized)
        self.assertNotIn("_secret", serialized)

        _observations, accepted = self.accepted_note()
        with self.assertRaisesRegex(EvidenceValidationError, "ordered array"):
            TakeNoteResolution.create(
                question_sha256=accepted.question_sha256,
                observation_ledger_sha256=accepted.observation_ledger_sha256,
                provider_round=accepted.provider_round,
                status=accepted.status,
                selector=accepted.selector,
                prior_state_sha256=accepted.prior_state_sha256,
                state=accepted.state,
                evidence_id=accepted.evidence_id,
                replaced_evidence_ids=set(),
                contributing_observation_ids=accepted.contributing_observation_ids,
                new_evidence=accepted.new_evidence,
                budget_delta=accepted.budget_delta,
            )

    def test_round_progress_cannot_be_forged_by_tampering_accepted_ids(self):
        rounds = ProviderRoundLedger.start(
            observations=self.ledger,
            notes=self.note_state,
        )
        ledger, accepted = self.accepted_note()
        rounds = rounds.close_round(
            round_number=1,
            resolutions=(),
            observations=ledger,
            resolver=self.resolver,
        )
        rounds = rounds.close_round(
            round_number=2,
            resolutions=(accepted,),
            observations=ledger,
            resolver=self.resolver,
        )
        with self.assertRaisesRegex(
            EvidenceValidationError, "differ from authenticated resolutions"
        ):
            replace(rounds.records[-1], newly_accepted_evidence_ids=())

    def test_real_s2_nested_store_completes_the_same_orchestration_chain(self):
        s2_root = Path(self.temporary.name) / "s2-foldered"
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
        question_sha256 = "d" * 64
        ledger = ObservationLedger.start(
            question_sha256=question_sha256,
            snapshot=snapshot,
        )
        notes = EvidenceNoteState.start(
            question_sha256=question_sha256,
            snapshot=snapshot,
            budget_unit="bytes",
            budget_limit=100_000,
        )
        resolver = TakeNoteResolver(
            root=s2_root,
            catalog=self.catalog,
            verified_manifest=manifest,
            snapshot=snapshot,
            question_sha256=question_sha256,
        )
        finish = FinishSearchResolver(
            root=s2_root,
            catalog=self.catalog,
            verified_manifest=manifest,
            snapshot=snapshot,
            question_sha256=question_sha256,
        )
        rounds = ProviderRoundLedger.start(observations=ledger, notes=notes)
        span = manifest.attribution_index.occurrences("[S1T13]")[0]
        path = "/memories/" + span.path
        result = filesystem.execute(
            "view",
            {"path": path, "start_line": span.line_start, "end_line": span.line_end},
        )
        ledger, observation = ledger.execute_and_append(
            filesystem=filesystem,
            tool_name=result.tool_name,
            arguments=result.canonical_args,
            provider_round=1,
            action_ordinal=1,
        )
        rounds = rounds.close_round(
            round_number=1,
            resolutions=(),
            observations=ledger,
            resolver=resolver,
        )
        resolution = resolver.resolve(
            ledger=ledger,
            state=notes,
            arguments={
                "observation_ids": [observation.observation_id],
                "path": path,
                "line_start": span.line_start,
                "line_end": span.line_end,
            },
            current_round=2,
        )
        rounds = rounds.close_round(
            round_number=2,
            resolutions=[resolution],
            observations=ledger,
            resolver=resolver,
        )
        stop = finish.model_finish(
            arguments={"reason": "evidence_sufficient", "missing_aspects": []},
            observations=ledger,
            notes=resolution.state,
            rounds=rounds,
        )
        self.assertEqual(path, "/memories/travel-and-outdoors/session-01.md")
        self.assertEqual(
            resolution.state.evidence_items[0].source_locators,
            ("[S1T13]",),
        )
        self.assertEqual(stop.reason, "evidence_sufficient")
        self.assertEqual(finish.round_limit, 20)

    def test_budget_stop_and_host_round_limit_are_host_verified(self):
        tiny = EvidenceNoteState.start(
            question_sha256="a" * 64,
            snapshot=self.snapshot,
            budget_unit="bytes",
            budget_limit=1,
        )
        rounds = ProviderRoundLedger.start(observations=self.ledger, notes=tiny)
        span = self.manifest.attribution_index.occurrences("[S1T13]")[0]
        path = "/memories/" + span.path
        result = self.filesystem.execute(
            "view",
            {"path": path, "start_line": span.line_start, "end_line": span.line_end},
        )
        ledger, observation = self.append(self.ledger, result, 1, 1)
        rounds = rounds.close_round(
            round_number=1,
            resolutions=(),
            observations=ledger,
            resolver=self.resolver,
        )
        skipped_resolution = self.resolver.resolve(
            ledger=ledger,
            state=tiny,
            arguments={
                "observation_ids": [observation.observation_id],
                "path": path,
                "line_start": span.line_start,
                "line_end": span.line_end,
            },
            current_round=2,
        )
        skipped = skipped_resolution.state
        rounds = rounds.close_round(
            round_number=2,
            resolutions=[skipped_resolution],
            observations=ledger,
            resolver=self.resolver,
        )
        budget_stop = self.finish_resolver.model_finish(
            arguments={
                "reason": "evidence_budget_reached",
                "missing_aspects": ["corroborating_evidence"],
            },
            observations=ledger,
            notes=skipped,
            rounds=rounds,
        )
        self.assertEqual(budget_stop.reason, "evidence_budget_reached")
        with self.assertRaisesRegex(EvidenceValidationError, "exact configured cap"):
            self.finish_resolver.host_round_limit(
                observations=ledger,
                notes=skipped,
                rounds=rounds,
            )
        self.assertEqual(self.finish_resolver.round_limit, 20)
        for round_number in range(3, 21):
            rounds = rounds.close_round(
                round_number=round_number,
                resolutions=(),
                observations=ledger,
                resolver=self.resolver,
            )
        capped = self.finish_resolver.host_round_limit(
            observations=ledger,
            notes=skipped,
            rounds=rounds,
        )
        self.assertEqual(capped.reason, "round_limit")
        self.assertTrue(capped.hit_cap)


class CuratedOrchestrationTest(unittest.TestCase):
    """Exercise the same R1 host boundary on a formal S3-shaped fixture."""

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
        self.store = self.temp_root / "s3-curated"
        self.store.mkdir()
        memory = (
            "---\nname: notes\ndescription: Curated fixture.\n---\n\n"
            "# Combined\n\n"
            "- Calvin planned to visit Japan [S1T13].\n"
            "- Dave later encouraged him [S2T2].\n"
            "- 他还想体验当地音乐 [S1T14].\n"
        )
        memory_path = self.store / "notes.md"
        memory_path.write_text(memory, encoding="utf-8")
        source_index = {
            "[S1T13]": [{"file": "notes.md", "line": 8}],
            "[S2T2]": [{"file": "notes.md", "line": 9}],
            "[S1T14]": [{"file": "notes.md", "line": 10}],
        }
        payload = memory_path.read_bytes()
        file_sha256 = sha256_bytes(payload)
        store_sha256 = sha256_bytes(canonical_json_bytes({"notes.md": file_sha256}))
        trace = self.temp_root / "s3-management"
        trace.mkdir()
        trace_file = trace / "index.json"
        trace_file.write_text('{"status":"completed"}\n', encoding="utf-8")
        trace_sha256 = sha256_bytes(
            canonical_json_bytes({"index.json": sha256_bytes(trace_file.read_bytes())})
        )
        run_id = "20261008T000000000000Z-12345678"
        finished_at = "2026-10-08T00:00:00Z"
        manifest = {
            "schema_version": 1,
            "artifact_id": "locomo/conv-50/s3-curated/v1",
            "build": {
                "run_id": run_id,
                "mode": "formal",
                "finished_at": finished_at,
                "chunks_completed": 85,
            },
            "counts": {"files": 1, "bytes": len(payload)},
            "directories": [],
            "files": {
                "notes.md": {
                    "bytes": len(payload),
                    "cross_references": [],
                    "headings": 1,
                    "lines": len(memory.splitlines()),
                    "locator_mentions": 3,
                    "sha256": file_sha256,
                    "section_cross_references": [],
                    "unique_locators": ["[S1T13]", "[S1T14]", "[S2T2]"],
                }
            },
            "source_index": source_index,
            "source": {
                "stream_manifest_sha256": "1" * 64,
                "prompt_contract_sha256": "2" * 64,
                "runtime_contract_sha256": "3" * 64,
            },
            "store": {
                "directory_name": "s3-curated",
                "tree_sha256": store_sha256,
            },
            "trace": {
                "directory_name": "s3-management",
                "tree_sha256": trace_sha256,
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
            "store_tree_sha256": store_sha256,
            "trace_tree_sha256": trace_sha256,
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
        self.manifest = VerifiedStoreManifest.load(
            root=self.store,
            store_id="s3",
            catalog=self.catalog,
            manifest_path=manifest_path,
            expected_manifest_sha256=sha256_bytes(manifest_payload),
            commit_marker_path=marker_path,
            expected_commit_marker_sha256=sha256_bytes(marker_payload),
            trace_path=trace,
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
        self.ledger = ObservationLedger.start(
            question_sha256="c" * 64,
            snapshot=self.snapshot,
        )
        self.resolver = TakeNoteResolver(
            root=self.store,
            catalog=self.catalog,
            verified_manifest=self.manifest,
            snapshot=self.snapshot,
            question_sha256="c" * 64,
        )
        self.finish_resolver = FinishSearchResolver(
            root=self.store,
            catalog=self.catalog,
            verified_manifest=self.manifest,
            snapshot=self.snapshot,
            question_sha256="c" * 64,
        )
        result = self.filesystem.execute(
            "view",
            {"path": "/memories/notes.md", "start_line": 8, "end_line": 10},
        )
        self.ledger, self.observation = self.ledger.execute_and_append(
            filesystem=self.filesystem,
            tool_name=result.tool_name,
            arguments=result.canonical_args,
            provider_round=1,
            action_ordinal=1,
        )

    def tearDown(self):
        self.temporary.cleanup()

    def resolve(self, state, line_start, line_end, current_round):
        return self.resolver.resolve(
            ledger=self.ledger,
            state=state,
            arguments={
                "observation_ids": [self.observation.observation_id],
                "path": "/memories/notes.md",
                "line_start": line_start,
                "line_end": line_end,
            },
            current_round=current_round,
        )

    def test_s3_curated_bridge_merge_is_deterministic(self):
        self.assertEqual(self.finish_resolver.round_limit, 40)
        state = EvidenceNoteState.start(
            question_sha256="c" * 64,
            snapshot=self.snapshot,
            budget_unit="bytes",
            budget_limit=10_000,
        )
        first = self.resolve(state, 8, 8, 2)
        third = self.resolve(first.state, 10, 10, 2)
        self.assertEqual(len(third.state.evidence_items), 2)
        bridge = self.resolve(third.state, 9, 9, 3)
        self.assertEqual(bridge.status, "accepted")
        self.assertEqual(len(bridge.replaced_evidence_ids), 2)
        self.assertEqual(len(bridge.state.evidence_items), 1)
        merged = bridge.state.evidence_items[0]
        self.assertEqual((merged.line_start, merged.line_end), (8, 10))
        self.assertEqual(
            merged.source_locators,
            ("[S1T13]", "[S2T2]", "[S1T14]"),
        )
        self.assertEqual(merged.selection_ordinal, 1)

    def test_s3_unicode_bytes_and_characters_budgets_are_distinct(self):
        probe = EvidenceNoteState.start(
            question_sha256="c" * 64,
            snapshot=self.snapshot,
            budget_unit="characters",
            budget_limit=10_000,
        )
        item = self.resolve(probe, 10, 10, 2).state.evidence_items[0]
        character_cost = len(item.text)
        byte_cost = len(item.text.encode("utf-8"))
        self.assertGreater(byte_cost, character_cost)

        characters = EvidenceNoteState.start(
            question_sha256="c" * 64,
            snapshot=self.snapshot,
            budget_unit="characters",
            budget_limit=character_cost,
        )
        accepted = self.resolve(characters, 10, 10, 2)
        self.assertEqual(accepted.status, "accepted")
        byte_limited = EvidenceNoteState.start(
            question_sha256="c" * 64,
            snapshot=self.snapshot,
            budget_unit="bytes",
            budget_limit=character_cost,
        )
        skipped = self.resolve(byte_limited, 10, 10, 2)
        self.assertEqual(skipped.status, "budget_skipped")
        self.assertEqual(skipped.state.evidence_items, ())

    def test_s3_round_limit_is_exactly_forty(self):
        empty = ObservationLedger.start(
            question_sha256="c" * 64,
            snapshot=self.snapshot,
        )
        notes = EvidenceNoteState.start(
            question_sha256="c" * 64,
            snapshot=self.snapshot,
            budget_unit="bytes",
            budget_limit=10_000,
        )
        rounds = ProviderRoundLedger.start(observations=empty, notes=notes)
        for round_number in range(1, 41):
            rounds = rounds.close_round(
                round_number=round_number,
                resolutions=(),
                observations=empty,
                resolver=self.resolver,
            )
        self.assertTrue(
            self.finish_resolver.host_round_limit(
                observations=empty,
                notes=notes,
                rounds=rounds,
            ).hit_cap
        )
        with self.assertRaisesRegex(EvidenceValidationError, "frozen store limit"):
            rounds.close_round(
                round_number=41,
                resolutions=(),
                observations=empty,
                resolver=self.resolver,
            )


if __name__ == "__main__":
    unittest.main()
