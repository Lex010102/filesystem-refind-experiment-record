import json
import unittest
from collections import Counter
from pathlib import Path

from fs_memory_lab.chapter5_stage_a import (
    E1_E7_ROW_COUNT,
    MASTER_ROW_COUNT,
    RQ1_CONDITIONS,
    RQ1_ROW_COUNT,
    audit_stage_a_output,
)


ROOT = Path(__file__).resolve().parents[1]
STAGE_A = ROOT / "artifacts/chapter5-main60-analysis-v1/stage-a"


def load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


@unittest.skipUnless((STAGE_A / "STAGE-A.PASSED").is_file(), "Stage A artifact not built")
class Chapter5StageAArtifactTests(unittest.TestCase):
    def test_independent_artifact_audit_passes(self):
        result = audit_stage_a_output(STAGE_A)
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["master_rows"], MASTER_ROW_COUNT)
        self.assertEqual(result["e1_e7_rows"], E1_E7_ROW_COUNT)
        self.assertEqual(result["rq1_rows"], RQ1_ROW_COUNT)
        self.assertTrue(result["no_api_calls"])

    def test_materialized_scopes_are_exact(self):
        master = load_jsonl(STAGE_A / "master-table.jsonl")
        e1_e7 = load_jsonl(STAGE_A / "e1-e7-main.jsonl")
        rq1 = load_jsonl(STAGE_A / "rq1-analysis-view.jsonl")
        self.assertEqual([row for row in master if row["is_e1_e7_main"]], e1_e7)
        self.assertEqual([row for row in master if row["is_rq1_analysis_row"]], rq1)
        self.assertEqual({row["condition_id"] for row in rq1}, set(RQ1_CONDITIONS))
        self.assertNotIn("E7", {row["condition_id"] for row in rq1})
        self.assertNotIn("B3-FullContext", {row["condition_id"] for row in rq1})

    def test_denominators_and_category_counts_are_not_mixed(self):
        rows = load_jsonl(STAGE_A / "master-table.jsonl")
        for answer_set, condition in sorted(
            {(row["answer_set_id"], row["condition_id"]) for row in rows}
        ):
            members = [
                row
                for row in rows
                if row["answer_set_id"] == answer_set and row["condition_id"] == condition
            ]
            self.assertEqual(len(members), 60)
            self.assertEqual(Counter(row["category"] for row in members), {1: 13, 2: 13, 3: 7, 4: 27})
            if condition.startswith("E"):
                self.assertEqual(sum(row["evidence_eligible"] for row in members), 58)
            else:
                self.assertTrue(all(row["evidence_recall"] is None for row in members))

    def test_output_never_persists_text_bearing_fields(self):
        rows = load_jsonl(STAGE_A / "master-table.jsonl")
        forbidden = {
            "question",
            "answer",
            "reference_answer",
            "candidate_answer",
            "evidence_text",
            "short_reason",
        }
        self.assertTrue(all(forbidden.isdisjoint(row) for row in rows))


if __name__ == "__main__":
    unittest.main()
