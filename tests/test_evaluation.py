import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from fs_memory_lab.answerer import SharedAnswerer
from fs_memory_lab.evaluation import (
    AnonymousCorrectnessJudge,
    GoldRecord,
    LOCOMO_EVALUATOR_SHA256,
    aggregate_evaluations,
    evaluate_run_record,
    evaluate_run_store,
    load_gold_records,
    locomo_category_f1,
    locomo_f1_score,
    locomo_multi_answer_f1,
    normalize_answer,
    write_evaluation_report,
)
from fs_memory_lab.evidence import QuestionInput, evidence_bundle_from_mapping, sha256_bytes
from fs_memory_lab.r2_runner import execute_r2_question
from fs_memory_lab.run_records import ExperimentRunStore, RunRecord, build_run_plan
from fs_memory_lab.vendor.locomo_porter import PorterStemmer


ROOT = Path(__file__).resolve().parents[1]


def action(name, arguments):
    return {
        "message": {
            "role": "assistant",
            "content": f"Thought: test\nAction: {name}\nAction Input: {json.dumps(arguments)}",
        },
        "usage": {"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3},
        "served_model": "retriever",
    }


class Provider:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []
        self.api_style = "portable"

    def complete(self, messages, tools, config):
        self.calls.append((json.loads(json.dumps(messages)), tools, config))
        return self.replies.pop(0)


class EvaluationTests(unittest.TestCase):
    def setUp(self):
        self.question = QuestionInput.from_mapping(
            {
                "schema_version": 1,
                "question_set_id": "eval-set",
                "run_position": 1,
                "question_id": "eval-q1",
                "conversation_id": "conv-50",
                "question": "Where did Calvin plan to travel?",
            }
        )

    def build_record(self, temporary):
        root = Path(temporary)
        retrieval = execute_r2_question(
            repo_root=ROOT,
            output_root=root / "retrieval",
            run_id="source",
            cell_id="E2",
            question=self.question,
            provider=Provider(
                [
                    action("search_chatrecord", {"keywords": ["Japan"], "top_k": 5}),
                    action("take_note", {"indices": [1]}),
                    action("finish_search", {}),
                ]
            ),
            requested_model="retriever",
            budget_unit="characters",
            budget_limit=20_000,
            sleeper=lambda _: None,
        )
        bundle = evidence_bundle_from_mapping(
            json.loads((retrieval.artifact_path / "bundle.json").read_text())
        )
        evidence_id = bundle.evidence_items[0].evidence_id
        answer_provider = Provider(
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
                    "usage": {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7},
                    "served_model": "answerer",
                }
            ]
        )
        answer = SharedAnswerer(
            provider=answer_provider,
            requested_model="answerer",
            sleeper=lambda _: None,
        ).run(bundle)
        plan = build_run_plan(
            run_id="eval-run",
            question_set_id="eval-set",
            question_ids=("eval-q1",),
            condition_ids=("E2",),
            config_hashes={"x": "a" * 64},
        )
        return RunRecord.create(
            plan_id=plan.plan_id,
            run_id=plan.run_id,
            condition_id="E2",
            evidence_bundle=bundle,
            answer_result=answer,
        )

    def gold(self, dia_ids):
        return GoldRecord(
            schema_version=1,
            question_set_id="eval-set",
            question_id="eval-q1",
            source_qa_index=1,
            non_adversarial_order=1,
            category=4,
            category_name="single-hop",
            answer="Japan",
            gold_evidence_dia_ids_official=tuple(dia_ids),
            gold_evidence_dia_ids=tuple(dia_ids),
            gold_evidence_locators=tuple(),
            gold_evidence_sessions=tuple(),
            has_caption_evidence=False,
        )

    def test_official_normalization_stemming_and_category_rules(self):
        stemmer = PorterStemmer()
        self.assertEqual(stemmer.stem("relational"), "relat")
        self.assertEqual(stemmer.stem("lying"), "lie")
        self.assertEqual(stemmer.stem("skies"), "sky")
        self.assertEqual(normalize_answer("The Cats, and a dog!"), "cats dog")
        self.assertEqual(locomo_f1_score("cats and dogs", "cat, dog"), 1.0)
        self.assertEqual(locomo_multi_answer_f1("Tokyo, ramen", "Tokyo, ramen"), 1.0)
        self.assertEqual(locomo_category_f1("Tokyo", "Tokyo; Japan", 3), 1.0)
        self.assertEqual(locomo_f1_score("", ""), 0.0)
        self.assertEqual(len(LOCOMO_EVALUATOR_SHA256), 64)

    def test_gold_loader_is_hash_pinned(self):
        source = ROOT / "experiments" / "locomo-conv50-v1" / "question-sets" / "dev-6-gold.jsonl"
        digest = sha256_bytes(source.read_bytes())
        rows = load_gold_records(source, expected_sha256=digest)
        self.assertEqual(len(rows), 6)
        with self.assertRaises(Exception):
            load_gold_records(source, expected_sha256="0" * 64)

    def test_evidence_citation_cost_and_aggregate_metrics(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temporary:
            record = self.build_record(temporary)
            retrieved = tuple(
                dict.fromkeys(
                    dia
                    for item in record.evidence_bundle.evidence_items
                    for dia in item.dia_ids
                )
            )
            result = evaluate_run_record(record, self.gold((retrieved[0],)))
            self.assertEqual(result.locomo_f1, 1.0)
            self.assertEqual(result.evidence_recall, 1.0)
            self.assertTrue(result.evidence_any_hit)
            self.assertTrue(result.evidence_all_hit)
            self.assertEqual(result.citation_validity, 1.0)
            summary = aggregate_evaluations((result,))
            self.assertEqual(summary["row_count"], 1)
            self.assertEqual(summary["conditions"]["E2"]["micro_f1"], 1.0)
            self.assertIsNone(summary["conditions"]["E2"]["post_stratified_f1"])
            report = write_evaluation_report(Path(temporary) / "report.json", (result,))
            self.assertTrue(report.is_file())
            with self.assertRaises(Exception):
                write_evaluation_report(report, (result,))

    def test_zero_gold_evidence_is_excluded_from_evidence_denominator(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temporary:
            result = evaluate_run_record(self.build_record(temporary), self.gold(()))
            self.assertFalse(result.evidence_eligible)
            self.assertIsNone(result.evidence_recall)

    def test_whole_run_requires_complete_hash_pinned_matching_store(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temporary:
            temporary_path = Path(temporary)
            record = self.build_record(temporary)
            plan = build_run_plan(
                run_id=record.run_id,
                question_set_id="eval-set",
                question_ids=("eval-q1",),
                condition_ids=("E2",),
                config_hashes={"x": "a" * 64},
            )
            store_root = temporary_path / "formal"
            store = ExperimentRunStore.create_or_open(store_root, plan)
            gold_path = temporary_path / "gold.jsonl"
            gold_path.write_text(json.dumps({
                "schema_version": 1,
                "question_set_id": "eval-set",
                "question_id": "eval-q1",
                "source_qa_index": 1,
                "non_adversarial_order": 1,
                "category": 4,
                "category_name": "single-hop",
                "answer": "Japan",
                "gold_evidence_dia_ids_official": [],
                "gold_evidence_dia_ids": [],
                "gold_evidence_locators": [],
                "gold_evidence_sessions": [],
                "has_caption_evidence": False,
            }) + "\n", encoding="utf-8")
            digest = sha256_bytes(gold_path.read_bytes())
            with self.assertRaises(Exception):
                evaluate_run_store(
                    run_root=store_root,
                    run_id=plan.run_id,
                    gold_path=gold_path,
                    expected_gold_sha256=digest,
                )
            store.publish_success(record)
            rows = evaluate_run_store(
                run_root=store_root,
                run_id=plan.run_id,
                gold_path=gold_path,
                expected_gold_sha256=digest,
            )
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].condition_id, "E2")

    def test_anonymous_judge_sees_no_condition_and_is_attached(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temporary:
            record = self.build_record(temporary)
            provider = Provider(
                [
                    {
                        "message": {
                            "role": "assistant",
                            "content": json.dumps(
                                {
                                    "label": "correct",
                                    "binary_correct": 1,
                                    "short_reason": "Semantically equivalent.",
                                    "confidence": "high",
                                }
                            ),
                        },
                        "usage": {"prompt_tokens": 4, "completion_tokens": 2, "total_tokens": 6},
                        "served_model": "judge",
                    }
                ]
            )
            judge = AnonymousCorrectnessJudge(
                provider=provider,
                requested_model="judge",
                sleeper=lambda _: None,
            )
            result = evaluate_run_record(record, self.gold(()), judge=judge)
            self.assertEqual(result.judge.binary_correct, 1)
            prompt = provider.calls[0][0][-1]["content"]
            self.assertNotIn("E2", prompt)
            self.assertNotIn("condition", prompt.lower())


if __name__ == "__main__":
    unittest.main()
