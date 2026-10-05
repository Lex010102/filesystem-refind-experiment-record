import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import fs_memory_lab.s3_chunks as s3_chunks_module
from fs_memory_lab.s3_chunks import (
    SESSION_HEADER_TEMPLATE,
    S3ChunkBuildError,
    _canonical_json_bytes,
    build_s3_management_chunks,
    chunk_session_records,
    render_chunk_text,
)
from fs_memory_lab.stores import render_source_turn


ROOT = Path(__file__).resolve().parents[1]
CANONICAL_PATH = ROOT / "data/processed/conv-50.jsonl"
STREAM_PATH = ROOT / "experiments/locomo-conv50-v1/streams/s3-management-v1"
MANIFEST_PATH = (
    ROOT / "experiments/locomo-conv50-v1/manifests/s3-management-stream.json"
)

EXPECTED_CANONICAL_SHA256 = (
    "130a5a1e1b75083358ef27a98dd215a4e75c819ace6f2ee9b560ba394e0f0394"
)
EXPECTED_STREAM_SHA256 = (
    "f599b8d35f55ac08b68595f728aaa7a20f30e14a529c7dcb0f1631857b6594ec"
)
EXPECTED_MANIFEST_SHA256 = (
    "6323382879ddafdb21c1207bf22a3d11c277d323faabfa28d1ae3144e78025d5"
)
EXPECTED_SESSION_CHUNK_COUNTS = [
    3,
    3,
    3,
    4,
    2,
    3,
    3,
    2,
    3,
    3,
    2,
    3,
    3,
    2,
    2,
    4,
    2,
    2,
    2,
    3,
    3,
    2,
    3,
    3,
    4,
    2,
    2,
    6,
    3,
    3,
]


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def load_records(path: Path = CANONICAL_PATH) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def make_record(
    turn_index: int,
    text: str,
    *,
    session_index: int = 1,
    session_date: str = "2023-01-01",
) -> dict:
    return {
        "session_index": session_index,
        "session_date": session_date,
        "turn_index": turn_index,
        "locator": f"[S{session_index}T{turn_index}]",
        "dia_id": f"D{session_index}:{turn_index}",
        "speaker": "Alice" if turn_index % 2 else "Bob",
        "text": text,
        "media": {"blip_caption": None},
    }


class S3ChunkIntegrityTest(unittest.TestCase):
    def test_checked_in_stream_is_lossless_and_within_both_caps(self):
        records = load_records()
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        actual_files = sorted(path for path in STREAM_PATH.iterdir() if path.is_file())
        expected_names = [chunk["filename"] for chunk in manifest["chunks"]]

        self.assertEqual(len(records), 568)
        self.assertEqual(len(actual_files), 85)
        self.assertEqual([path.name for path in actual_files], sorted(expected_names))
        self.assertEqual(manifest["input"]["canonical_sha256"], EXPECTED_CANONICAL_SHA256)
        self.assertEqual(
            manifest["input"]["expected_canonical_sha256"], EXPECTED_CANONICAL_SHA256
        )
        self.assertEqual(
            sha256_bytes(MANIFEST_PATH.read_bytes()), EXPECTED_MANIFEST_SHA256
        )
        self.assertEqual(manifest["counts"]["chunks"], 85)
        self.assertEqual(manifest["counts"]["sessions"], 30)
        self.assertEqual(manifest["counts"]["source_turns"], 568)
        self.assertEqual(manifest["counts"]["turns_with_caption"], 125)
        self.assertEqual(
            [
                sum(chunk["session_index"] == index for chunk in manifest["chunks"])
                for index in range(1, 31)
            ],
            EXPECTED_SESSION_CHUNK_COUNTS,
        )

        recovered_locators: list[str] = []
        recovered_global_indices: list[int] = []
        caption_count = 0
        for chunk in manifest["chunks"]:
            path = STREAM_PATH / chunk["filename"]
            payload = path.read_bytes()
            text = payload.decode("utf-8")
            self.assertFalse(text.endswith("\n"))
            self.assertEqual(len(text), chunk["characters"])
            self.assertEqual(len(payload), chunk["bytes"])
            self.assertEqual(sha256_bytes(payload), chunk["sha256"])
            self.assertLessEqual(chunk["turn_count"], 8)
            self.assertLessEqual(chunk["characters"], 3000)
            self.assertEqual(
                text.split("\n\n", 1)[0],
                SESSION_HEADER_TEMPLATE.format(
                    session_index=chunk["session_index"],
                    session_date=chunk["session_date"],
                ),
            )
            self.assertEqual(len(chunk["locators"]), chunk["turn_count"])
            self.assertEqual(len(chunk["dia_ids"]), chunk["turn_count"])
            for locator in chunk["locators"]:
                entry = manifest["source_index"][locator]
                record = records[entry["global_turn_index"] - 1]
                expected_block = render_source_turn(record)
                self.assertEqual(entry["chunk_file"], chunk["filename"])
                self.assertEqual(entry["session_index"], chunk["session_index"])
                self.assertEqual(
                    text[entry["start_character"] : entry["end_character_exclusive"]],
                    expected_block,
                )
                self.assertEqual(
                    payload[entry["start_byte"] : entry["end_byte_exclusive"]],
                    expected_block.encode("utf-8"),
                )
                self.assertEqual(
                    entry["rendered_sha256"],
                    sha256_bytes(expected_block.encode("utf-8")),
                )
                recovered_locators.append(locator)
                recovered_global_indices.append(entry["global_turn_index"])
                caption_count += int(record["media"]["blip_caption"] is not None)

        self.assertEqual(recovered_locators, [record["locator"] for record in records])
        self.assertEqual(recovered_global_indices, list(range(1, 569)))
        self.assertEqual(len(set(recovered_locators)), 568)
        self.assertEqual(caption_count, 125)
        self.assertEqual(len(manifest["source_index"]), 568)
        self.assertEqual(
            manifest["counts"]["characters"],
            sum(chunk["characters"] for chunk in manifest["chunks"]),
        )
        self.assertEqual(
            manifest["counts"]["bytes"],
            sum(chunk["bytes"] for chunk in manifest["chunks"]),
        )
        self.assertGreater(manifest["counts"]["bytes"], manifest["counts"]["characters"])
        self.assertEqual(
            manifest["stream"]["sha256"],
            sha256_bytes(_canonical_json_bytes(manifest["stream"]["ordered_index"])),
        )
        self.assertEqual(manifest["stream"]["sha256"], EXPECTED_STREAM_SHA256)
        self.assertEqual(
            manifest["build_cost"],
            {"llm_calls": 0, "model_tokens": 0, "tool_calls": 0},
        )
        self.assertTrue(manifest["verification"]["all_source_turns_covered_once"])
        self.assertTrue(manifest["verification"]["canonical_order_preserved"])
        self.assertFalse(manifest["verification"]["gold_inputs_read"])
        self.assertFalse(manifest["verification"]["image_urls_fetched"])

    def test_stream_contains_only_the_frozen_model_visible_projection(self):
        records = load_records()
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        corpus = "\n".join(path.read_text(encoding="utf-8") for path in sorted(STREAM_PATH.iterdir()))

        self.assertEqual(
            manifest["renderer"]["semantic_fields"],
            ["speaker", "text", "media.blip_caption"],
        )
        self.assertEqual(
            manifest["renderer"]["excluded_media_fields"],
            ["media.img_url", "media.query", "media.re-download"],
        )
        self.assertNotIn("img_url", corpus)
        self.assertNotIn("re-download", corpus)
        self.assertFalse(
            any(
                "http://" in render_source_turn(record)
                or "https://" in render_source_turn(record)
                for record in records
            )
        )
        self.assertEqual(sum("\n" in record["text"] for record in records), 8)

    def test_build_is_cross_directory_deterministic_and_idempotent(self):
        canonical_before = CANONICAL_PATH.read_bytes()
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            artifacts: list[tuple[list[bytes], bytes]] = []
            for machine_name in ("machine-a", "machine-b"):
                machine = base / machine_name
                stream = machine / "streams/s3-management-v1"
                manifest = machine / "manifests/s3-management-stream.json"
                first = build_s3_management_chunks(CANONICAL_PATH, stream, manifest)
                second = build_s3_management_chunks(CANONICAL_PATH, stream, manifest)
                self.assertEqual(first["write_status"], "created")
                self.assertEqual(second["write_status"], "verified-existing")
                artifacts.append(
                    (
                        [path.read_bytes() for path in sorted(stream.iterdir())],
                        manifest.read_bytes(),
                    )
                )

        self.assertEqual(artifacts[0], artifacts[1])
        self.assertEqual(
            artifacts[0][0], [path.read_bytes() for path in sorted(STREAM_PATH.iterdir())]
        )
        self.assertEqual(artifacts[0][1], MANIFEST_PATH.read_bytes())
        self.assertEqual(CANONICAL_PATH.read_bytes(), canonical_before)

    def test_existing_artifact_tampering_is_rejected_without_overwrite(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            stream = base / "streams/s3-management-v1"
            manifest = base / "manifests/s3-management-stream.json"
            build_s3_management_chunks(CANONICAL_PATH, stream, manifest)
            chunk = stream / "session_01_chunk_01.txt"
            original_chunk = chunk.read_bytes()
            chunk.write_bytes(original_chunk + b"tampered")
            with self.assertRaisesRegex(S3ChunkBuildError, "differs"):
                build_s3_management_chunks(CANONICAL_PATH, stream, manifest)
            self.assertEqual(chunk.read_bytes(), original_chunk + b"tampered")

            chunk.write_bytes(original_chunk)
            original_manifest = manifest.read_bytes()
            manifest.write_bytes(original_manifest + b"tampered")
            with self.assertRaisesRegex(S3ChunkBuildError, "manifest differs"):
                build_s3_management_chunks(CANONICAL_PATH, stream, manifest)
            self.assertEqual(manifest.read_bytes(), original_manifest + b"tampered")

    def test_extra_symlink_and_half_published_artifacts_fail_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            stream = base / "streams/s3-management-v1"
            manifest = base / "manifests/s3-management-stream.json"
            build_s3_management_chunks(CANONICAL_PATH, stream, manifest)

            extra = stream / "unexpected.txt"
            extra.write_text("unexpected", encoding="utf-8")
            with self.assertRaisesRegex(S3ChunkBuildError, "missing or unexpected"):
                build_s3_management_chunks(CANONICAL_PATH, stream, manifest)
            extra.unlink()

            link = stream / "unexpected-link.txt"
            link.symlink_to(stream / "session_01_chunk_01.txt")
            with self.assertRaisesRegex(S3ChunkBuildError, "only regular chunk files"):
                build_s3_management_chunks(CANONICAL_PATH, stream, manifest)
            link.unlink()

            frozen_stream = [path.read_bytes() for path in sorted(stream.iterdir())]
            manifest.unlink()
            with self.assertRaisesRegex(S3ChunkBuildError, "must either both be absent"):
                build_s3_management_chunks(CANONICAL_PATH, stream, manifest)
            self.assertEqual(
                [path.read_bytes() for path in sorted(stream.iterdir())], frozen_stream
            )
            self.assertFalse(manifest.exists())

    def test_manifest_publish_failure_rolls_back_new_stream(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            stream = base / "streams/s3-management-v1"
            manifest = base / "manifests/s3-management-stream.json"
            real_replace = os.replace
            call_count = 0

            def fail_second_replace(source, destination):
                nonlocal call_count
                call_count += 1
                if call_count == 2:
                    raise OSError("simulated manifest publish failure")
                return real_replace(source, destination)

            with patch.object(
                s3_chunks_module.os, "replace", side_effect=fail_second_replace
            ):
                with self.assertRaisesRegex(OSError, "simulated manifest publish failure"):
                    build_s3_management_chunks(CANONICAL_PATH, stream, manifest)

            self.assertEqual(call_count, 2)
            self.assertFalse(stream.exists())
            self.assertFalse(manifest.exists())
            self.assertEqual(list((base / "streams").iterdir()), [])
            self.assertEqual(list((base / "manifests").iterdir()), [])

    def test_extra_fields_and_oversize_turns_fail_before_output(self):
        records = load_records()
        records[0]["gold_sentinel"] = "must-not-pass-the-closed-allowlist"
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
            stream = base / "streams/s3-management-v1"
            manifest = base / "manifests/s3-management-stream.json"
            with self.assertRaisesRegex(S3ChunkBuildError, "closed field allowlist"):
                build_s3_management_chunks(
                    canonical,
                    stream,
                    manifest,
                    expected_canonical_sha256=None,
                )
            self.assertFalse(stream.exists())
            self.assertFalse(manifest.exists())

            with self.assertRaisesRegex(S3ChunkBuildError, "SHA-256 mismatch"):
                build_s3_management_chunks(canonical, stream, manifest)
            self.assertFalse(stream.exists())
            self.assertFalse(manifest.exists())

        oversize = make_record(1, "x" * 3100)
        with self.assertRaisesRegex(S3ChunkBuildError, "cannot fit"):
            chunk_session_records([oversize])

    def test_character_boundary_unicode_and_embedded_newlines(self):
        first = make_record(1, "short\n\nstill the same source turn")
        second = make_record(2, "x")
        base_length = len(render_chunk_text([first, second]))
        second["text"] = "x" * (1 + 3000 - base_length)
        self.assertEqual(len(render_chunk_text([first, second])), 3000)
        accepted = chunk_session_records([first, second])
        self.assertEqual(len(accepted), 1)
        self.assertEqual(len(accepted[0].records), 2)

        second["text"] += "x"
        split = chunk_session_records([first, second])
        self.assertEqual([len(chunk.records) for chunk in split], [1, 1])
        self.assertEqual(split[0].records[0]["text"], first["text"])

        unicode_record = make_record(1, "记忆é")
        unicode_text = render_chunk_text([unicode_record])
        self.assertGreater(len(unicode_text.encode("utf-8")), len(unicode_text))

    def test_natural_session_boundary_is_hard(self):
        first_session = make_record(1, "one", session_index=1)
        second_session = make_record(1, "two", session_index=2, session_date="2023-01-02")
        with self.assertRaisesRegex(S3ChunkBuildError, "may not cross"):
            render_chunk_text([first_session, second_session])


if __name__ == "__main__":
    unittest.main()
