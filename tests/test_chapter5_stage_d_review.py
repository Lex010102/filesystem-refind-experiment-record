from __future__ import annotations

import copy
import hashlib
import json
import shutil
import tempfile
import unittest
from collections import Counter
from pathlib import Path

from fs_memory_lab.chapter5_stage_d_review import (
    EXPECTED_REVIEW_COUNT,
    PUBLIC_FIELDS,
    STAGE_D_REVIEW_PROTOCOL_VERSION,
    _assemble_stage_d_review,
    _normalise_reviews,
    _question_source_paths,
    _safe_repo_path,
    _slot,
    audit_stage_d_review,
    build_stage_d_review,
)
from fs_memory_lab.evidence import EvidenceValidationError


REPO_ROOT = Path(__file__).resolve().parents[1]
FROZEN_ROOT = REPO_ROOT / "artifacts/chapter5-main60-analysis-v1"
AUTO = FROZEN_ROOT / "stage-d-auto"
FINAL = FROZEN_ROOT / "stage-d"


def _jsonl(path: Path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _review_rows(candidates):
    rows = []
    for candidate in candidates:
        paths = set(candidate["source_record_paths"])
        paths.update(_question_source_paths(candidate["question_id"]))
        paths.update({
            "data/processed/conv-50.jsonl",
            "data/manifests/source_map.json",
        })
        conditions = set(candidate["condition_ids"])
        if conditions & {"E1", "E2"}:
            paths.add("experiments/locomo-conv50-v1/stores/s1-flat")
        if conditions & {"E3", "E4"}:
            paths.add("experiments/locomo-conv50-v1/stores/s2-foldered")
        if conditions & {"E5", "E6"}:
            paths.add("experiments/locomo-conv50-v1/stores/s3-curated")
        rows.append({
            "review_id": "draft-only",
            "trace_candidate_id": candidate["trace_candidate_id"],
            "slot_id": _slot(candidate),
            "backbone_id": candidate["backbone_id"],
            "comparison_id": candidate["comparison_id"],
            "question_id": candidate["question_id"],
            "category": candidate["category"],
            "intended_case_type": candidate["candidate_role"],
            "observed_case_type": candidate["candidate_role"],
            "storage_status": "preserved",
            "retrieval_status": "sufficient",
            "packaging_status": "preserved",
            "evidence_sufficiency": "sufficient",
            "answerer_utilisation": "correct_use",
            "evaluation_agreement": "agreement",
            "primary_mechanism": "indeterminate",
            "secondary_mechanism": "none",
            "confidence": "low",
            "concise_finding": "The bounded trace supports only an indeterminate mechanism in this synthetic validation row.",
            "uncertainty": "This row validates the publication contract and is not a substantive case interpretation.",
            "source_paths_checked": sorted(paths),
            "review_status": "completed",
            "manual_content_inspected": True,
        })
    return rows


class Chapter5StageDReviewInputTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.candidates = _jsonl(AUTO / "trace-review-candidates.jsonl")
        cls.rows = _review_rows(cls.candidates)

    def test_exact_candidate_set_normalises_deterministically(self):
        first, bindings = _normalise_reviews(
            repo_root=REPO_ROOT,
            candidates=self.candidates,
            review_rows=self.rows,
        )
        second, bindings2 = _normalise_reviews(
            repo_root=REPO_ROOT,
            candidates=self.candidates,
            review_rows=list(reversed(self.rows)),
        )
        self.assertEqual(first, second)
        self.assertEqual(bindings, bindings2)
        self.assertEqual(len(first), EXPECTED_REVIEW_COUNT)
        self.assertEqual(len({row["review_id"] for row in first}), EXPECTED_REVIEW_COUNT)
        self.assertTrue(all(tuple(row) == PUBLIC_FIELDS for row in first))
        self.assertTrue(all(row["review_status"] == "completed" for row in first))
        self.assertTrue(all(row["manual_content_inspected"] is True for row in first))
        self.assertEqual(
            Counter((row["module_id"], row["backbone_id"], row["intended_case_type"]) for row in first),
            Counter(
                (module, backbone, role)
                for module in ("5.2.1", "5.2.2", "5.2.3", "5.2.4")
                for backbone in ("qwen", "deepseek")
                for role in ("repair", "harm", "counterexample")
            ),
        )

    def test_missing_or_substituted_candidate_is_rejected(self):
        with self.assertRaises(EvidenceValidationError):
            _normalise_reviews(
                repo_root=REPO_ROOT,
                candidates=self.candidates,
                review_rows=self.rows[:-1],
            )
        tampered = copy.deepcopy(self.rows)
        tampered[0]["question_id"] = "conv-50-q999"
        with self.assertRaises(EvidenceValidationError):
            _normalise_reviews(repo_root=REPO_ROOT, candidates=self.candidates, review_rows=tampered)

    def test_prohibited_text_field_is_rejected(self):
        tampered = copy.deepcopy(self.rows)
        tampered[0]["question"] = "raw text must not enter the public register"
        with self.assertRaises(EvidenceValidationError):
            _normalise_reviews(repo_root=REPO_ROOT, candidates=self.candidates, review_rows=tampered)

    def test_missing_declared_store_or_gold_source_is_rejected(self):
        tampered = copy.deepcopy(self.rows)
        tampered[0]["source_paths_checked"] = [
            path for path in tampered[0]["source_paths_checked"]
            if "stores/s1-flat" not in path
        ]
        with self.assertRaises(EvidenceValidationError):
            _normalise_reviews(repo_root=REPO_ROOT, candidates=self.candidates, review_rows=tampered)
        tampered = copy.deepcopy(self.rows)
        tampered[0]["source_paths_checked"] = [
            path for path in tampered[0]["source_paths_checked"]
            if not path.endswith("main-40-gold.jsonl")
        ]
        with self.assertRaises(EvidenceValidationError):
            _normalise_reviews(repo_root=REPO_ROOT, candidates=self.candidates, review_rows=tampered)

    def test_frozen_source_record_hash_change_is_rejected(self):
        candidates = copy.deepcopy(self.candidates)
        candidates[0]["source_record_file_sha256"][0] = "0" * 64
        with self.assertRaises(EvidenceValidationError):
            _normalise_reviews(repo_root=REPO_ROOT, candidates=candidates, review_rows=self.rows)

    def test_completion_attestations_are_required(self):
        for field in ("review_status", "manual_content_inspected"):
            tampered = copy.deepcopy(self.rows)
            del tampered[0][field]
            with self.subTest(field=field), self.assertRaises(EvidenceValidationError):
                _normalise_reviews(repo_root=REPO_ROOT, candidates=self.candidates, review_rows=tampered)

    def test_noncanonical_store_prefix_cannot_bypass_store_check(self):
        tampered = copy.deepcopy(self.rows)
        prefix = "experiments/locomo-conv50-v1/stores/s1-flat"
        tampered[0]["source_paths_checked"] = [
            path for path in tampered[0]["source_paths_checked"] if path != prefix
        ]
        tampered[0]["source_paths_checked"].append(
            prefix + "/../../question-sets/main-40-input.jsonl"
        )
        tampered[0]["source_paths_checked"].sort()
        with self.assertRaises(EvidenceValidationError):
            _normalise_reviews(repo_root=REPO_ROOT, candidates=self.candidates, review_rows=tampered)

    def test_safe_repo_path_rejects_absolute_dot_parent_and_symlink_components(self):
        with tempfile.TemporaryDirectory(prefix="chapter5-stage-d-path-test-") as temp:
            root = Path(temp).resolve()
            (root / "real").mkdir()
            (root / "real" / "source.txt").write_text("source", encoding="utf-8")
            (root / "linked").symlink_to(root / "real", target_is_directory=True)
            unsafe = (
                str(root / "real" / "source.txt"),
                "real/./source.txt",
                "real/../real/source.txt",
                "linked/source.txt",
            )
            for path in unsafe:
                with self.subTest(path=path), self.assertRaises((EvidenceValidationError, ValueError)):
                    _safe_repo_path(root, path)


class Chapter5StageDPrepublicationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="chapter5-stage-d-prepublication-")
        cls.target = Path(cls.temporary.name) / "stage-d"
        cls.target.mkdir()
        cls.candidates = _jsonl(AUTO / "trace-review-candidates.jsonl")
        cls.rows = _review_rows(cls.candidates)
        cls.result = _assemble_stage_d_review(
            repo_root=REPO_ROOT,
            auto_dir=AUTO,
            review_rows=cls.rows,
            output_dir=cls.target,
        )

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def _tampered_copy(self, name):
        root = Path(self.temporary.name) / name
        shutil.copytree(self.target, root)
        return root

    def test_prepublication_assembly_audits_without_formal_output(self):
        self.assertEqual(self.result["status"], "passed")
        result = audit_stage_d_review(repo_root=REPO_ROOT, auto_dir=AUTO, output_dir=self.target)
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["review_count"], EXPECTED_REVIEW_COUNT)

    def test_public_builder_keeps_the_frozen_destination_constraint(self):
        review_input = Path(self.temporary.name) / "review-input.jsonl"
        review_input.write_text(
            "".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in self.rows),
            encoding="utf-8",
        )
        unsafe_destination = Path(self.temporary.name) / "non-frozen-stage-d"
        with self.assertRaises(EvidenceValidationError):
            build_stage_d_review(
                repo_root=REPO_ROOT,
                auto_dir=AUTO,
                review_input=review_input,
                output_dir=unsafe_destination,
            )
        self.assertFalse(unsafe_destination.exists())

    def test_exact_file_set_auto_bytes_and_marker_semantics(self):
        auto_names = {path.name for path in AUTO.iterdir()}
        extra_names = {
            "trace-review-register.jsonl", "trace-review-register.csv", "trace-review-casebook.md",
            "review-schema.json", "review-source-manifest.json", "final-audit.json", "STAGE-D.PASSED",
        }
        self.assertEqual({path.name for path in self.target.iterdir()}, auto_names | extra_names)
        for source in AUTO.iterdir():
            self.assertEqual(source.read_bytes(), (self.target / source.name).read_bytes(), source.name)

        audit_payload = (self.target / "final-audit.json").read_bytes()
        audit = json.loads(audit_payload)
        marker = json.loads((self.target / "STAGE-D.PASSED").read_bytes())
        self.assertEqual(marker["status"], "passed")
        self.assertEqual(marker["audit_id"], audit["audit_id"])
        self.assertEqual(marker["audit_sha256"], hashlib.sha256(audit_payload).hexdigest())
        self.assertTrue(marker["manual_trace_review_completed"])
        self.assertTrue(marker["all_frozen_candidates_reviewed"])
        self.assertEqual(marker["review_count"], EXPECTED_REVIEW_COUNT)

    def test_review_auto_file_marker_and_extra_file_tampering_are_rejected(self):
        review_target = self._tampered_copy("tampered-review")
        payload = (review_target / "trace-review-register.jsonl").read_text(encoding="utf-8")
        self.assertIn('"confidence":"low"', payload)
        (review_target / "trace-review-register.jsonl").write_text(
            payload.replace('"confidence":"low"', '"confidence":"medium"', 1),
            encoding="utf-8",
        )
        with self.assertRaises(EvidenceValidationError):
            audit_stage_d_review(repo_root=REPO_ROOT, auto_dir=AUTO, output_dir=review_target)

        auto_target = self._tampered_copy("tampered-auto")
        auto_name = sorted(path.name for path in AUTO.iterdir())[0]
        with (auto_target / auto_name).open("ab") as stream:
            stream.write(b"\n")
        with self.assertRaises(EvidenceValidationError):
            audit_stage_d_review(repo_root=REPO_ROOT, auto_dir=AUTO, output_dir=auto_target)

        marker_target = self._tampered_copy("tampered-marker")
        with (marker_target / "STAGE-D.PASSED").open("ab") as stream:
            stream.write(b"\n")
        with self.assertRaises(EvidenceValidationError):
            audit_stage_d_review(repo_root=REPO_ROOT, auto_dir=AUTO, output_dir=marker_target)

        extra_target = self._tampered_copy("tampered-extra")
        (extra_target / "unexpected.txt").write_text("unexpected", encoding="utf-8")
        with self.assertRaises(EvidenceValidationError):
            audit_stage_d_review(repo_root=REPO_ROOT, auto_dir=AUTO, output_dir=extra_target)


@unittest.skipUnless((FINAL / "STAGE-D.PASSED").is_file(), "final Stage D artifact not built")
class Chapter5StageDFinalArtifactTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = _jsonl(FINAL / "trace-review-register.jsonl")

    def test_independent_final_audit(self):
        result = audit_stage_d_review(repo_root=REPO_ROOT, auto_dir=AUTO, output_dir=FINAL)
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["protocol_version"], STAGE_D_REVIEW_PROTOCOL_VERSION)
        self.assertEqual(result["review_count"], EXPECTED_REVIEW_COUNT)
        self.assertTrue(result["all_frozen_candidates_reviewed"])
        self.assertTrue(result["manual_trace_review_completed"])
        self.assertTrue(result["final_stage_d_marker_emitted"])

    def test_auto_bytes_are_unchanged_and_review_rows_are_bounded(self):
        for source in AUTO.iterdir():
            self.assertEqual(source.read_bytes(), (FINAL / source.name).read_bytes(), source.name)
        self.assertEqual(len(self.rows), EXPECTED_REVIEW_COUNT)
        # Canonical JSON serialisation sorts object keys.  The public contract
        # is the exact field set; insertion order is validated before writing.
        self.assertTrue(all(set(row) == set(PUBLIC_FIELDS) for row in self.rows))
        prohibited = {"question", "reference_answer", "candidate_answer", "answer", "evidence", "judge_rationale"}
        self.assertTrue(all(prohibited.isdisjoint(row) for row in self.rows))
        self.assertTrue(all(not path.startswith("/") for row in self.rows for path in row["source_paths_checked"]))

    def test_tampering_is_rejected(self):
        with tempfile.TemporaryDirectory(prefix="chapter5-stage-d-review-test-") as temp:
            target = Path(temp) / "stage-d"
            shutil.copytree(FINAL, target)
            payload = (target / "trace-review-register.jsonl").read_text(encoding="utf-8")
            (target / "trace-review-register.jsonl").write_text(payload.replace("high", "low", 1), encoding="utf-8")
            with self.assertRaises(EvidenceValidationError):
                audit_stage_d_review(repo_root=REPO_ROOT, auto_dir=AUTO, output_dir=target)


if __name__ == "__main__":
    unittest.main()
