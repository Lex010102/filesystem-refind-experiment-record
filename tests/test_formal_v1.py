import json
import tempfile
import unittest
from pathlib import Path

from fs_memory_lab.evidence import EvidenceValidationError
from fs_memory_lab.formal_v1 import (
    FORMAL_EVIDENCE_BUDGET_LIMIT,
    FORMAL_SERVED_MODEL,
    formal_manifest_body,
    verify_formal_manifest,
    write_formal_manifest,
)


ROOT = Path(__file__).resolve().parents[1]
FAKE_COMMIT = "1" * 40


class FormalV1Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.body = formal_manifest_body(ROOT, FAKE_COMMIT)

    def test_contract_has_frozen_main40_shape(self):
        body = self.body
        self.assertEqual(body["question_set"]["question_count"], 40)
        self.assertEqual(len(body["question_set"]["question_order"]), 40)
        self.assertEqual(len(body["question_set"]["execution_order"]), 280)
        self.assertEqual(
            body["retrieval"]["evidence_budget"]["single_source_limit"],
            FORMAL_EVIDENCE_BUDGET_LIMIT,
        )
        self.assertEqual(
            body["retrieval"]["r1"]["round_cap_by_condition"],
            {"E1": 20, "E3": 20, "E5": 40},
        )
        self.assertEqual(body["retrieval"]["r2"]["action_cap"], 4)
        self.assertEqual(body["retrieval"]["r3"]["action_cap"], 4)
        self.assertEqual(body["deployment"]["required_served_model"], FORMAL_SERVED_MODEL)
        self.assertFalse(body["scoring"]["anonymous_llm_judge"]["enabled"])

    def test_write_and_verify_round_trip_and_reject_overwrite(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as folder:
            path = Path(folder) / "manifest.json"
            write_formal_manifest(
                ROOT, implementation_commit=FAKE_COMMIT, destination=path
            )
            result = verify_formal_manifest(ROOT, path)
            self.assertEqual(result["status"], "verified")
            self.assertEqual(result["planned_records"], 280)
            with self.assertRaises(EvidenceValidationError):
                write_formal_manifest(
                    ROOT, implementation_commit=FAKE_COMMIT, destination=path
                )

    def test_tamper_is_rejected(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as folder:
            path = Path(folder) / "manifest.json"
            write_formal_manifest(
                ROOT, implementation_commit=FAKE_COMMIT, destination=path
            )
            value = json.loads(path.read_text(encoding="utf-8"))
            value["retrieval"]["evidence_budget"]["single_source_limit"] = 1
            path.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaises(EvidenceValidationError):
                verify_formal_manifest(ROOT, path)


if __name__ == "__main__":
    unittest.main()
