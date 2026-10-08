from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fs_memory_lab.agent import TransientProviderError
from fs_memory_lab.evidence import (
    EvidenceValidationError,
    QuestionInput,
    SourceCatalog,
    StoreSnapshotRef,
    VerifiedStoreManifest,
    canonical_json_bytes,
)
from fs_memory_lab.r1_agent import (
    FROZEN_R1_AGENT_LIMITS_SHA256,
    R1_AGENT_LIMITS,
    R1_FREE_TEXT_CORRECTION_PROMPT,
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

    def test_valid_tool_calls_with_free_text_get_one_safe_correction(self):
        polluted = self.successful_script()[0]
        polluted["message"]["content"] = "I will inspect the memory now."
        provider = ScriptedProvider([polluted, *self.successful_script()])

        outcome = self.agent(provider).run(cell_id="E1", question=self.question)

        self.assertEqual(outcome.stop.reason, "evidence_sufficient")
        self.assertEqual(outcome.rounds.rounds_completed, 3)
        self.assertEqual(outcome.model_calls, 4)
        self.assertEqual(outcome.protocol_correction_calls, 1)
        self.assertEqual(outcome.provider_request_attempts, 4)
        self.assertEqual(len(outcome.observations.observations), 1)
        self.assertEqual(len(outcome.notes.evidence_items), 1)
        self.assertEqual(
            provider.calls[1]["messages"][-1],
            {"role": "user", "content": R1_FREE_TEXT_CORRECTION_PROMPT},
        )
        encoded_trace = canonical_json_bytes(outcome.trace)
        self.assertNotIn(b"I will inspect the memory now", encoded_trace)
        corrections = [
            event
            for event in outcome.trace
            if event.get("kind") == "protocol_correction_requested"
        ]
        self.assertEqual(len(corrections), 1)

    def test_repeated_free_text_with_tool_calls_still_fails_closed(self):
        first = self.successful_script()[0]
        first["message"]["content"] = "First invalid explanation."
        second = self.successful_script()[0]
        second["message"]["content"] = "Second invalid explanation."
        provider = ScriptedProvider([first, second])

        with self.assertRaises(R1AgentError) as raised:
            self.agent(provider).run(cell_id="E1", question=self.question)

        self.assertEqual(raised.exception.stage, "provider_response")
        self.assertEqual(raised.exception.filesystem_tool_calls, 0)
        self.assertEqual(len(provider.calls), 2)
        self.assertEqual(
            sum(
                event.get("kind") == "protocol_correction_requested"
                for event in raised.exception.trace
            ),
            1,
        )

    def test_nontext_assistant_content_is_not_correction_eligible(self):
        malformed = self.successful_script()[0]
        malformed["message"]["content"] = [{"type": "text", "text": "no"}]
        provider = ScriptedProvider([malformed])

        with self.assertRaises(R1AgentError) as raised:
            self.agent(provider).run(cell_id="E1", question=self.question)

        self.assertEqual(raised.exception.stage, "provider_response")
        self.assertEqual(len(provider.calls), 1)
        self.assertFalse(
            any(
                event.get("kind") == "protocol_correction_requested"
                for event in raised.exception.trace
            )
        )

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

    def test_context_compaction_is_separate_model_call_and_keeps_host_state(self):
        high_usage = tool_response(("root-4", "view", {"path": "/memories"}))
        high_usage["usage"] = {
            "prompt_tokens": 97_001,
            "completion_tokens": 5,
            "total_tokens": 97_006,
        }
        summary = {
            "message": {
                "role": "assistant",
                "content": "Earlier rounds surveyed the same root; no evidence was saved.",
            },
            "usage": {
                "prompt_tokens": 100,
                "completion_tokens": 20,
                "total_tokens": 120,
            },
            "finish_reason": "stop",
            "served_model": "fake-r1",
        }
        responses = [
            tool_response(("root-1", "view", {"path": "/memories"})),
            tool_response(("root-2", "view", {"path": "/memories"})),
            tool_response(("root-3", "view", {"path": "/memories"})),
            high_usage,
            summary,
            self.successful_script()[0],
            tool_response(
                (
                    "note-after-compact",
                    "take_note",
                    {
                        "observation_ids": ["obs-0005"],
                        "path": self.path,
                        "line_start": self.span.line_start,
                        "line_end": self.span.line_end,
                    },
                )
            ),
            self.successful_script()[2],
        ]
        provider = ScriptedProvider(responses)
        outcome = self.agent(provider).run(cell_id="E1", question=self.question)
        self.assertEqual(outcome.rounds.rounds_completed, 7)
        self.assertEqual(outcome.compaction_calls, 1)
        self.assertEqual(outcome.model_calls, 8)
        self.assertEqual(outcome.provider_request_attempts, 8)
        self.assertEqual(provider.calls[4]["tools"], [])
        self.assertIn("Running summary", provider.calls[5]["messages"][2]["content"])
        self.assertEqual(len(outcome.notes.evidence_items), 1)
        self.assertTrue(
            any(event.get("kind") == "context_compaction" for event in outcome.trace)
        )

    def test_shared_token_safety_fuse_records_usage_and_executes_no_actions(self):
        provider = ScriptedProvider(
            [tool_response(("would-read", "view", {"path": "/memories"}))]
        )
        agent = self.agent(provider)
        tiny_limits = dict(R1_AGENT_LIMITS)
        tiny_limits["token_safety_fuse_limit"] = 15

        with patch("fs_memory_lab.r1_agent.R1_AGENT_LIMITS", tiny_limits):
            with self.assertRaises(R1AgentError) as raised:
                agent.run(cell_id="E1", question=self.question)

        error = raised.exception
        self.assertEqual(error.stage, "token_safety_fuse")
        self.assertEqual(error.filesystem_tool_calls, 0)
        self.assertEqual(error.orchestration_calls, 0)
        self.assertEqual(len(provider.calls), 1)
        checkpoints = [
            event
            for event in error.trace
            if event.get("kind") == "token_usage_checkpoint"
        ]
        self.assertEqual(len(checkpoints), 1)
        self.assertEqual(checkpoints[0]["cumulative_usage"]["total_tokens"], 15)
        triggered = [
            event
            for event in error.trace
            if event.get("kind") == "token_safety_fuse_triggered"
        ]
        self.assertEqual(len(triggered), 1)
        self.assertFalse(triggered[0]["filesystem_results_clipped"])
        self.assertFalse(triggered[0]["response_actions_executed"])

    def test_limits_are_explicit_and_content_addressed(self):
        self.assertEqual(R1_AGENT_LIMITS["max_tool_calls_per_response"], 16)
        self.assertEqual(R1_AGENT_LIMITS["max_tool_calls_per_episode"], 320)
        self.assertEqual(R1_AGENT_LIMITS["free_text_corrections_per_round"], 1)
        self.assertEqual(R1_AGENT_LIMITS["free_text_corrections_per_episode"], 3)
        self.assertEqual(R1_AGENT_LIMITS["token_safety_fuse_limit"], 1_000_000)
        self.assertEqual(
            R1_AGENT_LIMITS["token_safety_fuse_unit"],
            "provider_reported_total_tokens",
        )
        self.assertEqual(R1_AGENT_LIMITS["filesystem_result_truncation"], "none")
        self.assertRegex(r1_agent_limits_sha256(), r"^[0-9a-f]{64}$")
        self.assertEqual(r1_agent_limits_sha256(), FROZEN_R1_AGENT_LIMITS_SHA256)
        verify_r1_agent_limits()

    def test_private_episode_secret_is_mode_0600_and_absent_from_trace(self):
        private_path = Path(self.temporary.name) / "private" / "episode-secret.json"
        private_path.parent.mkdir()
        provider = ScriptedProvider(self.successful_script())
        outcome = self.agent(provider, private_checkpoint_path=private_path).run(
            cell_id="E1", question=self.question
        )
        self.assertEqual(os.stat(private_path).st_mode & 0o777, 0o600)
        outcome.observations.verify_private_checkpoint(private_path)
        self.assertNotIn(b"secret_hex", canonical_json_bytes(outcome.trace))
        os.chmod(private_path, 0o644)
        with self.assertRaisesRegex(EvidenceValidationError, "0600"):
            outcome.observations.verify_private_checkpoint(private_path)


if __name__ == "__main__":
    unittest.main()
