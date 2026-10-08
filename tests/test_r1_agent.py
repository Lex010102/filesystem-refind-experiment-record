from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from fs_memory_lab.agent import TransientProviderError
from fs_memory_lab.evidence import (
    QuestionInput,
    SourceCatalog,
    StoreSnapshotRef,
    VerifiedStoreManifest,
)
from fs_memory_lab.r1_agent import (
    FROZEN_R1_AGENT_LIMITS_SHA256,
    R1_AGENT_LIMITS,
    R1_TOOL_NAMES,
    R1AgentError,
    R1ResearchAgent,
    r1_agent_limits_sha256,
    verify_r1_agent_limits,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_MAP = REPO_ROOT / "data" / "manifests" / "source_map.json"
RECORDS = REPO_ROOT / "data" / "processed" / "conv-50.jsonl"
EXPERIMENT = REPO_ROOT / "experiments" / "locomo-conv50-v1"
SOURCE_MAP_SHA256 = "6e99115961bae06a48bfb7e82dbdcc18dc32ccf6c5ce57e3c266dfc7a5d4d574"
RECORDS_SHA256 = "130a5a1e1b75083358ef27a98dd215a4e75c819ace6f2ee9b560ba394e0f0394"
S1_MANIFEST_SHA256 = "5c5900c333c8f85463f038448560cb4357f1161d6ed43e9fbc86809ba7916d3c"


def tool_response(*calls, served_model="fake-r1"):
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
                        "arguments": (
                            arguments
                            if isinstance(arguments, str)
                            else json.dumps(arguments)
                        ),
                    },
                }
                for call_id, name, arguments in calls
            ],
        },
        "usage": {
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "total_tokens": 15,
        },
        "finish_reason": "tool_calls",
        "served_model": served_model,
    }


class ScriptedProvider:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def complete(self, messages, tools, config):
        self.calls.append(
            {
                "messages": json.loads(json.dumps(messages)),
                "tools": json.loads(json.dumps(tools)),
                "config": config,
            }
        )
        if not self.responses:
            raise AssertionError("Scripted provider received an unexpected call")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class R1ResearchAgentTest(unittest.TestCase):
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
        self.span = self.manifest.attribution_index.occurrences("[S1T13]")[0]
        self.path = "/memories/" + self.span.path
        self.question = QuestionInput.from_mapping(
            {
                "schema_version": 1,
                "question_set_id": "r1-dev",
                "run_position": 1,
                "question_id": "conv-50-dev-001",
                "conversation_id": "conv-50",
                "question": "Where did Calvin plan to travel?",
            }
        )

    def tearDown(self):
        self.temporary.cleanup()

    def agent(self, provider, **overrides):
        values = {
            "root": self.store,
            "catalog": self.catalog,
            "verified_manifest": self.manifest,
            "snapshot": self.snapshot,
            "provider": provider,
            "requested_model": "fake-requested",
            "budget_unit": "characters",
            "budget_limit": 10_000,
            "sleeper": lambda _seconds: None,
        }
        values.update(overrides)
        return R1ResearchAgent(**values)

    def successful_script(self):
        return [
            tool_response(
                (
                    "call-view",
                    "view",
                    {
                        "path": self.path,
                        "start_line": self.span.line_start,
                        "end_line": self.span.line_end,
                    },
                )
            ),
            tool_response(
                (
                    "call-note",
                    "take_note",
                    {
                        "observation_ids": ["obs-0001"],
                        "path": self.path,
                        "line_start": self.span.line_start,
                        "line_end": self.span.line_end,
                    },
                )
            ),
            tool_response(
                (
                    "call-finish",
                    "finish_search",
                    {"reason": "evidence_sufficient", "missing_aspects": []},
                )
            ),
        ]

    def test_fake_provider_end_to_end_produces_host_verified_evidence(self):
        provider = ScriptedProvider(self.successful_script())
        outcome = self.agent(provider).run(cell_id="E1", question=self.question)
        self.assertEqual(outcome.stop.reason, "evidence_sufficient")
        self.assertEqual(outcome.rounds.rounds_completed, 3)
        self.assertEqual(len(outcome.observations.observations), 1)
        self.assertEqual(len(outcome.notes.evidence_items), 1)
        item = outcome.notes.evidence_items[0]
        self.assertEqual(item.source_locators, ("[S1T13]",))
        self.assertEqual(item.path, self.path)
        self.assertEqual(outcome.filesystem_tool_calls, 1)
        self.assertEqual(outcome.orchestration_calls, 2)
        self.assertEqual(outcome.provider_request_attempts, 3)
        self.assertEqual(outcome.served_models, ("fake-r1",))
        names = tuple(tool["function"]["name"] for tool in provider.calls[0]["tools"])
        self.assertEqual(names, R1_TOOL_NAMES)
        self.assertNotIn("gold", provider.calls[0]["messages"][1]["content"])
        second_messages = provider.calls[1]["messages"]
        observation = json.loads(second_messages[-1]["content"])
        self.assertEqual(observation["observation_id"], "obs-0001")
        self.assertIn("content", observation)

    def test_invalid_note_is_recoverable_and_cannot_enter_evidence(self):
        responses = [
            self.successful_script()[0],
            tool_response(
                (
                    "bad-note",
                    "take_note",
                    {
                        "observation_ids": ["obs-9999"],
                        "path": self.path,
                        "line_start": self.span.line_start,
                        "line_end": self.span.line_end,
                    },
                )
            ),
            self.successful_script()[1],
            self.successful_script()[2],
        ]
        provider = ScriptedProvider(responses)
        outcome = self.agent(provider).run(cell_id="E1", question=self.question)
        self.assertEqual(outcome.rounds.rounds_completed, 4)
        self.assertEqual(len(outcome.notes.evidence_items), 1)
        bad_result = json.loads(provider.calls[2]["messages"][-1]["content"])
        self.assertFalse(bad_result["ok"])
        self.assertEqual(bad_result["error"]["code"], "unobserved_selection")

    def test_invalid_json_tool_arguments_are_recoverable(self):
        provider = ScriptedProvider(
            [
                tool_response(("bad-json", "view", "{")),
                *self.successful_script(),
            ]
        )
        outcome = self.agent(provider).run(cell_id="E1", question=self.question)
        self.assertEqual(outcome.rounds.rounds_completed, 4)
        error = json.loads(provider.calls[1]["messages"][-1]["content"])
        self.assertEqual(error["error"]["code"], "invalid_json")
        self.assertEqual(len(outcome.observations.observations), 1)

    def test_mixed_action_modes_fail_closed(self):
        provider = ScriptedProvider(
            [
                tool_response(
                    ("read", "view", {"path": "/memories"}),
                    (
                        "note",
                        "take_note",
                        {
                            "observation_ids": ["obs-0001"],
                            "path": self.path,
                            "line_start": self.span.line_start,
                            "line_end": self.span.line_end,
                        },
                    ),
                )
            ]
        )
        with self.assertRaises(R1AgentError) as raised:
            self.agent(provider).run(cell_id="E1", question=self.question)
        self.assertEqual(raised.exception.stage, "provider_response")
        self.assertIn("mixes incompatible", str(raised.exception))

    def test_free_text_or_unknown_tool_fails_closed(self):
        free_text = {
            "message": {"role": "assistant", "content": "The answer is Japan."},
            "usage": {},
            "served_model": "fake-r1",
        }
        with self.assertRaises(R1AgentError):
            self.agent(ScriptedProvider([free_text])).run(
                cell_id="E1", question=self.question
            )
        with self.assertRaises(R1AgentError):
            self.agent(
                ScriptedProvider([tool_response(("bad-tool", "create", {"path": "x"}))])
            ).run(cell_id="E1", question=self.question)

    def test_missing_served_model_or_inconsistent_usage_fails_closed(self):
        missing = self.successful_script()[0]
        missing.pop("served_model")
        with self.assertRaises(R1AgentError) as raised:
            self.agent(ScriptedProvider([missing])).run(
                cell_id="E1", question=self.question
            )
        self.assertEqual(raised.exception.stage, "provider_response")

        inconsistent = self.successful_script()[0]
        inconsistent["usage"]["total_tokens"] = 99
        with self.assertRaises(R1AgentError) as raised:
            self.agent(ScriptedProvider([inconsistent])).run(
                cell_id="E1", question=self.question
            )
        self.assertIn("inconsistent", str(raised.exception))

    def test_transient_request_retry_does_not_duplicate_actions(self):
        delays = []
        provider = ScriptedProvider(
            [
                TransientProviderError("temporary timeout"),
                *self.successful_script(),
            ]
        )
        outcome = self.agent(provider, sleeper=delays.append).run(
            cell_id="E1", question=self.question
        )
        self.assertEqual(delays, [2])
        self.assertEqual(outcome.provider_request_attempts, 4)
        self.assertEqual(len(outcome.observations.observations), 1)
        self.assertEqual(len(outcome.notes.evidence_items), 1)

    def test_host_enforces_exact_s1_round_cap(self):
        provider = ScriptedProvider(
            [
                tool_response((f"root-{number}", "view", {"path": "/memories"}))
                for number in range(1, 21)
            ]
        )
        outcome = self.agent(provider).run(cell_id="E1", question=self.question)
        self.assertEqual(outcome.stop.reason, "round_limit")
        self.assertTrue(outcome.stop.hit_cap)
        self.assertEqual(outcome.rounds.rounds_completed, 20)
        self.assertEqual(outcome.filesystem_tool_calls, 20)
        self.assertEqual(len(provider.calls), 20)

    def test_limits_are_explicit_and_content_addressed(self):
        self.assertEqual(R1_AGENT_LIMITS["max_tool_calls_per_response"], 16)
        self.assertEqual(R1_AGENT_LIMITS["max_tool_calls_per_episode"], 320)
        self.assertRegex(r1_agent_limits_sha256(), r"^[0-9a-f]{64}$")
        self.assertEqual(r1_agent_limits_sha256(), FROZEN_R1_AGENT_LIMITS_SHA256)
        verify_r1_agent_limits()


if __name__ == "__main__":
    unittest.main()
