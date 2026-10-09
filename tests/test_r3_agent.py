import json
import unittest
from pathlib import Path
from unittest.mock import patch

from fs_memory_lab.agent import TransientProviderError
from fs_memory_lab.evidence import QuestionInput
from fs_memory_lab.r3_agent import R3AgentError, R3RetrievalAgent
from fs_memory_lab.r3_index import R3CuratedIndex
from fs_memory_lab.r3_inputs import load_r3_corpus


ROOT = Path(__file__).resolve().parents[1]


def text_response(content: str, served_model: str = "fake-r3") -> dict:
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


class R3AgentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.index = R3CuratedIndex(load_r3_corpus(ROOT))
        cls.question = QuestionInput.from_mapping(
            {
                "schema_version": 1,
                "question_set_id": "r3-test",
                "run_position": 1,
                "question_id": "conv-50-r3-001",
                "conversation_id": "conv-50",
                "question": "What kind of custom guitar did Calvin have?",
            }
        )

    def agent(self, provider):
        return R3RetrievalAgent(
            index=self.index,
            provider=provider,
            requested_model="fake-requested",
            sleeper=lambda _seconds: None,
        )

    def test_search_note_finish_collects_curated_evidence_only(self) -> None:
        provider = ScriptedProvider(
            [
                action(
                    "Search broadly.",
                    "search_chatrecord",
                    {"keywords": ["octopus", "guitar"], "top_k": 5},
                ),
                action("Save the first result.", "take_note", {"indices": [1]}),
                action("Evidence is sufficient.", "finish_search", {}),
            ]
        )
        outcome = self.agent(provider).run(cell_id="E6", question=self.question)
        self.assertEqual(outcome.stop.reason, "evidence_sufficient")
        self.assertEqual(outcome.provider_rounds, 3)
        self.assertEqual(len(outcome.notes), 1)
        self.assertEqual(outcome.notes[0].observation_id, "obs-0001")
        self.assertTrue(outcome.notes[0].hit.anchor.unit_id.startswith("fact-"))
        self.assertTrue(all(call["tools"] == [] for call in provider.calls))
        self.assertIn("R3 Curated-Memory Adapter", provider.calls[0]["messages"][0]["content"])
        self.assertIn("Observation:", provider.calls[1]["messages"][-1]["content"])

    def test_seen_groups_apply_between_searches(self) -> None:
        provider = ScriptedProvider(
            [
                action("First search.", "search_chatrecord", {"keywords": ["music"], "top_k": 5}),
                action("Search again.", "search_chatrecord", {"keywords": ["music"], "top_k": 5}),
                action("Stop.", "finish_search", {}),
            ]
        )
        outcome = self.agent(provider).run(cell_id="E6", question=self.question)
        action_events = [event for event in outcome.trace if event["event"] == "action"]
        first_groups = set(action_events[0]["returned_groups"])
        second_groups = set(action_events[1]["returned_groups"])
        self.assertTrue(first_groups.isdisjoint(second_groups))

    def test_no_match_has_no_silent_fallback(self) -> None:
        provider = ScriptedProvider(
            [
                action(
                    "Search once.",
                    "search_chatrecord",
                    {"keywords": ["zzzznotpresenttokenzzzz"], "top_k": 5},
                ),
                action("Nothing was relevant.", "finish_search", {}),
            ]
        )
        outcome = self.agent(provider).run(cell_id="E6", question=self.question)
        self.assertEqual(outcome.stop.reason, "no_relevant_evidence")
        self.assertEqual(outcome.notes, ())

    def test_four_action_cap_never_auto_saves_last_hits(self) -> None:
        provider = ScriptedProvider(
            [
                action(
                    f"Search {number}.",
                    "search_chatrecord",
                    {"keywords": ["music"], "top_k": 5},
                )
                for number in range(1, 5)
            ]
        )
        outcome = self.agent(provider).run(cell_id="E6", question=self.question)
        self.assertEqual(outcome.stop.reason, "round_limit")
        self.assertTrue(outcome.stop.hit_cap)
        self.assertEqual(outcome.notes, ())
        self.assertEqual(outcome.provider_rounds, 4)

    def test_invalid_action_and_transient_retry_are_auditable(self) -> None:
        provider = ScriptedProvider(
            [
                TransientProviderError("timeout"),
                text_response("not valid"),
                action("Stop.", "finish_search", {}),
            ]
        )
        outcome = self.agent(provider).run(cell_id="E6", question=self.question)
        self.assertEqual(outcome.provider_request_attempts, 3)
        self.assertEqual(outcome.invalid_actions, 1)
        self.assertEqual(outcome.provider_rounds, 2)
        self.assertTrue(any(event["event"] == "provider_retry" for event in outcome.trace))

    def test_observation_safety_failure_becomes_publishable_agent_error(self) -> None:
        provider = ScriptedProvider(
            [
                action(
                    "Search.",
                    "search_chatrecord",
                    {"keywords": ["music"], "top_k": 5},
                )
            ]
        )
        from fs_memory_lab.evidence import EvidenceValidationError

        with patch(
            "fs_memory_lab.r3_agent.format_r3_search_observation",
            side_effect=EvidenceValidationError("observation exceeds safety limit"),
        ):
            with self.assertRaises(R3AgentError) as caught:
                self.agent(provider).run(cell_id="E6", question=self.question)
        self.assertEqual(caught.exception.stage, "action_execution")


if __name__ == "__main__":
    unittest.main()
