import json
import tempfile
import unittest
from pathlib import Path

from fs_memory_lab.evidence import QuestionInput
from fs_memory_lab.r2_artifacts import verify_r2_failure_artifact
from fs_memory_lab.r2_runner import (
    execute_r2_batch,
    execute_r2_question,
    verify_r2_batch_summary,
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
        "served_model": "fake-r2",
    }


class Provider:
    def __init__(self, replies, *, api_style="portable"):
        self.replies = list(replies)
        self.api_style = api_style

    def complete(self, messages, tools, config):
        return self.replies.pop(0)


class R2RunnerTests(unittest.TestCase):
    def setUp(self):
        self.question = QuestionInput.from_mapping(
            {
                "schema_version": 1,
                "question_set_id": "r2-runner-test",
                "run_position": 1,
                "question_id": "r2-runner-001",
                "conversation_id": "conv-50",
                "question": "Where did Calvin plan to travel?",
            }
        )

    def test_execute_one_with_fake_provider(self):
        provider = Provider(
            [
                reply("Search.", "search_chatrecord", {"keywords": ["Japan"], "top_k": 5}),
                reply("Save.", "take_note", {"indices": [1]}),
                reply("Done.", "finish_search", {}),
            ]
        )
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temporary:
            result = execute_r2_question(
                repo_root=ROOT,
                output_root=Path(temporary),
                run_id="fake-run",
                cell_id="E2",
                question=self.question,
                provider=provider,
                requested_model="fake-requested",
                budget_unit="characters",
                budget_limit=20_000,
                sleeper=lambda _seconds: None,
            )
            self.assertEqual(result.status, "completed")
            self.assertTrue((result.artifact_path / "COMPLETED").is_file())
            first_trace = json.loads(
                (result.artifact_path / "trace.jsonl").read_text().splitlines()[0]
            )
            self.assertEqual(first_trace["api_style"], "portable")

    def test_runtime_hash_distinguishes_portable_from_paper_wire(self):
        hashes = []
        for api_style in ("portable", "paper"):
            provider = Provider(
                [reply("Done.", "finish_search", {})], api_style=api_style
            )
            with tempfile.TemporaryDirectory(dir="/private/tmp") as temporary:
                result = execute_r2_question(
                    repo_root=ROOT,
                    output_root=Path(temporary),
                    run_id=f"wire-{api_style}",
                    cell_id="E2",
                    question=self.question,
                    provider=provider,
                    requested_model="fake-requested",
                    budget_unit="characters",
                    budget_limit=20_000,
                    sleeper=lambda _seconds: None,
                )
                bundle = json.loads(
                    (result.artifact_path / "bundle.json").read_text()
                )
                hashes.append(bundle["runtime_contract"]["runtime_sha256"])
                first_trace = json.loads(
                    (result.artifact_path / "trace.jsonl")
                    .read_text()
                    .splitlines()[0]
                )
                self.assertEqual(first_trace["api_style"], api_style)
        self.assertNotEqual(*hashes)

    def test_provider_protocol_failure_is_published_separately(self):
        provider = Provider(
            [
                {
                    "message": {"role": "assistant", "content": None},
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
                    "served_model": "fake-r2",
                }
            ]
        )
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temporary:
            result = execute_r2_question(
                repo_root=ROOT,
                output_root=Path(temporary),
                run_id="failed-run",
                cell_id="E2",
                question=self.question,
                provider=provider,
                requested_model="fake-requested",
                budget_unit="characters",
                budget_limit=20_000,
                sleeper=lambda _seconds: None,
            )
            self.assertEqual(result.status, "failed")
            artifact = verify_r2_failure_artifact(result.artifact_path)
            self.assertEqual(artifact.failure_kind, "provider_response")
            self.assertEqual(artifact.metrics["model_calls"], 1)
            self.assertEqual(artifact.model["served_models"], ("fake-r2",))
            self.assertTrue((result.artifact_path / "FAILED").is_file())

    def test_sequential_batch_summary_is_hash_verified(self):
        episode = [
            reply("Search.", "search_chatrecord", {"keywords": ["Japan"], "top_k": 5}),
            reply("Save.", "take_note", {"indices": [1]}),
            reply("Done.", "finish_search", {}),
        ]
        provider = Provider([*episode, *episode])
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temporary:
            results = execute_r2_batch(
                repo_root=ROOT,
                output_root=Path(temporary),
                run_id="batch-run",
                cell_ids=("E2", "E4"),
                questions=(self.question,),
                provider=provider,
                requested_model="fake-requested",
                budget_unit="characters",
                budget_limit=20_000,
                sleeper=lambda _seconds: None,
            )
            self.assertEqual([item.status for item in results], ["completed", "completed"])
            verified = verify_r2_batch_summary(
                Path(temporary) / "batch-run" / "batch-summary.json",
                repo_root=ROOT,
            )
            self.assertEqual(
                [item.artifact_id for item in verified],
                [item.artifact_id for item in results],
            )


if __name__ == "__main__":
    unittest.main()
