import hashlib
import json
import tempfile
import unittest
from collections import Counter
from pathlib import Path

from fs_memory_lab.filesystem import MemoryFS
from fs_memory_lab.stores import StoreBuildError, build_s1_store


ROOT = Path(__file__).resolve().parents[1]
CANONICAL_PATH = ROOT / "data/processed/conv-50.jsonl"
SOURCE_MAP_PATH = ROOT / "data/manifests/source_map.json"
STORE_PATH = ROOT / "experiments/locomo-conv50-v1/stores/s1-flat"
MANIFEST_PATH = ROOT / "experiments/locomo-conv50-v1/manifests/s1-flat.json"

EXPECTED_CANONICAL_SHA256 = (
    "130a5a1e1b75083358ef27a98dd215a4e75c819ace6f2ee9b560ba394e0f0394"
)
EXPECTED_SOURCE_MAP_SHA256 = (
    "6e99115961bae06a48bfb7e82dbdcc18dc32ccf6c5ce57e3c266dfc7a5d4d574"
)
EXPECTED_SESSION_TURN_COUNTS = [
    19,
    21,
    18,
    28,
    15,
    18,
    19,
    14,
    21,
    17,
    14,
    17,
    19,
    16,
    15,
    25,
    10,
    16,
    12,
    17,
    18,
    14,
    18,
    23,
    31,
    15,
    13,
    43,
    18,
    24,
]


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def load_records(path: Path = CANONICAL_PATH) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def expected_turn_block(record: dict) -> str:
    parts = [f"{record['speaker']}: {record['text']}"]
    caption = record["media"]["blip_caption"]
    if caption is not None:
        parts.append(f"[Image caption: {caption}]")
    parts.append(f"{record['locator']} (dia_id: {record['dia_id']})")
    return "\n".join(parts)


def canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def expected_session_bytes(session_index: int, records: list[dict], speakers: list[str]) -> bytes:
    first = records[0]
    stem = f"session-{session_index:02d}"
    lines = [
        "---",
        f"name: {stem}",
        (
            f"description: Session {session_index} on {first['session_date']} between "
            f"{speakers[0]} and {speakers[1]}."
        ),
        "---",
        "",
        f"# Session {session_index}",
        "",
        f"Date: {first['session_datetime_raw']}",
        f"Speakers: {speakers[0]}, {speakers[1]}",
        f"Conversation: {first['conversation_id']}",
        "",
    ]
    for record in records:
        lines.extend(expected_turn_block(record).split("\n"))
        lines.append("")
    return "\n".join(lines).encode("utf-8")


class S1StoreIntegrityTest(unittest.TestCase):
    def test_checked_in_store_is_a_complete_lossless_projection(self):
        records = load_records()
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        expected_names = [f"session-{index:02d}.md" for index in range(1, 31)]
        actual_files = sorted(path for path in STORE_PATH.rglob("*") if path.is_file())

        self.assertEqual([path.relative_to(STORE_PATH).as_posix() for path in actual_files], expected_names)
        self.assertFalse(any(path.is_dir() for path in STORE_PATH.iterdir()))
        self.assertEqual(len(records), 568)
        self.assertEqual(
            [sum(record["session_index"] == index for record in records) for index in range(1, 31)],
            EXPECTED_SESSION_TURN_COUNTS,
        )
        self.assertEqual(
            manifest["counts"],
            {
                "bytes": sum(path.stat().st_size for path in actual_files),
                "files": 30,
                "sessions": 30,
                "source_turns": 568,
                "turns_with_caption": 125,
            },
        )
        self.assertEqual(len(manifest["source_index"]), 568)
        self.assertEqual(sorted(manifest["files"]), expected_names)
        self.assertEqual(manifest["input"]["canonical_sha256"], EXPECTED_CANONICAL_SHA256)
        self.assertEqual(manifest["input"]["source_map_sha256"], EXPECTED_SOURCE_MAP_SHA256)
        self.assertEqual(
            manifest["build_cost"], {"llm_calls": 0, "model_tokens": 0, "tool_calls": 0}
        )

        locator_ids: list[str] = []
        dia_ids: list[str] = []
        recovered_blocks: list[str] = []
        captions_without_url = 0
        for record in records:
            locator = record["locator"]
            entry = manifest["source_index"][locator]
            self.assertEqual(entry["dia_id"], record["dia_id"])
            self.assertEqual(entry["turn_index"], record["turn_index"])
            self.assertEqual(entry["global_turn_index"], record["global_turn_index"])
            lines = (STORE_PATH / entry["file"]).read_text(encoding="utf-8").split("\n")
            block = "\n".join(lines[entry["start_line"] - 1 : entry["end_line"]])
            self.assertEqual(block, expected_turn_block(record), locator)
            recovered_blocks.append(block)
            final_line = block.split("\n")[-1]
            parsed_locator, parsed_dia = final_line.split(" (dia_id: ", 1)
            locator_ids.append(parsed_locator)
            dia_ids.append(parsed_dia.removesuffix(")"))
            if record["media"]["blip_caption"] is not None and not record["media"]["img_url"]:
                captions_without_url += 1

        self.assertEqual(locator_ids, [record["locator"] for record in records])
        self.assertEqual(dia_ids, [record["dia_id"] for record in records])
        self.assertTrue(all(count == 1 for count in Counter(locator_ids).values()))
        self.assertTrue(all(count == 1 for count in Counter(dia_ids).values()))
        self.assertEqual(
            sum("[Image caption: " in block for block in recovered_blocks), 125
        )
        self.assertEqual(captions_without_url, 26)
        self.assertEqual(sum("\n" in record["text"] for record in records), 8)

        speakers = list(dict.fromkeys(record["speaker"] for record in records))
        for session_index, filename in enumerate(expected_names, start=1):
            session_records = [
                record for record in records if record["session_index"] == session_index
            ]
            self.assertEqual(
                (STORE_PATH / filename).read_bytes(),
                expected_session_bytes(session_index, session_records, speakers),
            )

        for filename, file_entry in manifest["files"].items():
            payload = (STORE_PATH / filename).read_bytes()
            body = payload.split(b"---\n\n", 1)[1]
            self.assertEqual(file_entry["bytes"], len(payload))
            self.assertEqual(file_entry["sha256"], sha256_bytes(payload))
            self.assertEqual(file_entry["body_bytes"], len(body))
            self.assertEqual(file_entry["body_sha256"], sha256_bytes(body))
            MemoryFS._validate(STORE_PATH / filename, payload.decode("utf-8"))

        file_hashes = {
            name: manifest["files"][name]["sha256"] for name in sorted(manifest["files"])
        }
        self.assertEqual(
            manifest["store"]["sha256"], sha256_bytes(canonical_json_bytes(file_hashes))
        )

    def test_store_renders_only_the_frozen_allowlist(self):
        records = load_records()
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        corpus = "\n".join(path.read_text(encoding="utf-8") for path in sorted(STORE_PATH.glob("*.md")))

        self.assertEqual(
            manifest["renderer"]["semantic_fields"],
            ["speaker", "text", "media.blip_caption"],
        )
        self.assertEqual(manifest["renderer"]["source_fields"], ["locator", "dia_id"])
        self.assertEqual(
            manifest["renderer"]["excluded_media_fields"],
            ["media.img_url", "media.query", "media.re-download"],
        )
        self.assertNotIn("img_url", corpus)
        self.assertNotIn("re-download", corpus)
        self.assertFalse(any("http://" in block or "https://" in block for block in map(expected_turn_block, records)))
        self.assertTrue(manifest["verification"]["gold_fields_accessed"] is False)
        self.assertTrue(manifest["verification"]["image_urls_fetched"] is False)

    def test_build_is_cross_directory_deterministic_and_idempotent(self):
        canonical_before = CANONICAL_PATH.read_bytes()
        source_map_before = SOURCE_MAP_PATH.read_bytes()
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            artifacts: list[tuple[list[bytes], bytes]] = []
            for machine_name in ("machine-a", "machine-b"):
                machine = base / machine_name
                store = machine / "stores/s1-flat"
                manifest = machine / "manifests/s1-flat.json"
                first = build_s1_store(CANONICAL_PATH, SOURCE_MAP_PATH, store, manifest)
                second = build_s1_store(CANONICAL_PATH, SOURCE_MAP_PATH, store, manifest)
                self.assertEqual(first["write_status"], "created")
                self.assertEqual(second["write_status"], "verified-existing")
                artifacts.append(
                    ([path.read_bytes() for path in sorted(store.glob("*.md"))], manifest.read_bytes())
                )

        self.assertEqual(artifacts[0], artifacts[1])
        self.assertEqual(artifacts[0][0], [path.read_bytes() for path in sorted(STORE_PATH.glob("*.md"))])
        self.assertEqual(artifacts[0][1], MANIFEST_PATH.read_bytes())
        self.assertEqual(CANONICAL_PATH.read_bytes(), canonical_before)
        self.assertEqual(SOURCE_MAP_PATH.read_bytes(), source_map_before)

    def test_existing_store_tampering_is_rejected_without_overwrite(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            store = base / "stores/s1-flat"
            manifest = base / "manifests/s1-flat.json"
            build_s1_store(CANONICAL_PATH, SOURCE_MAP_PATH, store, manifest)
            target = store / "session-01.md"
            original = target.read_bytes()
            tampered = original + b"tampered\n"
            target.write_bytes(tampered)

            with self.assertRaisesRegex(StoreBuildError, "differs from the deterministic build"):
                build_s1_store(CANONICAL_PATH, SOURCE_MAP_PATH, store, manifest)
            self.assertEqual(target.read_bytes(), tampered)

            target.write_bytes(original)
            (store / "unexpected-directory").mkdir()
            with self.assertRaisesRegex(StoreBuildError, "only flat, regular session files"):
                build_s1_store(CANONICAL_PATH, SOURCE_MAP_PATH, store, manifest)

    def test_gold_bearing_canonical_input_is_rejected_before_writing(self):
        records = load_records()
        records[0]["question"] = "This field must never enter a store."
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            canonical = base / "bad.jsonl"
            canonical.write_text(
                "".join(
                    json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                    + "\n"
                    for record in records
                ),
                encoding="utf-8",
            )
            output = base / "stores/s1-flat"
            manifest = base / "manifests/s1-flat.json"
            with self.assertRaisesRegex(StoreBuildError, "leaks gold fields"):
                build_s1_store(canonical, SOURCE_MAP_PATH, output, manifest)
            self.assertFalse(output.exists())
            self.assertFalse(manifest.exists())


if __name__ == "__main__":
    unittest.main()
