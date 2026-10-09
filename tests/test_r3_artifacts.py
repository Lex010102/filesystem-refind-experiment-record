import json
import tempfile
import unittest
from pathlib import Path

from fs_memory_lab.evidence import EvidenceValidationError, QuestionInput
from fs_memory_lab.r3_agent import R3RetrievalAgent
from fs_memory_lab.r3_artifacts import (
    R3EpisodeWorkspace,
    build_r3_evidence_bundle,
    verify_r3_episode_artifact,
)
from fs_memory_lab.r3_index import R3CuratedIndex
from fs_memory_lab.r3_inputs import load_r3_corpus


ROOT = Path(__file__).resolve().parents[1]


def response(thought, name, arguments):
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
    def __init__(self, replies):
        self.replies = list(replies)
        self.api_style = "portable"

    def complete(self, messages, tools, config):
        return self.replies.pop(0)


class R3ArtifactTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.corpus = load_r3_corpus(ROOT)
        cls.question = QuestionInput.from_mapping(
            {
                "schema_version": 1,
                "question_set_id": "r3-artifact-test",
                "run_position": 1,
                "question_id": "r3-artifact-001",
                "conversation_id": "conv-50",
                "question": "What kind of custom guitar did Calvin have?",
            }
        )

    def outcome(self, indices=(1,)):
        provider = Provider(
            [
                response(
                    "Search.",
                    "search_chatrecord",
                    {"keywords": ["octopus", "guitar"], "top_k": 5},
                ),
                response("Save.", "take_note", {"indices": list(indices)}),
                response("Done.", "finish_search", {}),
            ]
        )
        return R3RetrievalAgent(
            index=R3CuratedIndex(self.corpus),
            provider=provider,
            requested_model="fake-requested",
            sleeper=lambda _seconds: None,
        ).run(cell_id="E6", question=self.question)

    def test_overlapping_fact_windows_merge_before_bundle(self):
        bundle = build_r3_evidence_bundle(
            self.outcome(indices=(1, 2)),
            corpus=self.corpus,
            budget_unit="characters",
            budget_limit=100_000,
        )
        self.assertEqual(bundle.status, "completed")
        paths = [item.path for item in bundle.evidence_items]
        self.assertEqual(len(paths), len(set(paths)))
        self.assertTrue(all(item.source_kind == "curated" for item in bundle.evidence_items))
        self.assertEqual(bundle.condition["retrieval_id"], "r3")

    def test_budget_skips_whole_item_without_truncation(self):
        bundle = build_r3_evidence_bundle(
            self.outcome(),
            corpus=self.corpus,
            budget_unit="characters",
            budget_limit=1,
        )
        self.assertEqual(bundle.stop.reason, "evidence_budget_reached")
        self.assertEqual(bundle.evidence_items, ())
        self.assertEqual(bundle.budget.skipped_items, 1)
        self.assertFalse(bundle.budget.truncated)

    def test_atomic_publish_reload_and_tamper_detection(self):
        outcome = self.outcome()
        bundle = build_r3_evidence_bundle(
            outcome,
            corpus=self.corpus,
            budget_unit="characters",
            budget_limit=100_000,
        )
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temporary:
            workspace = R3EpisodeWorkspace.create(
                output_root=Path(temporary),
                run_id="run-1",
                question_id=self.question.question_id,
            )
            for event in outcome.trace:
                workspace.sink(event)
            published = workspace.publish_success(bundle)
            verified = verify_r3_episode_artifact(published, corpus=self.corpus)
            self.assertEqual(verified.bundle_id, bundle.bundle_id)
            (published / "trace.jsonl").write_text("{}\n", encoding="utf-8")
            with self.assertRaises(EvidenceValidationError):
                verify_r3_episode_artifact(published, corpus=self.corpus)


if __name__ == "__main__":
    unittest.main()
