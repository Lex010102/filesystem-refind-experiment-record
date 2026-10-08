import json
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from fs_memory_lab.agent import CompatibleChatProvider, TransientProviderError
from fs_memory_lab.evidence import QuestionInput
from fs_memory_lab.r2_agent import R2PlannerConfig, R2RetrievalAgent
from fs_memory_lab.r2_index import R2RawIndex
from fs_memory_lab.r2_inputs import build_r2_raw_corpus


ROOT = Path(__file__).resolve().parents[1]


def text_response(content: str, served_model: str = "fake-r2") -> dict:
    return {
        "message": {"role": "assistant", "content": content},
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        "finish_reason": "stop",
        "served_model": served_model,
    }


def action(thought: str, name: str, arguments: dict) -> dict:
    return text_response(
        f"Thought: {thought}\nAction: {name}\n"
        f"Action Input: {json.dumps(arguments, separators=(',', ':'))}"
    )


class ScriptedProvider:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.api_style = "portable"

    def complete(self, messages, tools, config):
        self.calls.append(
            {
                "messages": json.loads(json.dumps(messages)),
                "tools": json.loads(json.dumps(tools)),
                "config": config,
            }
        )
        if not self.responses:
            raise AssertionError("unexpected provider call")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class R2AgentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.index = R2RawIndex(build_r2_raw_corpus(ROOT, "s1"))
        cls.question = QuestionInput.from_mapping(
            {
                "schema_version": 1,
                "question_set_id": "r2-test",
                "run_position": 1,
                "question_id": "conv-50-r2-001",
                "conversation_id": "conv-50",
                "question": "Where did Calvin plan to travel?",
            }
        )

    def agent(self, provider):
        return R2RetrievalAgent(
            index=self.index,
            provider=provider,
            requested_model="fake-requested",
            sleeper=lambda _seconds: None,
        )

    def test_fake_provider_search_note_finish(self) -> None:
        provider = ScriptedProvider(
            [
                action("Search broadly.", "search_chatrecord", {"keywords": ["Japan"], "top_k": 5}),
                action("Save the first result.", "take_note", {"indices": [1]}),
                action("Evidence is sufficient.", "finish_search", {}),
            ]
        )
        outcome = self.agent(provider).run(cell_id="E2", question=self.question)
        self.assertEqual(outcome.stop.reason, "evidence_sufficient")
        self.assertEqual(outcome.provider_rounds, 3)
        self.assertEqual(len(outcome.notes), 1)
        self.assertEqual(outcome.notes[0].observation_id, "obs-0001")
        self.assertEqual(outcome.api_style, "portable")
        self.assertTrue(all(call["tools"] == [] for call in provider.calls))
        self.assertTrue(all(call["config"].temperature == 0 for call in provider.calls))
        self.assertIn("Observation:", provider.calls[1]["messages"][-1]["content"])

    def test_no_relevant_finish_has_no_silent_fallback(self) -> None:
        provider = ScriptedProvider(
            [
                action("Search once.", "search_chatrecord", {"keywords": ["notfoundxyz"], "top_k": 5}),
                action("Nothing was relevant.", "finish_search", {}),
            ]
        )
        outcome = self.agent(provider).run(cell_id="E2", question=self.question)
        self.assertEqual(outcome.stop.reason, "no_relevant_evidence")
        self.assertEqual(outcome.notes, ())
        self.assertEqual(outcome.searches, 1)

    def test_four_searches_cap_without_auto_note_or_direct_bm25(self) -> None:
        provider = ScriptedProvider(
            [
                action(f"Search {number}.", "search_chatrecord", {"keywords": ["Japan"], "top_k": 5})
                for number in range(1, 5)
            ]
        )
        outcome = self.agent(provider).run(cell_id="E2", question=self.question)
        self.assertEqual(outcome.stop.reason, "round_limit")
        self.assertTrue(outcome.stop.hit_cap)
        self.assertEqual(outcome.notes, ())
        self.assertEqual(outcome.provider_rounds, 4)

    def test_invalid_action_consumes_one_action_and_is_recoverable(self) -> None:
        provider = ScriptedProvider(
            [
                text_response("This is not the required format."),
                action("Stop.", "finish_search", {}),
            ]
        )
        outcome = self.agent(provider).run(cell_id="E2", question=self.question)
        self.assertEqual(outcome.invalid_actions, 1)
        self.assertEqual(outcome.provider_rounds, 2)
        self.assertIn("Error [invalid_format]", provider.calls[1]["messages"][-1]["content"])

    def test_transient_failure_retries_before_response(self) -> None:
        provider = ScriptedProvider(
            [
                TransientProviderError("timeout"),
                action("Stop.", "finish_search", {}),
            ]
        )
        outcome = self.agent(provider).run(cell_id="E2", question=self.question)
        self.assertEqual(outcome.provider_request_attempts, 2)
        self.assertEqual(outcome.provider_rounds, 1)

    def test_portable_wire_sends_temperature_but_omits_paper_only_fields(self) -> None:
        provider = CompatibleChatProvider(
            "https://api.example.test/v1",
            "coding",
            "test-key",
            api_style="portable",
        )
        response = MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps(
            {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "Thought: Done.\nAction: finish_search\nAction Input: {}",
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 1,
                    "completion_tokens": 1,
                    "total_tokens": 2,
                },
                "model": "qwen-test",
            }
        ).encode("utf-8")
        config = R2PlannerConfig("coding", "high", 4096, 4, 0)
        with patch("urllib.request.urlopen", return_value=response) as urlopen:
            provider.complete([{"role": "user", "content": "test"}], [], config)
        payload = json.loads(urlopen.call_args.args[0].data)
        self.assertEqual(payload["temperature"], 0)
        self.assertNotIn("reasoning_effort", payload)
        self.assertNotIn("max_completion_tokens", payload)
        self.assertNotIn("tools", payload)


if __name__ == "__main__":
    unittest.main()
