from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from fs_memory_lab.evidence import EvidenceValidationError
from fs_memory_lab.model2_validation import (
    MODEL2_OFFLINE_REPORT_NAME,
    MODEL2_PILOT_MANIFEST_NAME,
    MODEL2_REQUESTED_MODEL_ALIAS,
    PILOT_RECORD_COUNT,
    RECORDS_PER_BATCH,
    SUITE_BATCH_COUNT,
    SUITE_RECORD_COUNT,
    build_offline_dry_run_report,
    evaluate_model2_pilot_gate,
    expected_suite_layout,
    prepare_model2_pilot,
    run_prepared_suite_dry_run,
)
from fs_memory_lab.formal_v2_model2 import prepare_suite
from fs_memory_lab.model2_preflight import (
    MODEL2_MODELS_ENDPOINT,
    MODEL2_ROLE_ORDER,
    ModelCatalogCheck,
    Model2SmokeReport,
    ModelResponseReceipt,
    RoleSmokeResult,
)
from fs_memory_lab.run_records import CONDITION_IDS, verify_run_store


ROOT = Path(__file__).resolve().parents[1]
SERVED_MODEL = "deepseek-v4.1-flash"
FAKE_COMMIT = "7" * 40


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _passing_metric_shape() -> dict[str, object]:
    return {
        "planned_records": 42,
        "completed_records": 42,
        "completed_by_condition": {condition: 6 for condition in CONDITION_IDS},
        "active_failed_keys": 0,
        "next_key": None,
        "requested_model_aliases": [MODEL2_REQUESTED_MODEL_ALIAS],
        "served_models": [SERVED_MODEL],
        "retrieval_attempts": 36,
        "retrieval_system_failure_attempts": 0,
        "answer_attempts": 42,
        "answer_system_failure_attempts": 0,
        "citations_valid": True,
        "stores_unchanged": True,
        "e2_e4_fixed_query_top5_backend_invariant": True,
        "budget_skipped_episode_count": 0,
        "retrieval_episode_count": 36,
        "empty_evidence_bundles": 0,
        "token_safety_fuse_hits": 0,
        "max_retrieval_episode_total_tokens": 999_999,
        "r1_round_cap_by_condition": {"E1": 20, "E3": 20, "E5": 40},
        "r2_action_cap": 4,
        "r3_action_cap": 4,
        "cap_metrics_complete": True,
        "compaction_metrics_complete": True,
        "answer_repair_metrics_complete": True,
        "truncated_evidence_items": 0,
        "evidence_bundles_with_wrong_budget": 0,
        "e7_records": 6,
        "e7_retrieval_calls": 0,
        "e7_source_model_mismatches": 0,
        "e7_per_source_budget_limit": 16_000,
        "e7_total_budget_limit": 32_000,
        "e7_cost_rule_verified": True,
        "semantic_gold_loaded": False,
        "judge_calls": 0,
    }


def _write_synthetic_valid_smoke(path: Path) -> None:
    roles = []
    for component in MODEL2_ROLE_ORDER:
        def receipt(call_index: int) -> ModelResponseReceipt:
            return ModelResponseReceipt(
                component=component,
                call_index=call_index,
                requested_alias=MODEL2_REQUESTED_MODEL_ALIAS,
                served_model=SERVED_MODEL,
                usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
                finish_reason="stop",
                response_id=None,
                system_fingerprint=None,
            )

        checks = {
            "r1": {
                "native_tool_calls": True,
                "tool_choice_auto_profile": True,
                "tool_call_count": 1,
                "single_tool_mode": "filesystem",
                "json_arguments": True,
                "take_note_wire_compatibility": True,
                "finish_search_wire_compatibility": True,
            },
            "r1_compaction": {
                "plain_text": True,
                "no_tool_calls": True,
                "finish_stop": True,
            },
            "r2": {
                "textual_react": True,
                "no_native_tool_calls": True,
                "action": "finish_search",
                "action_input_json": True,
                "synthetic_stop_turn": True,
            },
            "r3": {
                "textual_react": True,
                "no_native_tool_calls": True,
                "action": "finish_search",
                "action_input_json": True,
                "synthetic_stop_turn": True,
            },
            "answerer": {
                "exact_json": True,
                "no_tool_calls": True,
                "citation_subset": True,
                "citation_count": 1,
            },
        }[component]
        roles.append(
            RoleSmokeResult(
                component=component,
                request_sha256="a" * 64,
                system_prompt_sha256="b" * 64,
                receipt=receipt(1),
                checks=checks,
                additional_receipts=(receipt(2), receipt(3)) if component == "r1" else (),
                additional_request_sha256s=("c" * 64, "d" * 64)
                if component == "r1"
                else (),
            )
        )
    report = Model2SmokeReport(
        requested_alias=MODEL2_REQUESTED_MODEL_ALIAS,
        expected_served_model=SERVED_MODEL,
        roles=tuple(roles),
    )
    path.write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_synthetic_models_check(path: Path) -> None:
    report = ModelCatalogCheck(
        requested_alias=MODEL2_REQUESTED_MODEL_ALIAS,
        endpoint=MODEL2_MODELS_ENDPOINT,
        advertised_model_ids=(MODEL2_REQUESTED_MODEL_ALIAS,),
        alias_context_limits={"context_length": 1_048_576},
    )
    path.write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )


class Model2ValidationTests(unittest.TestCase):
    def test_expected_suite_is_420_unique_keys_in_twelve_35_record_batches(self):
        layout = expected_suite_layout(ROOT)
        keys = [
            (item["condition_id"], item["question_id"])
            for item in layout["execution_order"]
        ]
        self.assertEqual(len(keys), SUITE_RECORD_COUNT)
        self.assertEqual(len(set(keys)), SUITE_RECORD_COUNT)
        self.assertEqual(len(layout["main_question_ids"]), 40)
        self.assertEqual(len(layout["extension_question_ids"]), 20)
        self.assertEqual(len(layout["batches"]), SUITE_BATCH_COUNT)
        self.assertTrue(
            all(batch["record_count"] == RECORDS_PER_BATCH for batch in layout["batches"])
        )
        self.assertEqual(layout["batches"][8]["suite_batch_id"], "B09")
        self.assertEqual(layout["batches"][8]["child_batch_id"], "B01")
        # Global position 41 must continue the six-way rotation, not restart E1.
        self.assertEqual(keys[40 * 7][0], "E5")

    def test_offline_report_covers_frozen_contract_without_api_or_answers(self):
        report = build_offline_dry_run_report(
            repo_root=ROOT,
            requested_model_alias=MODEL2_REQUESTED_MODEL_ALIAS,
            required_served_model=SERVED_MODEL,
            preflight_report_sha256="a" * 64,
        )
        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["planned_records"], 420)
        self.assertEqual(report["condition_counts"], {f"E{i}": 60 for i in range(1, 8)})
        self.assertTrue(report["checks"]["e7_no_retrieval_contract"])
        self.assertTrue(report["checks"]["whole_item_budget_schema_enforced"])
        self.assertTrue(report["checks"]["checkpoint_resume_without_duplicates"])
        self.assertTrue(report["checks"]["api_provider_not_constructed"])
        self.assertTrue(report["checks"]["formal_answers_not_generated"])
        self.assertEqual(len(report["resume_projection_checks"]), 13)

    def test_offline_report_rejects_unapproved_alias(self):
        with self.assertRaises(EvidenceValidationError):
            build_offline_dry_run_report(
                repo_root=ROOT,
                requested_model_alias="coding",
                required_served_model=SERVED_MODEL,
                preflight_report_sha256="a" * 64,
            )

    def test_prepared_suite_dry_run_verifies_manifest_children_and_preflight(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            folder = Path(temporary)
            preflight = folder / "role-smoke.json"
            _write_synthetic_valid_smoke(preflight)
            models_check = folder / "models-check.json"
            _write_synthetic_models_check(models_check)
            output = folder / "runs"
            suite_id = "model2-suite-dry-run-test"
            prepare_suite(
                repo_root=ROOT,
                output_root=output,
                suite_id=suite_id,
                implementation_commit=FAKE_COMMIT,
                requested_model_alias=MODEL2_REQUESTED_MODEL_ALIAS,
                required_served_model=SERVED_MODEL,
                models_check_report_path=models_check,
                role_smoke_report_path=preflight,
            )
            report = run_prepared_suite_dry_run(
                repo_root=ROOT,
                output_root=output,
                suite_id=suite_id,
            )
            self.assertEqual(report["status"], "passed")
            self.assertEqual(report["planned_records"], 420)
            self.assertTrue(report["checks"]["preflight_role_smokes_verified"])
            self.assertEqual(
                report["deployment"]["context_limit_tokens"], 1_048_576
            )
            self.assertEqual(
                report["deployment"]["models_check_report_sha256"],
                json.loads(
                    (output / suite_id / "suite-manifest.json").read_text(
                        encoding="utf-8"
                    )
                )["preflight_artifacts"]["models_check"]["sha256"],
            )
            self.assertTrue(report["checks"]["suite_schedule_matches_global_420_order"])
            self.assertTrue(report["checks"]["empty_child_checkpoints_exact"])
            self.assertEqual(report["api_boundary"], {"provider_constructed": False, "calls": 0})
            self.assertEqual(report["answer_boundary"], {"records_generated": 0})
            self.assertTrue((output / suite_id / MODEL2_OFFLINE_REPORT_NAME).is_file())

    def test_prepare_pilot_only_writes_empty_plan_and_bound_manifest(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            folder = Path(temporary)
            preflight = folder / "preflight.json"
            preflight.write_text(
                json.dumps({"requested_model": "x-test-2", "served_model": SERVED_MODEL}),
                encoding="utf-8",
            )
            output = folder / "runs"
            path = prepare_model2_pilot(
                repo_root=ROOT,
                output_root=output,
                run_id="model2-dev6-pilot-test",
                requested_model_alias=MODEL2_REQUESTED_MODEL_ALIAS,
                required_served_model=SERVED_MODEL,
                preflight_report_path=preflight,
                preflight_report_sha256=_sha256(preflight),
            )
            self.assertEqual(path.name, MODEL2_PILOT_MANIFEST_NAME)
            manifest = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["status"], "prepared-not-started")
            self.assertEqual(manifest["planned_records"], PILOT_RECORD_COUNT)
            self.assertEqual(manifest["deployment"]["requested_model_alias"], "x-test-2")
            self.assertEqual(manifest["deployment"]["required_served_model"], SERVED_MODEL)
            self.assertEqual(manifest["api_calls_made_by_prepare"], 0)
            self.assertEqual(manifest["answers_generated_by_prepare"], 0)
            store, checkpoint = verify_run_store(output, "model2-dev6-pilot-test")
            self.assertEqual(checkpoint["planned"], 42)
            self.assertEqual(checkpoint["completed"], 0)
            self.assertEqual(len(store.pending_keys()), 42)

            # Even operationally perfect supplied metrics cannot pass while the
            # verified append-only store itself remains empty.
            gate = evaluate_model2_pilot_gate(
                output_root=output,
                run_id="model2-dev6-pilot-test",
                metrics=_passing_metric_shape(),
            )
            self.assertEqual(gate["status"], "failed")
            self.assertFalse(gate["checks"]["records_42_complete"])

    def test_pilot_preparation_rejects_tampered_preflight_hash(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            folder = Path(temporary)
            preflight = folder / "preflight.json"
            preflight.write_text("{}\n", encoding="utf-8")
            with self.assertRaises(EvidenceValidationError):
                prepare_model2_pilot(
                    repo_root=ROOT,
                    output_root=folder / "runs",
                    run_id="model2-dev6-pilot-bad-preflight",
                    required_served_model=SERVED_MODEL,
                    preflight_report_path=preflight,
                    preflight_report_sha256="0" * 64,
                )


if __name__ == "__main__":
    unittest.main()
