from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from fs_memory_lab.dev_retrieval import (
    DEV_CONDITIONS,
    _has_empty_budget_outcome,
    authorize_empty_content_hotfix_retry,
    authorize_provider_response_retry,
    load_hotfix_recovery_policy,
    load_manifest,
    prepare_dev_run,
    write_status,
)
from fs_memory_lab.evidence import EvidenceValidationError
from fs_memory_lab.r1_inputs import load_question_inputs, load_r1_store
from fs_memory_lab.r1_runner import execute_r1_question
from fs_memory_lab.r2_runner import execute_r2_question
from fs_memory_lab.run_records import run_plan_from_mapping


ROOT = Path(__file__).resolve().parents[1]


def tool_response(call_id, name, arguments):
    return {
        "message": {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": call_id,
                    "type": "function",
                    "function": {"name": name, "arguments": json.dumps(arguments)},
                }
            ],
        },
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        "finish_reason": "tool_calls",
        "served_model": "fake-served",
    }


class Provider:
    api_style = "portable"
    model = "coding"

    def __init__(self, responses):
        self.responses = list(responses)

    def complete(self, _messages, _tools, _config):
        return self.responses.pop(0)


class DevRetrievalTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(dir="/private/tmp")
        self.output = Path(self.temporary.name) / "stage3"
        self.run_id = "dev6-test"

    def tearDown(self):
        self.temporary.cleanup()

    def prepare(self):
        return prepare_dev_run(
            repo_root=ROOT,
            output_root=self.output,
            run_id=self.run_id,
            budget_limit=6000,
            requested_model="coding",
        )

    def test_empty_budget_gate_uses_packing_outcome_not_controller_stop_reason(self):
        self.assertTrue(
            _has_empty_budget_outcome(
                [
                    {
                        "empty_evidence": True,
                        "budget_skipped_items": 1,
                        "stop_reason": "round_limit",
                    }
                ]
            )
        )
        self.assertFalse(
            _has_empty_budget_outcome(
                [
                    {
                        "empty_evidence": True,
                        "budget_skipped_items": 0,
                        "stop_reason": "no_relevant_evidence",
                    }
                ]
            )
        )

    def test_prepare_freezes_rotated_36_episode_plan(self):
        path = self.prepare()
        manifest = load_manifest(path)
        plan = run_plan_from_mapping(manifest["plan"])
        self.assertEqual(plan.condition_ids, DEV_CONDITIONS)
        self.assertEqual(len(plan.execution_order), 36)
        self.assertEqual(
            [key.condition_id for key in plan.execution_order[:6]], list(DEV_CONDITIONS)
        )
        self.assertEqual(
            [key.condition_id for key in plan.execution_order[6:12]],
            ["E2", "E3", "E4", "E5", "E6", "E1"],
        )
        state = json.loads((path.parent / "status.json").read_text())
        self.assertEqual(state["verified_episode_count"], 0)
        self.assertEqual(state["pending_episode_count"], 36)

    def test_verified_existing_episode_is_a_resume_checkpoint(self):
        self.prepare()
        question = load_question_inputs(ROOT, "dev-6")[0]
        store = load_r1_store(ROOT, "s1")
        span = store.verified_manifest.attribution_index.occurrences("[S1T13]")[0]
        path = "/memories/" + span.path
        provider = Provider(
            [
                tool_response("read", "view", {"path": path, "start_line": span.line_start, "end_line": span.line_end}),
                tool_response("note", "take_note", {"observation_ids": ["obs-0001"], "path": path, "line_start": span.line_start, "line_end": span.line_end}),
                tool_response("finish", "finish_search", {"reason": "evidence_sufficient", "missing_aspects": []}),
            ]
        )
        result = execute_r1_question(
            repo_root=ROOT,
            output_root=self.output,
            run_id=self.run_id,
            cell_id="E1",
            question=question,
            provider=provider,
            requested_model="coding",
            budget_unit="characters",
            budget_limit=6000,
            loaded_store=store,
            sleeper=lambda _seconds: None,
        )
        state = write_status(repo_root=ROOT, output_root=self.output, run_id=self.run_id)
        self.assertEqual(result.status, "completed")
        self.assertEqual(state["verified_episode_count"], 1)
        self.assertEqual(state["pending_episode_count"], 35)
        self.assertFalse(state["driver_failure_historical"])
        self.assertEqual(state["next_key"], {"condition_id": "E2", "question_id": question.question_id})

        bundle_path = result.artifact_path / "bundle.json"
        bundle = json.loads(bundle_path.read_text())
        bundle["budget"]["limit"] = 5999
        bundle_path.write_text(json.dumps(bundle), encoding="utf-8")
        with self.assertRaises(EvidenceValidationError):
            write_status(repo_root=ROOT, output_root=self.output, run_id=self.run_id)

    def test_duplicate_publication_incident_becomes_historical_after_verify(self):
        self.prepare()
        question = load_question_inputs(ROOT, "dev-6")[0]
        store = load_r1_store(ROOT, "s1")
        span = store.verified_manifest.attribution_index.occurrences("[S1T13]")[0]
        path = "/memories/" + span.path
        result = execute_r1_question(
            repo_root=ROOT,
            output_root=self.output,
            run_id=self.run_id,
            cell_id="E1",
            question=question,
            provider=Provider(
                [
                    tool_response("read", "view", {"path": path, "start_line": span.line_start, "end_line": span.line_end}),
                    tool_response("note", "take_note", {"observation_ids": ["obs-0001"], "path": path, "line_start": span.line_start, "line_end": span.line_end}),
                    tool_response("finish", "finish_search", {"reason": "evidence_sufficient", "missing_aspects": []}),
                ]
            ),
            requested_model="coding",
            budget_unit="characters",
            budget_limit=6000,
            loaded_store=store,
            sleeper=lambda _seconds: None,
        )
        self.assertEqual(result.status, "completed")
        failure = {
            "schema_version": 1,
            "protocol_version": "dev6-retrieval-e1-e6-v1",
            "run_id": self.run_id,
            "sequence": 1,
            "condition_id": "E1",
            "question_id": question.question_id,
            "error_type": "OSError",
            "message": "duplicate publication race",
            "at": "2026-01-01T00:00:00Z",
        }
        (self.output / self.run_id / "driver-failure.json").write_text(
            json.dumps(failure), encoding="utf-8"
        )
        state = write_status(repo_root=ROOT, output_root=self.output, run_id=self.run_id)
        self.assertEqual(state["status"], "pending")
        self.assertTrue(state["driver_failure_historical"])

    def test_explicit_provider_response_recovery_is_hash_bound(self):
        self.prepare()
        question = load_question_inputs(ROOT, "dev-6")[0]
        failed = execute_r2_question(
            repo_root=ROOT,
            output_root=self.output,
            run_id=self.run_id,
            cell_id="E2",
            question=question,
            provider=Provider(
                [
                    {
                        "message": {"role": "assistant", "content": 123},
                        "usage": {"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3},
                        "served_model": "fake-served",
                    }
                ]
            ),
            requested_model="coding",
            budget_unit="characters",
            budget_limit=6000,
            sleeper=lambda _seconds: None,
        )
        self.assertEqual(failed.status, "failed")
        before = write_status(repo_root=ROOT, output_root=self.output, run_id=self.run_id)
        self.assertEqual(before["failure_count"], 1)
        policy_path = authorize_provider_response_retry(
            repo_root=ROOT, output_root=self.output, run_id=self.run_id
        )
        policy = json.loads(policy_path.read_text())
        self.assertEqual(policy["retry_key"]["condition_id"], "E2")
        self.assertEqual(policy["eligible_failure_kind"], "provider_response")

        succeeded = execute_r2_question(
            repo_root=ROOT,
            output_root=self.output,
            run_id=self.run_id,
            cell_id="E2",
            question=question,
            provider=Provider(
                [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "Thought: done\nAction: finish_search\nAction Input: {}",
                        },
                        "usage": {"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3},
                        "served_model": "fake-served",
                    }
                ]
            ),
            requested_model="coding",
            budget_unit="characters",
            budget_limit=6000,
            sleeper=lambda _seconds: None,
        )
        self.assertEqual(succeeded.status, "completed")
        after = write_status(repo_root=ROOT, output_root=self.output, run_id=self.run_id)
        self.assertEqual(after["failure_count"], 0)
        self.assertEqual(after["method_failure_attempt_count"], 1)
        self.assertEqual(after["recovered_failure_count"], 1)

    def test_repeated_empty_response_hotfix_recovery_is_hash_bound(self):
        self.prepare()
        question = load_question_inputs(ROOT, "dev-6")[0]
        failure_ids = []
        for attempt in range(2):
            failed = execute_r2_question(
                repo_root=ROOT,
                output_root=self.output,
                run_id=self.run_id,
                cell_id="E2",
                question=question,
                provider=Provider(
                    [
                        {
                            "message": {"role": "assistant", "content": 123},
                            "usage": {
                                "prompt_tokens": 2 + attempt,
                                "completion_tokens": 1,
                                "total_tokens": 3 + attempt,
                            },
                            "served_model": "fake-served",
                        }
                    ]
                ),
                requested_model="coding",
                budget_unit="characters",
                budget_limit=6000,
                sleeper=lambda _seconds: None,
            )
            self.assertEqual(failed.status, "failed")
            failure_ids.append(failed.artifact_id)

        policy_path = authorize_empty_content_hotfix_retry(
            repo_root=ROOT, output_root=self.output, run_id=self.run_id
        )
        policy = load_hotfix_recovery_policy(policy_path)
        self.assertEqual(policy["retry_key"]["condition_id"], "E2")
        self.assertEqual(policy["prior_failure_ids"], sorted(failure_ids))
        self.assertEqual(policy["prior_failed_attempt_total_tokens"], 7)
        self.assertEqual(policy["maximum_post_hotfix_retries"], 1)
        self.assertTrue(policy["preserve_all_failure_artifacts"])


if __name__ == "__main__":
    unittest.main()
