from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from fs_memory_lab.evidence import EvidenceValidationError, QuestionInput
from fs_memory_lab.r1_artifacts import (
    verify_r1_episode_artifact,
    verify_r1_failure_artifact,
)
from fs_memory_lab.r1_cli import build_parser
from fs_memory_lab.r1_inputs import load_r1_store
from fs_memory_lab.r1_runner import (
    execute_r1_batch,
    execute_r1_question,
    verify_r1_batch_summary,
)


REPO_ROOT = Path(__file__).resolve().parents[1]


def tool_response(call_id, name, arguments):
    return {
        "message": {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": call_id,
                    "type": "function",
                    "function": {
                        "name": name,
                        "arguments": json.dumps(arguments),
                    },
                }
            ],
        },
        "usage": {
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "total_tokens": 15,
        },
        "finish_reason": "tool_calls",
        "response_id": "fake-response",
        "served_model": "fake-r1",
        "system_fingerprint": "fake-fingerprint",
    }


class Provider:
    def __init__(self, responses):
        self.responses = list(responses)

    def complete(self, _messages, _tools, _config):
        return self.responses.pop(0)


class R1RunnerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.loaded = load_r1_store(REPO_ROOT, "s1")
        cls.span = cls.loaded.verified_manifest.attribution_index.occurrences(
            "[S1T13]"
        )[0]

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(dir="/private/tmp")
        self.output = Path(self.temporary.name) / "r1"

    def tearDown(self):
        self.temporary.cleanup()

    @staticmethod
    def question(number):
        return QuestionInput.from_mapping(
            {
                "schema_version": 1,
                "question_set_id": "runner-dev",
                "run_position": number,
                "question_id": f"conv-50-runner-{number:03d}",
                "conversation_id": "conv-50",
                "question": "Where did Calvin plan to travel?",
            }
        )

    def success_responses(self, prefix):
        path = "/memories/" + self.span.path
        return [
            tool_response(
                prefix + "-read",
                "view",
                {
                    "path": path,
                    "start_line": self.span.line_start,
                    "end_line": self.span.line_end,
                },
            ),
            tool_response(
                prefix + "-note",
                "take_note",
                {
                    "observation_ids": ["obs-0001"],
                    "path": path,
                    "line_start": self.span.line_start,
                    "line_end": self.span.line_end,
                },
            ),
            tool_response(
                prefix + "-finish",
                "finish_search",
                {"reason": "evidence_sufficient", "missing_aspects": []},
            ),
        ]

    def test_single_success_and_failure_are_published_and_verified(self):
        success = execute_r1_question(
            repo_root=REPO_ROOT,
            output_root=self.output,
            run_id="runner-success",
            cell_id="E1",
            question=self.question(1),
            provider=Provider(self.success_responses("one")),
            requested_model="fake-requested",
            budget_unit="characters",
            budget_limit=10_000,
            loaded_store=self.loaded,
            sleeper=lambda _seconds: None,
        )
        self.assertEqual(success.status, "completed")
        self.assertEqual(
            verify_r1_episode_artifact(
                success.artifact_path, loaded_store=self.loaded
            ).bundle_id,
            success.artifact_id,
        )

        failure_response = {
            "message": {"role": "assistant", "content": "direct answer"},
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 5,
                "total_tokens": 15,
            },
            "finish_reason": "stop",
            "response_id": "bad-response",
            "served_model": "fake-r1",
            "system_fingerprint": "fake-fingerprint",
        }
        failure = execute_r1_question(
            repo_root=REPO_ROOT,
            output_root=self.output,
            run_id="runner-failure",
            cell_id="E1",
            question=self.question(2),
            provider=Provider([failure_response]),
            requested_model="fake-requested",
            budget_unit="characters",
            budget_limit=10_000,
            loaded_store=self.loaded,
            sleeper=lambda _seconds: None,
        )
        self.assertEqual(failure.status, "failed")
        self.assertEqual(
            verify_r1_failure_artifact(failure.artifact_path).failure_id,
            failure.artifact_id,
        )

    def test_batch_is_cell_major_and_writes_frozen_summary(self):
        questions = (self.question(1), self.question(2))
        responses = [
            *self.success_responses("q1"),
            *self.success_responses("q2"),
        ]
        results = execute_r1_batch(
            repo_root=REPO_ROOT,
            output_root=self.output,
            run_id="runner-batch",
            cell_ids=("E1",),
            questions=questions,
            provider=Provider(responses),
            requested_model="fake-requested",
            budget_unit="characters",
            budget_limit=10_000,
            stop_on_failure=True,
            sleeper=lambda _seconds: None,
        )
        self.assertEqual(
            [item.question_id for item in results],
            [
                "conv-50-runner-001",
                "conv-50-runner-002",
            ],
        )
        summary = json.loads(
            (self.output / "runner-batch" / "batch-summary.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(summary["planned_episode_count"], 2)
        self.assertEqual(summary["completed_episode_count"], 2)
        self.assertFalse(summary["halted_on_failure"])
        self.assertEqual(len(summary["summary_sha256"]), 64)
        verified = verify_r1_batch_summary(
            self.output / "runner-batch" / "batch-summary.json",
            repo_root=REPO_ROOT,
        )
        self.assertEqual(verified, results)
        summary["completed_episode_count"] = 1
        (self.output / "runner-batch" / "batch-summary.json").write_text(
            json.dumps(summary), encoding="utf-8"
        )
        with self.assertRaises(EvidenceValidationError):
            verify_r1_batch_summary(
                self.output / "runner-batch" / "batch-summary.json",
                repo_root=REPO_ROOT,
            )

    def test_cli_requires_explicit_budget_and_has_offline_preflight(self):
        parser = build_parser()
        parsed = parser.parse_args(["--repo-root", str(REPO_ROOT), "preflight"])
        self.assertEqual(parsed.command, "preflight")
        with self.assertRaises(SystemExit):
            parser.parse_args(
                [
                    "run-one",
                    "--cell",
                    "E1",
                    "--question-set",
                    "dev-6",
                    "--question-id",
                    "conv-50-q129",
                    "--run-id",
                    "missing-budget",
                    "--output-root",
                    str(self.output),
                ]
            )


if __name__ == "__main__":
    unittest.main()
