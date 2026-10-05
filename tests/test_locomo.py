import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from fs_memory_lab.locomo import (
    OFFICIAL_DATA_BYTES,
    OFFICIAL_DATA_SHA256,
    LocomoDataError,
    parse_session_datetime,
    prepare_locomo,
    sha256_file,
)


ROOT = Path(__file__).resolve().parents[1]
RAW_PATH = ROOT / "data/raw/locomo10.json"
CANONICAL_PATH = ROOT / "data/processed/conv-50.jsonl"
SOURCE_MAP_PATH = ROOT / "data/manifests/source_map.json"
MANIFEST_PATH = ROOT / "data/manifests/locomo-conv-50-v1.json"
LICENSE_PATH = ROOT / "data/LICENSE.locomo.txt"


def load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


class LocomoPinnedDataTest(unittest.TestCase):
    def test_official_raw_file_is_pinned_exactly(self):
        self.assertEqual(RAW_PATH.stat().st_size, OFFICIAL_DATA_BYTES)
        self.assertEqual(sha256_file(RAW_PATH), OFFICIAL_DATA_SHA256)

    def test_canonical_records_and_source_map_round_trip_to_raw(self):
        dataset = json.loads(RAW_PATH.read_text(encoding="utf-8"))
        sample = next(item for item in dataset if item["sample_id"] == "conv-50")
        records = load_jsonl(CANONICAL_PATH)
        source_map = json.loads(SOURCE_MAP_PATH.read_text(encoding="utf-8"))

        self.assertEqual(len(records), 568)
        self.assertEqual(source_map["record_count"], 568)
        self.assertEqual(records[0]["locator"], "[S1T1]")
        self.assertEqual(records[-1]["locator"], "[S30T24]")

        for line_number, record in enumerate(records, start=1):
            locator = record["locator"]
            mapped = source_map["by_locator"][locator]
            raw_turn = sample["conversation"][record["session_id"]][record["turn_index"] - 1]

            self.assertEqual(record["global_turn_index"], line_number)
            self.assertEqual(mapped["jsonl_line"], line_number)
            self.assertEqual(mapped["dia_id"], record["dia_id"])
            self.assertEqual(source_map["by_dia_id"][record["dia_id"]], {
                "jsonl_line": line_number,
                "locator": locator,
            })
            self.assertEqual(raw_turn["dia_id"], record["dia_id"])
            self.assertEqual(raw_turn["speaker"], record["speaker"])
            self.assertEqual(raw_turn["text"], record["text"])
            self.assertEqual(
                hashlib.sha256(record["text"].encode("utf-8")).hexdigest(),
                record["source_sha256"],
            )
            raw_turn_payload = json.dumps(
                raw_turn,
                ensure_ascii=False,
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            self.assertEqual(
                hashlib.sha256(raw_turn_payload).hexdigest(),
                mapped["raw_turn_sha256"],
            )

            self.assertNotIn("question", record)
            self.assertNotIn("answer", record)
            self.assertNotIn("qa", record)
            self.assertNotIn("gold_answer", record)

    def test_manifest_fixes_counts_hashes_and_known_official_alias(self):
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        source_map = json.loads(SOURCE_MAP_PATH.read_text(encoding="utf-8"))

        self.assertEqual(manifest["selection"]["conversation_id"], "conv-50")
        self.assertEqual(manifest["selection"]["raw_sample_index"], 9)
        self.assertEqual(manifest["counts"]["conversation_sessions"], 30)
        self.assertEqual(manifest["counts"]["conversation_turns"], 568)
        self.assertEqual(manifest["counts"]["qa_total"], 204)
        self.assertEqual(
            manifest["counts"]["qa_by_category"],
            {"1": 32, "2": 32, "3": 7, "4": 87, "5": 46},
        )
        self.assertEqual(
            manifest["outputs"]["canonical_records"]["sha256"],
            sha256_file(CANONICAL_PATH),
        )
        self.assertEqual(
            manifest["outputs"]["source_map"]["sha256"],
            sha256_file(SOURCE_MAP_PATH),
        )
        self.assertEqual(source_map["record_sha256"], sha256_file(CANONICAL_PATH))
        self.assertEqual(source_map["record_bytes"], CANONICAL_PATH.stat().st_size)
        self.assertEqual(
            source_map["dia_id_aliases"]["D30:05"]["canonical_dia_id"],
            "D30:5",
        )
        self.assertEqual(source_map["dia_id_aliases"]["D30:05"]["locator"], "[S30T5]")

    def test_regeneration_is_cross_directory_deterministic_and_does_not_modify_raw(self):
        raw_before = RAW_PATH.read_bytes()
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            outputs = []
            reports = []
            for directory_name in ("machine-a", "machine-b"):
                output_dir = base / directory_name
                processed = output_dir / "conv-50.jsonl"
                source_map = output_dir / "source_map.json"
                manifest = output_dir / "manifest.json"
                reports.append(
                    prepare_locomo(
                        RAW_PATH,
                        processed,
                        source_map,
                        manifest,
                        license_path=LICENSE_PATH,
                    )
                )
                outputs.append(
                    (processed.read_bytes(), source_map.read_bytes(), manifest.read_bytes())
                )

        self.assertEqual(reports[0], reports[1])
        self.assertEqual(outputs[0], outputs[1])
        self.assertEqual(RAW_PATH.read_bytes(), raw_before)

    def test_jsonl_escapes_embedded_newlines_without_splitting_records(self):
        records = load_jsonl(CANONICAL_PATH)
        self.assertEqual(sum("\n" in record["text"] for record in records), 8)
        self.assertEqual(len(CANONICAL_PATH.read_text(encoding="utf-8").splitlines()), 568)

    def test_invalid_calendar_datetime_uses_data_error(self):
        with self.assertRaisesRegex(LocomoDataError, "Invalid LoCoMo session datetime"):
            parse_session_datetime("10:99 am on 31 February, 2023")

    def test_wrong_raw_hash_is_rejected_before_outputs_are_written(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            with self.assertRaisesRegex(LocomoDataError, "SHA-256 mismatch"):
                prepare_locomo(
                    RAW_PATH,
                    base / "records.jsonl",
                    base / "source-map.json",
                    base / "manifest.json",
                    expected_raw_sha256="0" * 64,
                    license_path=LICENSE_PATH,
                )
            self.assertFalse((base / "records.jsonl").exists())
            self.assertFalse((base / "source-map.json").exists())
            self.assertFalse((base / "manifest.json").exists())

    def test_license_cannot_be_an_output_and_must_match_pinned_text(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            bad_license = base / "LICENSE.txt"
            bad_license.write_text("not the official license", encoding="utf-8")
            with self.assertRaisesRegex(LocomoDataError, "does not match"):
                prepare_locomo(
                    RAW_PATH,
                    base / "records.jsonl",
                    base / "source-map.json",
                    base / "manifest.json",
                    license_path=bad_license,
                )
            with self.assertRaisesRegex(LocomoDataError, "must be distinct"):
                prepare_locomo(
                    RAW_PATH,
                    base / "records.jsonl",
                    base / "source-map.json",
                    LICENSE_PATH,
                    license_path=LICENSE_PATH,
                )


if __name__ == "__main__":
    unittest.main()
