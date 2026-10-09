import json
import tempfile
import unittest
from pathlib import Path

from fs_memory_lab.answerer import (
    ANSWERER_SYSTEM_PROMPT_SHA256,
    AnswererError,
    SharedAnswerer,
    validate_answer_result,
)
from fs_memory_lab.agent import TransientProviderError
from fs_memory_lab.evidence import QuestionInput
from fs_memory_lab.r2_artifacts import evidence_bundle_from_mapping
from fs_memory_lab.r2_runner import execute_r2_question


ROOT = Path(__file__).resolve().parents[1]


def retrieval_reply(name, arguments):
    return {
        "message": {
            "role": "assistant",
            "content": (
                f"Thought: test\nAction: {name}\n"
                f"Action Input: {json.dumps(arguments, separators=(',', ':'))}"
            ),
        },
        "usage": {"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3},
        "served_model": "fake-retriever",
    }


def answer_reply(content, *, served="fake-answerer", response_id="resp-1"):
    return {
        "message": {"role": "assistant", "content": content},
        "usage": {"prompt_tokens": 20, "completion_tokens": 5, "total_tokens": 25},
        "served_model": served,
        "response_id": response_id,
        "finish_reason": "stop",
    }


class Provider:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []
        self.api_style = "portable"

    def complete(self, messages, tools, config):
        self.calls.append((json.loads(json.dumps(messages)), list(tools), config))
        if not self.replies:
            raise AssertionError("unexpected provider call")
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


class SharedAnswererTests(unittest.TestCase):
    def setUp(self):
        self.question = QuestionInput.from_mapping(
            {
                "schema_version": 1,
                "question_set_id": "answerer-test",
                "run_position": 1,
                "question_id": "answerer-q1",
                "conversation_id": "conv-50",
                "question": "Where did Calvin plan to travel?",
            }
        )

    def build_bundle(self, temporary):
        provider = Provider(
            [
                retrieval_reply("search_chatrecord", {"keywords": ["Japan"], "top_k": 5}),
                retrieval_reply("take_note", {"indices": [1]}),
                retrieval_reply("finish_search", {}),
            ]
        )
        result = execute_r2_question(
            repo_root=ROOT,
            output_root=Path(temporary),
            run_id="retrieval",
            cell_id="E2",
            question=self.question,
            provider=provider,
            requested_model="fake-retriever",
            budget_unit="characters",
            budget_limit=20_000,
            sleeper=lambda _: None,
        )
        value = json.loads((result.artifact_path / "bundle.json").read_text())
        return evidence_bundle_from_mapping(value)

    def test_answerer_uses_no_tools_and_hides_condition(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temporary:
            bundle = self.build_bundle(temporary)
            evidence_id = bundle.evidence_items[0].evidence_id
            provider = Provider(
                [
                    answer_reply(
                        json.dumps(
                            {
                                "answer": "Japan",
                                "citations": [evidence_id],
                                "insufficient_evidence": False,
                            }
                        )
                    )
                ]
            )
            result = SharedAnswerer(
                provider=provider,
                requested_model="fake-answerer",
                sleeper=lambda _: None,
            ).run(bundle)
            self.assertEqual(result.answer, "Japan")
            self.assertEqual(result.citations, (evidence_id,))
            self.assertEqual(result.prompt_sha256, ANSWERER_SYSTEM_PROMPT_SHA256)
            self.assertEqual(provider.calls[0][1], [])
            prompt = provider.calls[0][0][-1]["content"]
            self.assertNotIn("E2", prompt)
            self.assertNotIn("gold", prompt.lower())
            validate_answer_result(result, bundle=bundle)

    def test_one_format_only_repair(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temporary:
            bundle = self.build_bundle(temporary)
            evidence_id = bundle.evidence_items[0].evidence_id
            provider = Provider(
                [
                    answer_reply("Japan", response_id="bad"),
                    answer_reply(
                        json.dumps(
                            {
                                "answer": "Japan",
                                "citations": [evidence_id],
                                "insufficient_evidence": False,
                            }
                        ),
                        response_id="fixed",
                    ),
                ]
            )
            result = SharedAnswerer(
                provider=provider,
                requested_model="fake-answerer",
                sleeper=lambda _: None,
            ).run(bundle)
            self.assertEqual(result.format_repairs, 1)
            self.assertEqual(result.model_calls, 2)
            self.assertNotIn(bundle.evidence_items[0].text, provider.calls[1][0][-1]["content"])

    def test_unknown_citation_fails_after_one_repair(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temporary:
            bundle = self.build_bundle(temporary)
            invalid = json.dumps(
                {
                    "answer": "Japan",
                    "citations": ["ev-" + "f" * 64],
                    "insufficient_evidence": False,
                }
            )
            provider = Provider([answer_reply(invalid), answer_reply(invalid)])
            with self.assertRaises(AnswererError) as raised:
                SharedAnswerer(
                    provider=provider,
                    requested_model="fake-answerer",
                    sleeper=lambda _: None,
                ).run(bundle)
            self.assertEqual(raised.exception.stage, "answer_schema")

    def test_transient_timeout_retries_before_completion(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temporary:
            bundle = self.build_bundle(temporary)
            evidence_id = bundle.evidence_items[0].evidence_id
            provider = Provider(
                [
                    TransientProviderError("timeout"),
                    answer_reply(
                        json.dumps(
                            {
                                "answer": "Japan",
                                "citations": [evidence_id],
                                "insufficient_evidence": False,
                            }
                        )
                    ),
                ]
            )
            result = SharedAnswerer(
                provider=provider,
                requested_model="fake-answerer",
                sleeper=lambda _: None,
            ).run(bundle)
            self.assertEqual(result.provider_request_attempts, 2)
            self.assertEqual(result.model_calls, 1)


if __name__ == "__main__":
    unittest.main()
