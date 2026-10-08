import json
import tempfile
import unittest
from pathlib import Path

from fs_memory_lab.evidence import EvidenceValidationError, QuestionInput
from fs_memory_lab.r2_agent import R2RetrievalAgent
from fs_memory_lab.r2_artifacts import (
    R2EpisodeWorkspace,
    build_r2_evidence_bundle,
    verify_r2_episode_artifact,
)
from fs_memory_lab.r2_index import R2RawIndex
from fs_memory_lab.r2_inputs import build_r2_raw_corpus


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
        "served_model": "fake-r2",
    }


class Provider:
    def __init__(self, replies):
        self.replies = list(replies)

    def complete(self, messages, tools, config):
        return self.replies.pop(0)


class R2ArtifactTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.corpus = build_r2_raw_corpus(ROOT, "s1")
        cls.question = QuestionInput.from_mapping(
            {
                "schema_version": 1,
                "question_set_id": "r2-artifact-test",
                "run_position": 1,
                "question_id": "r2-artifact-001",
                "conversation_id": "conv-50",
                "question": "Where did Calvin plan to travel?",
            }
        )

    def outcome(self, indices=(1,)):
        provider = Provider(
            [
                response("Search.", "search_chatrecord", {"keywords": ["Japan"], "top_k": 5}),
                response("Save.", "take_note", {"indices": list(indices)}),
                response("Done.", "finish_search", {}),
            ]
        )
        return R2RetrievalAgent(
            index=R2RawIndex(self.corpus),
            provider=provider,
            requested_model="fake-requested",
            sleeper=lambda _seconds: None,
        ).run(cell_id="E2", question=self.question)

    def test_overlapping_context_blocks_merge_before_bundle(self):
        bundle = build_r2_evidence_bundle(
            self.outcome(indices=(2, 3)),
            loaded_store=self.corpus.store,
            corpus_sha256=self.corpus.corpus_sha256,
            budget_unit="characters",
            budget_limit=20_000,
        )
        self.assertEqual(bundle.status, "completed")
        self.assertEqual(len(bundle.evidence_items), 1)
        item = bundle.evidence_items[0]
        self.assertEqual(item.rank, 2)
        self.assertEqual(item.observation_ids, ("obs-0001",))
        self.assertEqual(item.source_locators[0], "[S1T1]")
        self.assertEqual(item.source_locators[-1], "[S1T12]")

    def test_budget_skips_whole_item_without_truncation(self):
        bundle = build_r2_evidence_bundle(
            self.outcome(),
            loaded_store=self.corpus.store,
            corpus_sha256=self.corpus.corpus_sha256,
            budget_unit="characters",
            budget_limit=1,
        )
        self.assertEqual(bundle.stop.reason, "evidence_budget_reached")
        self.assertEqual(bundle.evidence_items, ())
        self.assertEqual(bundle.budget.skipped_items, 1)
        self.assertFalse(bundle.budget.truncated)

    def test_atomic_publish_reload_and_tamper_detection(self):
        outcome = self.outcome()
        bundle = build_r2_evidence_bundle(
            outcome,
            loaded_store=self.corpus.store,
            corpus_sha256=self.corpus.corpus_sha256,
            budget_unit="characters",
            budget_limit=20_000,
        )
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temporary:
            workspace = R2EpisodeWorkspace.create(
                output_root=Path(temporary),
                run_id="run-1",
                cell_id="E2",
                question_id=self.question.question_id,
            )
            for event in outcome.trace:
                workspace.sink(event)
            published = workspace.publish_success(bundle)
            verified = verify_r2_episode_artifact(
                published, loaded_store=self.corpus.store
            )
            self.assertEqual(verified.bundle_id, bundle.bundle_id)
            (published / "trace.jsonl").write_text("{}\n", encoding="utf-8")
            with self.assertRaises(EvidenceValidationError):
                verify_r2_episode_artifact(published, loaded_store=self.corpus.store)


if __name__ == "__main__":
    unittest.main()
