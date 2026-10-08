from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from fs_memory_lab.evidence import EvidenceValidationError, QuestionInput
from fs_memory_lab.r1_agent import R1AgentError, R1ResearchAgent
from fs_memory_lab.r1_artifacts import (
    R1EpisodeWorkspace,
    build_r1_evidence_bundle,
    build_r1_failure_artifact,
    evidence_bundle_from_mapping,
    verify_r1_episode_artifact,
    verify_r1_failure_artifact,
)
from fs_memory_lab.r1_inputs import load_r1_store


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


class R1ArtifactTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.loaded = load_r1_store(REPO_ROOT, "s1")
        cls.span = cls.loaded.verified_manifest.attribution_index.occurrences(
            "[S1T13]"
        )[0]

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(dir="/private/tmp")
        self.output = Path(self.temporary.name) / "r1"
        self.question = QuestionInput.from_mapping(
            {
                "schema_version": 1,
                "question_set_id": "artifact-dev",
                "run_position": 1,
                "question_id": "conv-50-artifact-001",
                "conversation_id": "conv-50",
                "question": "Where did Calvin plan to travel?",
            }
        )

    def tearDown(self):
        self.temporary.cleanup()

    def run_episode(self):
        path = "/memories/" + self.span.path
        provider = Provider(
            [
                tool_response(
                    "read",
                    "view",
                    {
                        "path": path,
                        "start_line": self.span.line_start,
                        "end_line": self.span.line_end,
                    },
                ),
                tool_response(
                    "note",
                    "take_note",
                    {
                        "observation_ids": ["obs-0001"],
                        "path": path,
                        "line_start": self.span.line_start,
                        "line_end": self.span.line_end,
                    },
                ),
                tool_response(
                    "finish",
                    "finish_search",
                    {"reason": "evidence_sufficient", "missing_aspects": []},
                ),
            ]
        )
        workspace = R1EpisodeWorkspace.create(
            output_root=self.output,
            run_id="dev-run-001",
            cell_id="E1",
            question_id=self.question.question_id,
        )
        agent = R1ResearchAgent(
            root=self.loaded.root,
            catalog=self.loaded.catalog,
            verified_manifest=self.loaded.verified_manifest,
            snapshot=self.loaded.snapshot,
            provider=provider,
            requested_model="fake-requested",
            budget_unit="characters",
            budget_limit=10_000,
            event_sink=workspace.sink,
            sleeper=lambda _seconds: None,
            private_checkpoint_path=workspace.private_checkpoint_path,
        )
        outcome = agent.run(cell_id="E1", question=self.question)
        return workspace, outcome

    def test_bundle_roundtrip_and_atomic_publication_verify(self):
        workspace, outcome = self.run_episode()
        bundle = build_r1_evidence_bundle(outcome, loaded_store=self.loaded)
        recreated = evidence_bundle_from_mapping(bundle.to_dict())
        self.assertEqual(recreated, bundle)
        published = workspace.publish_success(bundle=bundle, outcome=outcome)
        self.assertEqual(published, workspace.final)
        self.assertFalse(workspace.staging.exists())
        verified = verify_r1_episode_artifact(published, loaded_store=self.loaded)
        self.assertEqual(verified, bundle)
        self.assertEqual(verified.metrics["provider_rounds"], 3)
        self.assertEqual(verified.metrics["model_calls"], 3)
        self.assertEqual(verified.metrics["total_tokens"], 45)
        self.assertEqual(verified.evidence_items[0].source_locators, ("[S1T13]",))

    def test_bundle_or_trace_tampering_breaks_hash_chain(self):
        workspace, outcome = self.run_episode()
        bundle = build_r1_evidence_bundle(outcome, loaded_store=self.loaded)
        published = workspace.publish_success(bundle=bundle, outcome=outcome)
        bundle_path = published / "bundle.json"
        original = bundle_path.read_bytes()
        bundle_path.write_bytes(original.replace(b"Calvin", b"Mallory", 1))
        with self.assertRaises(EvidenceValidationError):
            verify_r1_episode_artifact(published, loaded_store=self.loaded)

    def test_workspace_rejects_overwrite_and_unsafe_segments(self):
        workspace, outcome = self.run_episode()
        bundle = build_r1_evidence_bundle(outcome, loaded_store=self.loaded)
        workspace.publish_success(bundle=bundle, outcome=outcome)
        with self.assertRaises(EvidenceValidationError):
            R1EpisodeWorkspace.create(
                output_root=self.output,
                run_id="dev-run-001",
                cell_id="E1",
                question_id=self.question.question_id,
            )
        with self.assertRaises(EvidenceValidationError):
            R1EpisodeWorkspace.create(
                output_root=self.output,
                run_id="../escape",
                cell_id="E1",
                question_id="q1",
            )

    def test_failure_artifact_is_separate_atomic_and_verifiable(self):
        provider = Provider(
            [
                {
                    "message": {
                        "role": "assistant",
                        "content": "I will answer directly.",
                    },
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
            ]
        )
        workspace = R1EpisodeWorkspace.create(
            output_root=self.output,
            run_id="dev-run-failure",
            cell_id="E1",
            question_id=self.question.question_id,
        )
        agent = R1ResearchAgent(
            root=self.loaded.root,
            catalog=self.loaded.catalog,
            verified_manifest=self.loaded.verified_manifest,
            snapshot=self.loaded.snapshot,
            provider=provider,
            requested_model="fake-requested",
            budget_unit="characters",
            budget_limit=10_000,
            event_sink=workspace.sink,
            sleeper=lambda _seconds: None,
            private_checkpoint_path=workspace.private_checkpoint_path,
        )
        with self.assertRaises(R1AgentError) as captured:
            agent.run(cell_id="E1", question=self.question)
        artifact = build_r1_failure_artifact(
            captured.exception,
            cell_id="E1",
            question=self.question,
            loaded_store=self.loaded,
            requested_model="fake-requested",
            budget_unit="characters",
            budget_limit=10_000,
        )
        self.assertEqual(artifact.metrics["model_calls"], 1)
        self.assertEqual(artifact.metrics["provider_rounds"], 0)
        self.assertEqual(artifact.metrics["total_tokens"], 15)
        failed = workspace.publish_failure(artifact=artifact)
        self.assertFalse((failed / "bundle.json").exists())
        verified = verify_r1_failure_artifact(failed)
        self.assertEqual(verified, artifact)
        failure_path = failed / "failure.json"
        failure_path.write_bytes(
            failure_path.read_bytes().replace(
                b"provider_response", b"tampered-stage", 1
            )
        )
        with self.assertRaises(EvidenceValidationError):
            verify_r1_failure_artifact(failed)


if __name__ == "__main__":
    unittest.main()
