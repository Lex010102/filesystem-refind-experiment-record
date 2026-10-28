import csv
import hashlib
import json
import shutil
import tempfile
import unittest
from collections import Counter
from pathlib import Path
from unittest import mock

from fs_memory_lab import chapter5_rq5_stage1 as stage1
from fs_memory_lab.chapter5_rq5_stage1 import (
    EXPECTED_BACKBONE_CONDITION_ERRORS,
    EXPECTED_CONDITION_ERRORS,
    PROTOCOL_VERSION,
    TABLE_NAMES,
    audit_rq5_stage1_output,
    build_rq5_stage1,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
STAGE_A = REPO_ROOT / "artifacts/chapter5-main60-analysis-v1/stage-a"


def _json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _jsonl(path: Path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _kwargs(output_dir: Path):
    return {"repo_root": REPO_ROOT, "stage_a_dir": STAGE_A, "output_dir": output_dir}


class Chapter5RQ5Stage1ArtifactTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="chapter5-rq5-stage1-test-")
        cls.output = Path(cls.temp.name) / "rq5-root-cause-index"
        cls.build_result = build_rq5_stage1(**_kwargs(cls.output))
        cls.audit = _json(cls.output / "audit.json")
        cls.marker = _json(cls.output / "RQ5-STAGE-1.PASSED")
        cls.denominators = _json(cls.output / "denominator-audit.json")
        cls.state_model = _json(cls.output / "state-model.json")
        cls.tables = {name: _jsonl(cls.output / f"{name}.jsonl") for name in TABLE_NAMES}
        cls.source_rows = _jsonl(STAGE_A / "master-table.jsonl")

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_normal_build_independent_audit_hashes_and_exact_file_set(self):
        self.assertEqual(self.build_result["status"], "passed")
        self.assertEqual(self.build_result["protocol_version"], PROTOCOL_VERSION)
        audited = audit_rq5_stage1_output(**_kwargs(self.output))
        self.assertEqual(audited["status"], "passed")
        self.assertEqual(audited["audit_id"], self.audit["audit_id"])
        self.assertEqual(self.marker["audit_id"], self.audit["audit_id"])
        self.assertEqual(self.marker["audit_sha256"], _sha256(self.output / "audit.json"))
        for name, digest in self.audit["output_sha256"].items():
            self.assertEqual(_sha256(self.output / name), digest, name)

        expected = {
            "README.md", "schema.json", "state-model.json", "denominator-audit.json",
            "source-manifest.json", "audit.json", "RQ5-STAGE-1.PASSED",
        }
        for name in TABLE_NAMES:
            expected.update({f"{name}.csv", f"{name}.jsonl"})
        self.assertEqual({path.name for path in self.output.iterdir()}, expected)

    def test_population_and_strict_error_list_are_exact(self):
        cases = self.tables["case-index"]
        errors = self.tables["strict-error-cases"]
        states = self.tables["root-cause-state-register"]
        self.assertEqual(len(cases), 900)
        self.assertEqual(len(errors), 250)
        self.assertEqual(len(states), 250)
        self.assertEqual(len({row["case_id"] for row in cases}), 900)
        self.assertEqual(len({row["source_record_path"] for row in cases}), 900)
        self.assertEqual(
            [row["case_id"] for row in errors],
            [row["case_id"] for row in cases if row["strict_score"] == 0.0],
        )
        self.assertEqual([row["case_id"] for row in states], [row["case_id"] for row in errors])
        self.assertEqual(Counter(row["judge_label"] for row in errors), Counter({"partial": 74, "incorrect": 176}))
        self.assertEqual(sum(row["evidence_eligible"] for row in errors), 233)
        self.assertEqual(sum(not row["evidence_eligible"] for row in errors), 17)

    def test_error_counts_match_independent_source_reconstruction(self):
        errors = self.tables["strict-error-cases"]
        direct = [row for row in self.source_rows if float(row["strict_score"]) == 0.0]
        self.assertEqual(len(direct), len(errors))
        self.assertEqual(
            Counter(row["condition_id"] for row in errors),
            Counter(EXPECTED_CONDITION_ERRORS),
        )
        for backbone, expected in EXPECTED_BACKBONE_CONDITION_ERRORS.items():
            observed = Counter(
                row["condition_id"] for row in errors if row["packet_backbone"] == backbone
            )
            self.assertEqual(observed, Counter(expected), backbone)
        self.assertEqual(Counter(row["category_name"] for row in errors), Counter({
            "multi-hop": 58, "temporal": 60, "open-domain": 59, "single-hop": 73,
        }))
        self.assertEqual(Counter(row["access_regime"] for row in errors), Counter({
            "selective_retrieval": 205, "dual_source_fusion": 31, "full_context": 14,
        }))

    def test_question_packets_bind_same_question_counterfactuals(self):
        packets = self.tables["question-packets"]
        self.assertEqual(len(packets), 120)
        self.assertEqual(Counter(row["packet_backbone"] for row in packets), Counter({"qwen": 60, "deepseek": 60}))
        self.assertEqual(sum(row["contains_strict_error"] for row in packets), 58)
        self.assertEqual(len({row["question_id"] for row in packets if row["contains_strict_error"]}), 33)
        for row in packets:
            expected = ["E1", "E2", "E3", "E4", "E5", "E6", "E7"]
            if row["packet_backbone"] == "deepseek":
                expected.append("B3-FullContext")
            self.assertEqual(row["condition_ids"], expected)
            self.assertEqual(row["condition_count"], len(expected))
            self.assertEqual(row["strict_correct_count"] + row["strict_noncorrect_count"], len(expected))

    def test_e7_parent_linkage_and_full_context_boundary(self):
        cases = self.tables["case-index"]
        by_id = {row["case_id"]: row for row in cases}
        e7 = [row for row in cases if row["condition_id"] == "E7"]
        self.assertEqual(len(e7), 120)
        for row in e7:
            self.assertTrue(row["fusion_reuses_parent_bundles"])
            self.assertFalse(row["independent_retrieval_path"])
            self.assertEqual(by_id[row["parent_e2_case_id"]]["condition_id"], "E2")
            self.assertEqual(by_id[row["parent_e6_case_id"]]["condition_id"], "E6")
            self.assertEqual(
                row["source_bundle_ids"],
                [by_id[row["parent_e2_case_id"]]["evidence_bundle_id"], by_id[row["parent_e6_case_id"]]["evidence_bundle_id"]],
            )
        full_context = [row for row in cases if row["condition_id"] == "B3-FullContext"]
        self.assertEqual(len(full_context), 60)
        for row in full_context:
            self.assertTrue(row["full_context_path"])
            self.assertFalse(row["independent_retrieval_path"])
            self.assertIsNone(row["evidence_recall"])
            self.assertEqual(row["observable_final_input_coverage"], "source_visible_by_construction")

    def test_state_model_is_condition_aware_and_assigns_no_cause(self):
        states = self.tables["root-cause-state-register"]
        self.assertFalse(self.state_model["stage_1_assignment"]["causal_attribution_computed"])
        self.assertTrue(all(row["attribution_status"] == "pending" for row in states))
        self.assertTrue(all(row["primary_cause"] == "pending" for row in states))
        self.assertTrue(all(row["secondary_causes"] == [] for row in states))
        self.assertTrue(all(row["attribution_strength"] == "pending" for row in states))
        for row in states:
            condition = row["condition_id"]
            if condition in {"E1", "E2", "E3", "E4", "E5", "E6"}:
                self.assertEqual(row["retriever_reach_state"], "pending")
                self.assertEqual(row["model_observation_state"], "pending")
                self.assertEqual(row["parent_e2_bundle_state"], "not_applicable")
                self.assertEqual(row["parent_e6_bundle_state"], "not_applicable")
                self.assertEqual(row["fusion_operation_state"], "not_applicable")
            elif condition == "E7":
                self.assertEqual(row["store_availability_state"], "not_applicable")
                self.assertEqual(row["retriever_reach_state"], "not_applicable")
                self.assertEqual(row["parent_e2_bundle_state"], "pending")
                self.assertEqual(row["parent_e6_bundle_state"], "pending")
                self.assertEqual(row["fusion_operation_state"], "pending")
                self.assertIsNotNone(row["parent_e2_case_id"])
                self.assertIsNotNone(row["parent_e6_case_id"])
            else:
                self.assertEqual(condition, "B3-FullContext")
                self.assertEqual(row["store_availability_state"], "not_applicable")
                self.assertEqual(row["retriever_reach_state"], "not_applicable")
                self.assertEqual(row["evidence_retention_state"], "not_applicable")
                self.assertEqual(row["long_context_utilisation_state"], "pending")

            self.assertEqual(row["source_data_gate_status"], "passed")
            self.assertEqual(row["source_record_integrity_state"], "passed")
            self.assertEqual(row["question_identity_state"], "passed")
            self.assertEqual(
                row["gold_annotation_state"],
                "available" if row["evidence_eligible"] else "not_available",
            )
            self.assertEqual(row["annotated_evidence_attribution_applicable"], row["evidence_eligible"])

            chain_key = "E1-E6" if condition in {"E1", "E2", "E3", "E4", "E5", "E6"} else condition
            chain = set(self.state_model["ordered_chains"][chain_key])
            stage_fields = {
                "store_availability": "store_availability_state",
                "retriever_reach": "retriever_reach_state",
                "model_observation": "model_observation_state",
                "evidence_retention": "evidence_retention_state",
                "parent_e2_bundle": "parent_e2_bundle_state",
                "parent_e6_bundle": "parent_e6_bundle_state",
                "fusion_operation": "fusion_operation_state",
                "final_input_sufficiency": "final_input_sufficiency_state",
                "long_context_utilisation": "long_context_utilisation_state",
                "answerer_utilisation": "answerer_utilisation_state",
                "evaluation_agreement": "evaluation_agreement_state",
            }
            for stage, field in stage_fields.items():
                self.assertEqual(row[field], "pending" if stage in chain else "not_applicable")

        self.assertEqual(
            set(self.state_model["stage_definitions"]),
            {
                stage
                for chain in self.state_model["ordered_chains"].values()
                for stage in chain
            },
        )
        for definition in self.state_model["stage_definitions"].values():
            self.assertTrue(definition["terminal_values"])
            self.assertIn("indeterminate", definition["terminal_values"])
        self.assertEqual(
            self.state_model["attribution_contract"]["strength_values"],
            ["direct", "convergent", "indeterminate"],
        )

    def test_denominator_audit_and_census_partition_population(self):
        census = self.tables["error-census"]
        self.assertEqual(sum(row["population_n"] for row in census), 900)
        self.assertEqual(sum(row["strict_noncorrect_n"] for row in census), 250)
        self.assertEqual(self.denominators["population_rows"], 900)
        self.assertEqual(self.denominators["strict_correct_rows"], 650)
        self.assertEqual(self.denominators["partial_rows"], 74)
        self.assertEqual(self.denominators["incorrect_rows"], 176)
        self.assertEqual(self.denominators["strict_noncorrect_evidence_eligible"], 233)
        self.assertEqual(self.denominators["strict_noncorrect_evidence_ineligible"], 17)
        self.assertEqual(self.denominators["question_packets_with_error"], 58)
        self.assertEqual(self.denominators["unique_error_question_ids"], 33)

    def test_published_artifact_is_text_and_secret_free(self):
        forbidden = stage1.FORBIDDEN_FIELDS
        fragments = stage1.SECRET_FIELD_FRAGMENTS
        for table in self.tables.values():
            for row in table:
                for field in row:
                    lowered = field.lower()
                    self.assertNotIn(lowered, forbidden)
                    self.assertFalse(any(fragment in lowered for fragment in fragments))
        readme = (self.output / "README.md").read_text(encoding="utf-8")
        self.assertIn("does not assign a root", readme)
        self.assertFalse(self.audit["causal_stage_attribution_computed"])

    def test_csv_and_jsonl_tables_have_matching_rows_and_headers(self):
        for name in TABLE_NAMES:
            with (self.output / f"{name}.csv").open(encoding="utf-8", newline="") as handle:
                csv_rows = list(csv.DictReader(handle))
            json_rows = self.tables[name]
            self.assertEqual(len(csv_rows), len(json_rows), name)
            self.assertEqual(set(csv_rows[0]), set(json_rows[0]), name)

    def test_reversed_stage_a_rows_produce_byte_identical_payloads(self):
        with tempfile.TemporaryDirectory(prefix="rq5-stage1-order-") as tmp:
            target = Path(tmp) / "artifact"
            original_reader = stage1._read_jsonl

            def reversed_master(path: Path):
                rows = original_reader(path)
                return list(reversed(rows)) if path.name == "master-table.jsonl" else rows

            with mock.patch.object(stage1, "_read_jsonl", side_effect=reversed_master):
                build_rq5_stage1(**_kwargs(target))
            self.assertEqual({path.name for path in target.iterdir()}, {path.name for path in self.output.iterdir()})
            for source in self.output.iterdir():
                self.assertEqual(source.read_bytes(), (target / source.name).read_bytes(), source.name)

    def test_existing_output_is_never_overwritten(self):
        with self.assertRaises(ValueError):
            build_rq5_stage1(**_kwargs(self.output))

    def test_invalid_source_path_and_hash_are_rejected(self):
        original_reader = stage1._read_jsonl
        for mode in ("path", "hash"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory(prefix=f"rq5-stage1-{mode}-") as tmp:
                target = Path(tmp) / "artifact"

                def mutated_master(path: Path, mode=mode):
                    rows = original_reader(path)
                    if path.name == "master-table.jsonl":
                        rows = [dict(row) for row in rows]
                        if mode == "path":
                            rows[0]["source_record_path"] = "../escape.json"
                        else:
                            rows[0]["source_record_file_sha256"] = "0" * 64
                    return rows

                with mock.patch.object(stage1, "_read_jsonl", side_effect=mutated_master):
                    with self.assertRaises(ValueError):
                        build_rq5_stage1(**_kwargs(target))
                self.assertFalse(target.exists())

    def test_tamper_missing_extra_and_symlink_are_rejected(self):
        for case in ("tamper", "missing", "extra", "symlink"):
            with self.subTest(case=case), tempfile.TemporaryDirectory(prefix=f"rq5-stage1-{case}-") as tmp:
                target = Path(tmp) / "artifact"
                shutil.copytree(self.output, target)
                if case == "tamper":
                    path = target / "strict-error-cases.csv"
                    path.write_bytes(path.read_bytes() + b"tamper")
                elif case == "missing":
                    (target / "root-cause-state-register.jsonl").unlink()
                elif case == "extra":
                    (target / "unexpected.txt").write_text("extra", encoding="utf-8")
                else:
                    path = target / "state-model.json"
                    path.unlink()
                    path.symlink_to(self.output / "state-model.json")
                with self.assertRaises(ValueError):
                    audit_rq5_stage1_output(**_kwargs(target))


if __name__ == "__main__":
    unittest.main()
