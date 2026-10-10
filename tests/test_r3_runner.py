import json
import tempfile
import unittest
from pathlib import Path

from fs_memory_lab.evidence import QuestionInput
from fs_memory_lab.r3_artifacts import verify_r3_failure_artifact
from fs_memory_lab.r3_runner import (
    execute_r3_batch,
    execute_r3_question,
    verify_r3_batch_summary,
)


ROOT = Path(__file__).resolve().parents[1]


def reply(thought, name, arguments):
    return {
        "message": {
            "role": "assistant",
            "content": (
                f"Thought: {thought}\nAction: {name}\n"
                f"Action Input: {json.dumps(arguments, separators=(',', ':'))}"
            ),
        },
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        "finish_reason": "stop",
        "served_model": "fake-r3",
    }


class Provider:
    def __init__(self, replies, *, api_style="portable"):
        self.replies = list(replies)
        self.api_style = api_style

    def complete(self, messages, tools, config):
        return self.replies.pop(0)


class R3RunnerTests(unittest.TestCase):
    def setUp(self):
        self.question = QuestionInput.from_mapping(
            {
                "schema_version": 1,
                "question_set_id": "r3-runner-test",
                "run_position": 1,
                "question_id": "r3-runner-001",
                "conversation_id": "conv-50",
                "question": "What kind of custom guitar did Calvin have?",
            }
        )

    def episode(self):
        return [
            reply(
                "Search.",
                "search_chatrecord",
                {"keywords": ["octopus", "guitar"], "top_k": 5},
            ),
            reply("Save.", "take_note", {"indices": [1]}),
            reply("Done.", "finish_search", {}),
        ]

    def test_execute_one_with_fake_provider(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temporary:
            result = execute_r3_question(
                repo_root=ROOT,
                output_root=Path(temporary),
                run_id="fake-run",
                question=self.question,
                provider=Provider(self.episode()),
                requested_model="fake-requested",
                budget_unit="characters",
                budget_limit=100_000,
                sleeper=lambda _seconds: None,
            )
            self.assertEqual(result.status, "completed")
            self.assertEqual(result.cell_id, "E6")
            self.assertTrue((result.artifact_path / "COMPLETED").is_file())
            first_trace = json.loads(
                (result.artifact_path / "trace.jsonl").read_text().splitlines()[0]
            )
            self.assertEqual(first_trace["cell_id"], "E6")
            self.assertEqual(first_trace["store_id"], "s3")

    def test_runtime_hash_distinguishes_wire_profiles(self):
        hashes = []
        for api_style in ("portable", "paper"):
            with tempfile.TemporaryDirectory(dir="/private/tmp") as temporary:
                result = execute_r3_question(
                    repo_root=ROOT,
                    output_root=Path(temporary),
                    run_id=f"wire-{api_style}",
                    question=self.question,
                    provider=Provider([reply("Done.", "finish_search", {})], api_style=api_style),
                    requested_model="fake-requested",
                    budget_unit="characters",
                    budget_limit=20_000,
                    sleeper=lambda _seconds: None,
                )
                bundle = json.loads((result.artifact_path / "bundle.json").read_text())
                hashes.append(bundle["runtime_contract"]["runtime_sha256"])
        self.assertNotEqual(*hashes)

    def test_provider_protocol_failure_is_separate_artifact(self):
        provider = Provider(
            [
                {
                    "message": {"role": "assistant", "content": 123},
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
                    "served_model": "fake-r3",
                }
            ]
        )
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temporary:
            result = execute_r3_question(
                repo_root=ROOT,
                output_root=Path(temporary),
                run_id="failed-run",
                question=self.question,
                provider=provider,
                requested_model="fake-requested",
                budget_unit="characters",
                budget_limit=20_000,
                sleeper=lambda _seconds: None,
            )
            self.assertEqual(result.status, "failed")
            artifact = verify_r3_failure_artifact(result.artifact_path)
            self.assertEqual(artifact.failure_kind, "provider_response")
            self.assertEqual(artifact.condition["retrieval_id"], "r3")

    def test_sequential_batch_summary_is_hash_verified(self):
        second_question = QuestionInput.from_mapping(
            {
                "schema_version": 1,
                "question_set_id": "r3-runner-test",
                "run_position": 2,
                "question_id": "r3-runner-002",
                "conversation_id": "conv-50",
                "question": "What music did Calvin like?",
            }
        )
        provider = Provider([*self.episode(), *self.episode()])
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temporary:
            results = execute_r3_batch(
                repo_root=ROOT,
                output_root=Path(temporary),
                run_id="batch-run",
                questions=(self.question, second_question),
                provider=provider,
                requested_model="fake-requested",
                budget_unit="characters",
                budget_limit=100_000,
                sleeper=lambda _seconds: None,
            )
            self.assertEqual([item.status for item in results], ["completed", "completed"])
            verified = verify_r3_batch_summary(
                Path(temporary) / "batch-run" / "batch-summary.json",
                repo_root=ROOT,
            )
            self.assertEqual(
                [item.artifact_id for item in verified],
                [item.artifact_id for item in results],
            )


if __name__ == "__main__":
    unittest.main()
