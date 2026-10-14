import hashlib
import json
import tempfile
import unittest
from collections import Counter
from pathlib import Path

from fs_memory_lab.question_sets import FORBIDDEN_ONLINE_KEYS
from fs_memory_lab.question_sets_v2 import (
    COMPOSITE_SET_ID,
    EXPECTED_EXTENSION_IDS,
    EXTENSION_QUOTAS,
    EXTENSION_SET_ID,
    FINAL_QUOTAS,
    build_question_sets_v2,
    verify_question_sets_v2,
)


ROOT = Path(__file__).resolve().parents[1]
PARENT_DIR = ROOT / "experiments/locomo-conv50-v1/question-sets"
QUESTION_DIR = ROOT / "experiments/locomo-conv50-v1/question-sets-main60-v2"


def load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Main60QuestionSetV2Test(unittest.TestCase):
    def test_checked_in_artifacts_pass_full_verification(self):
        result = verify_question_sets_v2(ROOT, QUESTION_DIR)
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["composite_question_set_id"], COMPOSITE_SET_ID)
        self.assertEqual(result["extension_question_set_id"], EXTENSION_SET_ID)

    def test_regeneration_is_byte_identical(self):
        with tempfile.TemporaryDirectory() as temporary:
            generated = Path(temporary) / "question-sets-main60-v2"
            result = build_question_sets_v2(ROOT, generated)
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

    def test_extension_and_composition_contract(self):
        extension_input = load_jsonl(QUESTION_DIR / "extension-20-input.jsonl")
        extension_gold = load_jsonl(QUESTION_DIR / "extension-20-gold.jsonl")
        core_input = load_jsonl(PARENT_DIR / "main-40-input.jsonl")
        core_gold = load_jsonl(PARENT_DIR / "main-40-gold.jsonl")
        dev_input = load_jsonl(PARENT_DIR / "dev-6-input.jsonl")
        composition = json.loads(
            (QUESTION_DIR / "main-60-composition.json").read_text()
        )

        self.assertEqual(len(extension_input), 20)
        self.assertEqual(len(extension_gold), 20)
        self.assertEqual(
            tuple(row["question_id"] for row in extension_input),
            EXPECTED_EXTENSION_IDS,
        )
        self.assertEqual(
            [row["question_id"] for row in extension_input],
            [row["question_id"] for row in extension_gold],
        )
        self.assertEqual(
            Counter(row["category"] for row in extension_gold),
            Counter(EXTENSION_QUOTAS),
        )
        self.assertFalse(
            any(FORBIDDEN_ONLINE_KEYS & row.keys() for row in extension_input)
        )

        core_ids = {row["question_id"] for row in core_input}
        dev_ids = {row["question_id"] for row in dev_input}
        extension_ids = {row["question_id"] for row in extension_input}
        self.assertTrue(core_ids.isdisjoint(extension_ids))
        self.assertTrue(dev_ids.isdisjoint(extension_ids))

        order = composition["question_order"]
        self.assertEqual(composition["composite_question_set_id"], COMPOSITE_SET_ID)
        self.assertEqual([row["global_position"] for row in order], list(range(1, 61)))
        self.assertEqual(
            [row["question_id"] for row in order[:40]],
            [row["question_id"] for row in core_input],
        )
        self.assertEqual(
            [row["question_id"] for row in order[40:]],
            list(EXPECTED_EXTENSION_IDS),
        )
        self.assertEqual(
            Counter(row["category"] for row in core_gold + extension_gold),
            Counter(FINAL_QUOTAS),
        )

    def test_parent_main40_artifacts_remain_byte_frozen(self):
        self.assertEqual(
            sha256(PARENT_DIR / "main-40-input.jsonl"),
            "31a65ab18797abb4491cf8de2e172050d25000eb5c1f6ddb77383d3900b757af",
        )
        self.assertEqual(
            sha256(PARENT_DIR / "main-40-gold.jsonl"),
            "a6833ca585ca26efcdd038a5cf202fd46657999053ebd7b8cc73793f7544718b",
        )


if __name__ == "__main__":
    unittest.main()
