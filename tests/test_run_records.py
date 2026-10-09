import json
import tempfile
import unittest
from pathlib import Path

from fs_memory_lab.answerer import SharedAnswerer
from fs_memory_lab.evidence import (
    EvidenceValidationError,
    QuestionInput,
    evidence_bundle_from_mapping,
    sha256_bytes,
)
from fs_memory_lab.r2_runner import execute_r2_question
from fs_memory_lab.run_records import (
    ExperimentRunStore,
    RunKey,
    RunRecord,
    build_run_plan,
    run_record_from_mapping,
    verify_run_store,
)


ROOT = Path(__file__).resolve().parents[1]


def reply(name, arguments, *, served="fake"):
    return {
        "message": {
            "role": "assistant",
            "content": (
                f"Thought: test\nAction: {name}\n"
                f"Action Input: {json.dumps(arguments, separators=(',', ':'))}"
            ),
        },
        "usage": {"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3},
        "served_model": served,
    }


class Provider:
    def __init__(self, replies):
        self.replies = list(replies)
        self.api_style = "portable"

    def complete(self, messages, tools, config):
        return self.replies.pop(0)


class RunRecordTests(unittest.TestCase):
    def setUp(self):
        self.question = QuestionInput.from_mapping(
            {
                "schema_version": 1,
                "question_set_id": "run-record-test",
                "run_position": 1,
                "question_id": "run-q1",
                "conversation_id": "conv-50",
                "question": "Where did Calvin plan to travel?",
            }
        )
        self.plan = build_run_plan(
            run_id="formal-test",
            question_set_id="run-record-test",
            question_ids=(self.question.question_id,),
            condition_ids=("E2",),
            config_hashes={"test": sha256_bytes(b"config")},
        )

    def build_record(self, temporary):
        root = Path(temporary)
        retrieval = execute_r2_question(
            repo_root=ROOT,
            output_root=root / "retrieval",
            run_id="source",
            cell_id="E2",
            question=self.question,
            provider=Provider(
                [
                    reply("search_chatrecord", {"keywords": ["Japan"], "top_k": 5}),
                    reply("take_note", {"indices": [1]}),
                    reply("finish_search", {}),
                ]
            ),
            requested_model="fake",
            budget_unit="characters",
            budget_limit=20_000,
            sleeper=lambda _: None,
        )
        bundle = evidence_bundle_from_mapping(
            json.loads((retrieval.artifact_path / "bundle.json").read_text())
        )
        evidence_id = bundle.evidence_items[0].evidence_id
        answerer = SharedAnswerer(
            provider=Provider(
                [
                    {
                        "message": {
                            "role": "assistant",
                            "content": json.dumps(
                                {
                                    "answer": "Japan",
                                    "citations": [evidence_id],
                                    "insufficient_evidence": False,
                                }
                            ),
                        },
                        "usage": {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7},
                        "served_model": "answerer",
                    }
                ]
            ),
            requested_model="answerer",
            sleeper=lambda _: None,
        )
        answer = answerer.run(bundle)
        return RunRecord.create(
            plan_id=self.plan.plan_id,
            run_id=self.plan.run_id,
            condition_id="E2",
            evidence_bundle=bundle,
            answer_result=answer,
        )

    def test_atomic_publish_verify_and_resume_skip(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temporary:
            record = self.build_record(temporary)
            output = Path(temporary) / "formal"
            store = ExperimentRunStore.create_or_open(output, self.plan)
            self.assertEqual(store.pending_keys(), (RunKey("E2", "run-q1"),))
            path = store.publish_success(record)
            self.assertTrue(path.is_file())
            self.assertEqual(store.pending_keys(), ())
            reopened, checkpoint = verify_run_store(output, self.plan.run_id)
            self.assertEqual(reopened.load_completed(record.key), record)
            self.assertEqual(checkpoint["completed"], 1)
            self.assertEqual(checkpoint["pending"], 0)
            with self.assertRaises(EvidenceValidationError):
                store.publish_success(record)

    def test_failure_history_stays_pending_then_success_can_publish(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temporary:
            record = self.build_record(temporary)
            store = ExperimentRunStore.create_or_open(Path(temporary) / "formal", self.plan)
            key = record.key
            store.publish_failure(
                key=key,
                stage="provider",
                error_type="TimeoutError",
                message="timed out",
                retryable=True,
            )
            store.publish_failure(
                key=key,
                stage="provider",
                error_type="TimeoutError",
                message="timed out again",
                retryable=True,
            )
            self.assertEqual(len(store.failure_attempts(key)), 2)
            self.assertEqual(store.pending_keys(), (key,))
            store.publish_success(record)
            self.assertEqual(store.pending_keys(), ())
            self.assertEqual(len(store.failure_attempts(key)), 2)

    def test_existing_plan_must_match_exactly(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temporary:
            output = Path(temporary) / "formal"
            ExperimentRunStore.create_or_open(output, self.plan)
            changed = build_run_plan(
                run_id=self.plan.run_id,
                question_set_id=self.plan.question_set_id,
                question_ids=self.plan.question_ids,
                condition_ids=self.plan.condition_ids,
                config_hashes={"test": sha256_bytes(b"changed")},
            )
            with self.assertRaises(EvidenceValidationError):
                ExperimentRunStore.create_or_open(output, changed)

    def test_tampered_record_fails_closed(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temporary:
            record = self.build_record(temporary)
            store = ExperimentRunStore.create_or_open(Path(temporary) / "formal", self.plan)
            path = store.publish_success(record)
            value = json.loads(path.read_text())
            value["answer_result"]["answer"] = "tampered"
            path.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaises(EvidenceValidationError):
                store.pending_keys()

    def test_record_round_trip_and_rotated_order(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temporary:
            record = self.build_record(temporary)
            self.assertEqual(run_record_from_mapping(record.to_dict()), record)
        plan = build_run_plan(
            run_id="order-test",
            question_set_id="set",
            question_ids=("q1", "q2"),
            condition_ids=("E1", "E2", "E3", "E4", "E5", "E6", "E7"),
            config_hashes={"x": "a" * 64},
        )
        self.assertEqual(
            [key.condition_id for key in plan.execution_order[:7]],
            ["E1", "E2", "E3", "E4", "E5", "E6", "E7"],
        )
        self.assertEqual(
            [key.condition_id for key in plan.execution_order[7:14]],
            ["E2", "E3", "E4", "E5", "E6", "E1", "E7"],
        )

if __name__ == "__main__":
    unittest.main()
