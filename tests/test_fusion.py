import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from fs_memory_lab.answerer import SharedAnswerer
from fs_memory_lab.evidence import (
    EvidenceValidationError,
    QuestionInput,
    evidence_bundle_from_mapping,
)
from fs_memory_lab.fusion import (
    FUSION_CONTRACT_SHA256,
    build_e7_fusion_bundle,
    fusion_bundle_from_mapping,
)
from fs_memory_lab.r2_runner import execute_r2_question
from fs_memory_lab.r3_runner import execute_r3_question
from fs_memory_lab.run_records import ExperimentRunStore, RunRecord, build_run_plan


ROOT = Path(__file__).resolve().parents[1]


def reply(name, arguments, *, served):
    return {
        "message": {
            "role": "assistant",
            "content": (
                f"Thought: test\nAction: {name}\n"
                f"Action Input: {json.dumps(arguments, separators=(',', ':'))}"
            ),
        },
        "usage": {"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3},
        "served_model": served,
    }


class Provider:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []
        self.api_style = "portable"

    def complete(self, messages, tools, config):
        self.calls.append((messages, tools, config))
        return self.replies.pop(0)


class FusionTests(unittest.TestCase):
    def setUp(self):
        self.question = QuestionInput.from_mapping(
            {
                "schema_version": 1,
                "question_set_id": "fusion-test",
                "run_position": 1,
                "question_id": "fusion-q1",
                "conversation_id": "conv-50",
                "question": "Where did Calvin plan to travel?",
            }
        )

    def build_sources(self, temporary):
        root = Path(temporary)
        r2 = execute_r2_question(
            repo_root=ROOT,
            output_root=root,
            run_id="raw",
            cell_id="E2",
            question=self.question,
            provider=Provider(
                [
                    reply("search_chatrecord", {"keywords": ["Japan"], "top_k": 5}, served="r2"),
                    reply("take_note", {"indices": [1]}, served="r2"),
                    reply("finish_search", {}, served="r2"),
                ]
            ),
            requested_model="fake",
            budget_unit="characters",
            budget_limit=20_000,
            sleeper=lambda _: None,
        )
        r3 = execute_r3_question(
            repo_root=ROOT,
            output_root=root,
            run_id="curated",
            question=self.question,
            provider=Provider(
                [
                    reply("search_chatrecord", {"keywords": ["Japan"], "top_k": 5}, served="r3"),
                    reply("take_note", {"indices": [1]}, served="r3"),
                    reply("finish_search", {}, served="r3"),
                ]
            ),
            requested_model="fake",
            budget_unit="characters",
            budget_limit=20_000,
            sleeper=lambda _: None,
        )
        raw = evidence_bundle_from_mapping(
            json.loads((r2.artifact_path / "bundle.json").read_text())
        )
        curated = evidence_bundle_from_mapping(
            json.loads((r3.artifact_path / "bundle.json").read_text())
        )
        return raw, curated

    @staticmethod
    def answer_bundle(bundle):
        evidence_id = bundle.evidence_items[0].evidence_id
        return SharedAnswerer(
            provider=Provider(
                [
                    {
                        "message": {
                            "role": "assistant",
                            "content": json.dumps(
                                {
                                    "answer": "Japan",
                                    "citations": [evidence_id],
                                    "insufficient_evidence": False,
                                }
                            ),
                        },
                        "usage": {"prompt_tokens": 10, "completion_tokens": 3, "total_tokens": 13},
                        "served_model": "answerer",
                    }
                ]
            ),
            requested_model="answerer",
            sleeper=lambda _: None,
        ).run(bundle)

    def test_deterministic_round_robin_and_round_trip(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temporary:
            raw, curated = self.build_sources(temporary)
            fused = build_e7_fusion_bundle(raw, curated)
            self.assertEqual(fused.source_conditions, ("E2", "E6"))
            self.assertEqual(fused.contract_sha256, FUSION_CONTRACT_SHA256)
            self.assertEqual(fused.evidence_channels[:2], ("RAW", "CURATED"))
            self.assertEqual(fused.retrieval_metrics["search_calls"], 0)
            self.assertEqual(fused.budget.total_limit, 40_000)
            restored = fusion_bundle_from_mapping(fused.to_dict())
            self.assertEqual(restored, fused)
            self.assertEqual(build_e7_fusion_bundle(raw, curated), fused)

    def test_source_budget_must_match(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temporary:
            raw, curated = self.build_sources(temporary)
            curated = replace(
                curated,
                budget=replace(curated.budget, limit=curated.budget.limit + 1),
            )
            with self.assertRaises(EvidenceValidationError):
                build_e7_fusion_bundle(raw, curated)

    def test_wrong_source_condition_is_rejected(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temporary:
            raw, curated = self.build_sources(temporary)
            raw = replace(raw, condition={"condition_id": "E4", "store_id": "s1", "retrieval_id": "r2"})
            with self.assertRaises(EvidenceValidationError):
                build_e7_fusion_bundle(raw, curated)

    def test_shared_answerer_accepts_fusion_without_condition_label(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temporary:
            raw, curated = self.build_sources(temporary)
            fused = build_e7_fusion_bundle(raw, curated)
            evidence_id = fused.evidence_items[0].evidence_id
            provider = Provider(
                [
                    {
                        "message": {
                            "role": "assistant",
                            "content": json.dumps(
                                {
                                    "answer": "Japan",
                                    "citations": [evidence_id],
                                    "insufficient_evidence": False,
                                }
                            ),
                        },
                        "usage": {"prompt_tokens": 10, "completion_tokens": 3, "total_tokens": 13},
                        "served_model": "answerer",
                    }
                ]
            )
            result = SharedAnswerer(
                provider=provider,
                requested_model="answerer",
                sleeper=lambda _: None,
            ).run(fused)
            self.assertEqual(result.answer, "Japan")
            prompt = provider.calls[0][0][-1]["content"]
            self.assertNotIn("E7", prompt)
            self.assertIn("Source: RAW", prompt)
            self.assertIn("Source: CURATED", prompt)

    def test_e7_publishes_only_after_its_exact_e2_and_e6_sources(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temporary:
            raw, curated = self.build_sources(temporary)
            fused = build_e7_fusion_bundle(raw, curated)
            plan = build_run_plan(
                run_id="e7-link-test",
                question_set_id=self.question.question_set_id,
                question_ids=(self.question.question_id,),
                condition_ids=("E2", "E6", "E7"),
                config_hashes={"test": "a" * 64},
            )
            records = {
                condition: RunRecord.create(
                    plan_id=plan.plan_id,
                    run_id=plan.run_id,
                    condition_id=condition,
                    evidence_bundle=bundle,
                    answer_result=self.answer_bundle(bundle),
                )
                for condition, bundle in (("E2", raw), ("E6", curated), ("E7", fused))
            }
            store = ExperimentRunStore.create_or_open(Path(temporary) / "formal", plan)
            with self.assertRaises(EvidenceValidationError):
                store.publish_success(records["E7"])
            store.publish_success(records["E2"])
            with self.assertRaises(EvidenceValidationError):
                store.publish_success(records["E7"])
            store.publish_success(records["E6"])
            store.publish_success(records["E7"])
            self.assertEqual(store.load_completed(records["E7"].key), records["E7"])


if __name__ == "__main__":
    unittest.main()
