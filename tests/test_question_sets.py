import json
import tempfile
import unittest
from pathlib import Path

from fs_memory_lab.question_sets import (
    DEV_QUOTAS,
    FORBIDDEN_ONLINE_KEYS,
    MAIN_QUOTAS,
    build_question_sets,
    verify_question_sets,
)


ROOT = Path(__file__).resolve().parents[1]
QUESTION_DIR = ROOT / "experiments/locomo-conv50-v1/question-sets"


def load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line]


class FrozenQuestionSetTest(unittest.TestCase):
    def test_checked_in_artifacts_pass_full_verification(self):
        result = verify_question_sets(ROOT, QUESTION_DIR)
        self.assertEqual(result["status"], "passed")

    def test_regeneration_is_byte_identical(self):
        with tempfile.TemporaryDirectory() as temporary:
            generated = Path(temporary) / "question-sets"
            result = build_question_sets(ROOT, generated)
            self.assertEqual(result["verification"]["status"], "passed")
            self.assertEqual(
                sorted(path.name for path in generated.iterdir()),
                sorted(path.name for path in QUESTION_DIR.iterdir()),
            )
            for checked_in in QUESTION_DIR.iterdir():
                self.assertEqual(
                    (generated / checked_in.name).read_bytes(),
                    checked_in.read_bytes(),
                    checked_in.name,
                )

    def test_online_input_is_separated_from_gold(self):
        main_input = load_jsonl(QUESTION_DIR / "main-40-input.jsonl")
        main_gold = load_jsonl(QUESTION_DIR / "main-40-gold.jsonl")
        dev_input = load_jsonl(QUESTION_DIR / "dev-6-input.jsonl")
        dev_gold = load_jsonl(QUESTION_DIR / "dev-6-gold.jsonl")

        self.assertEqual(len(main_input), 40)
        self.assertEqual(len(dev_input), 6)
        self.assertFalse(any(FORBIDDEN_ONLINE_KEYS & row.keys() for row in main_input))
        self.assertEqual(
            [row["question_id"] for row in main_input],
            [row["question_id"] for row in main_gold],
        )
        self.assertEqual(
            {row["category"] for row in main_gold}, set(MAIN_QUOTAS)
        )
        self.assertEqual({row["category"] for row in dev_gold}, set(DEV_QUOTAS))
        self.assertTrue(
            {row["question_id"] for row in main_input}.isdisjoint(
                {row["question_id"] for row in dev_input}
            )
        )

    def test_official_zero_padded_evidence_alias_is_canonicalized(self):
        gold = {
            row["question_id"]: row
            for row in load_jsonl(QUESTION_DIR / "main-40-gold.jsonl")
        }
        row = gold["conv-50-q070"]
        self.assertIn("D30:05", row["gold_evidence_dia_ids_official"])
        self.assertIn("D30:5", row["gold_evidence_dia_ids"])
        self.assertIn("[S30T5]", row["gold_evidence_locators"])
        self.assertEqual(row["gold_evidence_sessions"], [30])


if __name__ == "__main__":
    unittest.main()
