from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import tempfile
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .paper_config import CHUNK_MAX_CHARS, CHUNK_MAX_TURNS
from .stores import (
    MEDIA_FIELDS,
    TURN_RENDERER_VERSION,
    StoreBuildError,
    load_canonical_records,
    render_source_turn,
)


S3_CHUNK_SCHEMA_VERSION = 1
S3_CHUNK_GENERATOR_VERSION = "locomo-s3-management-stream-v1"
PINNED_CONV50_CANONICAL_SHA256 = (
    "130a5a1e1b75083358ef27a98dd215a4e75c819ace6f2ee9b560ba394e0f0394"
)
SESSION_HEADER_TEMPLATE = "Session {session_index} · {session_date}"
TURN_SEPARATOR = "\n\n"

CANONICAL_RECORD_FIELDS = frozenset(
    {
        "schema_version",
        "conversation_id",
        "session_id",
        "session_index",
        "session_date",
        "session_datetime",
        "session_datetime_raw",
        "turn_index",
        "global_turn_index",
        "locator",
        "dia_id",
        "speaker",
        "text",
        "media",
        "source_sha256",
        "raw_turn_sha256",
    }
)

_LOCATOR_RE = re.compile(r"^\[S([1-9][0-9]*)T([1-9][0-9]*)\]$")
_DIA_ID_RE = re.compile(r"^D([1-9][0-9]*):([1-9][0-9]*)$")
_ISO_DATE_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")


class S3ChunkBuildError(StoreBuildError):
    """Raised when the fixed S3 management stream cannot be built safely."""


@dataclass(frozen=True)
class ChunkDraft:
    session_index: int
    session_chunk_index: int
    records: tuple[dict[str, Any], ...]
    text: str


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _pretty_json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2, sort_keys=True)
        + "\n"
    ).encode("utf-8")


def _session_header(record: dict[str, Any]) -> str:
    return SESSION_HEADER_TEMPLATE.format(
        session_index=record["session_index"],
        session_date=record["session_date"],
    )


def render_chunk_text(records: list[dict[str, Any]] | tuple[dict[str, Any], ...]) -> str:
    """Render the exact chunk payload later embedded in one S3 management episode."""
    if not records:
        raise S3ChunkBuildError("Cannot render an empty management chunk")
    session_indices = {record.get("session_index") for record in records}
    if len(session_indices) != 1:
        raise S3ChunkBuildError("An S3 management chunk may not cross a natural session boundary")
    session_dates = {record.get("session_date") for record in records}
    if len(session_dates) != 1:
        raise S3ChunkBuildError("Session dates disagree inside an S3 management chunk")
    return TURN_SEPARATOR.join(
        [_session_header(records[0]), *(render_source_turn(record) for record in records)]
    )


def chunk_session_records(
    records: list[dict[str, Any]],
    *,
    max_turns: int = CHUNK_MAX_TURNS,
    max_characters: int = CHUNK_MAX_CHARS,
) -> list[ChunkDraft]:
    """Greedily chunk one natural session without splitting any source turn."""
    if not records:
        raise S3ChunkBuildError("Cannot chunk an empty natural session")
    if max_turns < 1 or max_characters < 1:
        raise S3ChunkBuildError("Chunk limits must be positive")
    session_index = records[0].get("session_index")
    if any(record.get("session_index") != session_index for record in records):
        raise S3ChunkBuildError("chunk_session_records received more than one session")

    chunks: list[ChunkDraft] = []
    current: list[dict[str, Any]] = []

    def flush() -> None:
        if not current:
            return
        text = render_chunk_text(current)
        chunks.append(
            ChunkDraft(
                session_index=int(session_index),
                session_chunk_index=len(chunks) + 1,
                records=tuple(current),
                text=text,
            )
        )

    for record in records:
        render_source_turn(record)
        candidate = [*current, record]
        candidate_text = render_chunk_text(candidate)
        if current and (len(current) >= max_turns or len(candidate_text) > max_characters):
            flush()
            current.clear()
            candidate = [record]
            candidate_text = render_chunk_text(candidate)
        if len(candidate_text) > max_characters:
            raise S3ChunkBuildError(
                f"Source turn {record.get('locator')} cannot fit inside the "
                f"{max_characters}-character cap without splitting"
            )
        current.append(record)

    flush()
    return chunks


def _validate_records(
    records: list[dict[str, Any]],
) -> tuple[str, list[str], dict[int, list[dict[str, Any]]]]:
    sessions: dict[int, list[dict[str, Any]]] = defaultdict(list)
    speakers: list[str] = []
    conversation_ids: set[str] = set()
    schema_versions: set[int] = set()
    seen_locators: set[str] = set()
    seen_dia_ids: set[str] = set()

    for line_number, record in enumerate(records, start=1):
        fields = set(record)
        if fields != CANONICAL_RECORD_FIELDS:
            missing = sorted(CANONICAL_RECORD_FIELDS - fields)
            unexpected = sorted(fields - CANONICAL_RECORD_FIELDS)
            raise S3ChunkBuildError(
                f"Canonical JSONL line {line_number} violates the closed field allowlist; "
                f"missing={missing}, unexpected={unexpected}"
            )
        if record["global_turn_index"] != line_number:
            raise S3ChunkBuildError(
                f"global_turn_index mismatch on canonical line {line_number}"
            )
        session_index = record["session_index"]
        turn_index = record["turn_index"]
        if not isinstance(session_index, int) or session_index < 1:
            raise S3ChunkBuildError(f"Invalid session_index on canonical line {line_number}")
        if not isinstance(turn_index, int) or turn_index < 1:
            raise S3ChunkBuildError(f"Invalid turn_index on canonical line {line_number}")
        if record["session_id"] != f"session_{session_index}":
            raise S3ChunkBuildError(f"session_id mismatch on canonical line {line_number}")
        if not isinstance(record["session_date"], str) or not _ISO_DATE_RE.fullmatch(
            record["session_date"]
        ):
            raise S3ChunkBuildError(f"Invalid session_date on canonical line {line_number}")

        expected_id_parts = (str(session_index), str(turn_index))
        locator_match = (
            _LOCATOR_RE.fullmatch(record["locator"])
            if isinstance(record["locator"], str)
            else None
        )
        dia_match = (
            _DIA_ID_RE.fullmatch(record["dia_id"])
            if isinstance(record["dia_id"], str)
            else None
        )
        if (
            locator_match is None
            or dia_match is None
            or locator_match.groups() != expected_id_parts
            or dia_match.groups() != expected_id_parts
        ):
            raise S3ChunkBuildError(
                f"Source ids disagree with session/turn indices on canonical line {line_number}"
            )
        if record["locator"] in seen_locators or record["dia_id"] in seen_dia_ids:
            raise S3ChunkBuildError(f"Duplicate source id on canonical line {line_number}")
        seen_locators.add(record["locator"])
        seen_dia_ids.add(record["dia_id"])

        media = record["media"]
        if not isinstance(media, dict) or set(media) != set(MEDIA_FIELDS):
            raise S3ChunkBuildError(f"Invalid media fields for {record['locator']}")
        source_sha256 = _sha256_bytes(record["text"].encode("utf-8"))
        if record["source_sha256"] != source_sha256:
            raise S3ChunkBuildError(f"Source text hash mismatch for {record['locator']}")
        raw_turn = {"speaker": record["speaker"]}
        raw_turn.update({key: media[key] for key in MEDIA_FIELDS if media[key] is not None})
        raw_turn.update({"dia_id": record["dia_id"], "text": record["text"]})
        if record["raw_turn_sha256"] != _sha256_bytes(_canonical_json_bytes(raw_turn)):
            raise S3ChunkBuildError(f"Raw turn hash mismatch for {record['locator']}")

        render_source_turn(record)
        conversation_ids.add(record["conversation_id"])
        schema_versions.add(record["schema_version"])
        if record["speaker"] not in speakers:
            speakers.append(record["speaker"])
        sessions[session_index].append(record)

    if len(conversation_ids) != 1:
        raise S3ChunkBuildError(
            f"S3 accepts exactly one conversation, got {sorted(conversation_ids)}"
        )
    if schema_versions != {1}:
        raise S3ChunkBuildError(f"Unsupported canonical schema versions: {schema_versions}")
    if len(speakers) != 2:
        raise S3ChunkBuildError(f"Expected exactly two speakers, got {speakers}")
    session_indices = sorted(sessions)
    if session_indices != list(range(1, session_indices[-1] + 1)):
        raise S3ChunkBuildError(f"Session indices are not contiguous: {session_indices}")
    for session_index in session_indices:
        session_records = sessions[session_index]
        if [record["turn_index"] for record in session_records] != list(
            range(1, len(session_records) + 1)
        ):
            raise S3ChunkBuildError(f"Turn indices are not contiguous in session {session_index}")
        first = session_records[0]
        if any(
            record["session_id"] != first["session_id"]
            or record["session_date"] != first["session_date"]
            or record["session_datetime"] != first["session_datetime"]
            or record["session_datetime_raw"] != first["session_datetime_raw"]
            for record in session_records
        ):
            raise S3ChunkBuildError(f"Session metadata is inconsistent in session {session_index}")

    return next(iter(conversation_ids)), speakers, dict(sessions)


def _verify_existing_directory(output_dir: Path, desired_files: dict[str, bytes]) -> None:
    if output_dir.is_symlink() or not output_dir.is_dir():
        raise S3ChunkBuildError(f"S3 stream output is not a regular directory: {output_dir}")
    entries = list(output_dir.iterdir())
    if any(path.is_symlink() or not path.is_file() for path in entries):
        raise S3ChunkBuildError("Existing S3 stream must contain only regular chunk files")
    actual = {path.name: path for path in entries}
    if set(actual) != set(desired_files):
        raise S3ChunkBuildError(
            "Existing S3 stream has missing or unexpected files; refusing to overwrite"
        )
    changed = [
        name for name, payload in desired_files.items() if actual[name].read_bytes() != payload
    ]
    if changed:
        raise S3ChunkBuildError(
            f"Existing S3 stream differs from the deterministic build: {changed[:5]}"
        )


def _publish_or_verify(
    output_dir: Path,
    manifest_path: Path,
    desired_files: dict[str, bytes],
    manifest_bytes: bytes,
) -> str:
    output_exists = output_dir.exists() or output_dir.is_symlink()
    manifest_exists = manifest_path.exists() or manifest_path.is_symlink()
    if output_exists or manifest_exists:
        if not output_exists or not manifest_exists:
            raise S3ChunkBuildError(
                "S3 stream and manifest must either both be absent or both already exist"
            )
        _verify_existing_directory(output_dir, desired_files)
        if manifest_path.is_symlink() or not manifest_path.is_file():
            raise S3ChunkBuildError("Existing S3 manifest is not a regular file")
        if manifest_path.read_bytes() != manifest_bytes:
            raise S3ChunkBuildError(
                "Existing S3 manifest differs from the deterministic build; refusing to overwrite"
            )
        return "verified-existing"

    output_dir.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_dir = Path(
        tempfile.mkdtemp(prefix=f".{output_dir.name}.tmp-", dir=output_dir.parent)
    )
    manifest_fd, temporary_manifest_name = tempfile.mkstemp(
        prefix=f".{manifest_path.name}.tmp-", dir=manifest_path.parent
    )
    os.close(manifest_fd)
    temporary_manifest = Path(temporary_manifest_name)
    output_published = False
    try:
        for filename, payload in desired_files.items():
            (temporary_dir / filename).write_bytes(payload)
        temporary_manifest.write_bytes(manifest_bytes)
        os.replace(temporary_dir, output_dir)
        output_published = True
        os.replace(temporary_manifest, manifest_path)
    except Exception:
        if output_published and output_dir.exists() and not manifest_path.exists():
            shutil.rmtree(output_dir)
        raise
    finally:
        if temporary_dir.exists():
            shutil.rmtree(temporary_dir)
        if temporary_manifest.exists():
            temporary_manifest.unlink()
    return "created"


def build_s3_management_chunks(
    canonical_path: Path,
    output_dir: Path,
    manifest_path: Path,
    *,
    expected_canonical_sha256: str | None = PINNED_CONV50_CANONICAL_SHA256,
) -> dict[str, Any]:
    canonical_path = Path(canonical_path)
    output_dir = Path(output_dir)
    manifest_path = Path(manifest_path)
    if output_dir.resolve() in manifest_path.resolve().parents:
        raise S3ChunkBuildError("S3 manifest must live outside the chunk directory")
    if len({canonical_path.resolve(), output_dir.resolve(), manifest_path.resolve()}) != 3:
        raise S3ChunkBuildError("Canonical, stream, and manifest paths must be distinct")

    records, canonical_sha256 = load_canonical_records(canonical_path)
    if (
        expected_canonical_sha256 is not None
        and canonical_sha256 != expected_canonical_sha256
    ):
        raise S3ChunkBuildError(
            "Canonical JSONL SHA-256 mismatch: "
            f"expected {expected_canonical_sha256}, got {canonical_sha256}"
        )
    conversation_id, speakers, sessions = _validate_records(records)
    all_chunks: list[ChunkDraft] = []
    for session_index in sorted(sessions):
        all_chunks.extend(chunk_session_records(sessions[session_index]))

    desired_files: dict[str, bytes] = {}
    chunk_manifest: list[dict[str, Any]] = []
    source_index: dict[str, dict[str, Any]] = {}
    caption_count = 0
    global_chunk_index = 0
    filename_width = max(2, len(str(max(sessions))))

    for draft in all_chunks:
        global_chunk_index += 1
        filename = (
            f"session_{draft.session_index:0{filename_width}d}_"
            f"chunk_{draft.session_chunk_index:02d}.txt"
        )
        payload = draft.text.encode("utf-8")
        desired_files[filename] = payload
        header = _session_header(draft.records[0])
        character_cursor = len(header)
        byte_cursor = len(header.encode("utf-8"))
        locators: list[str] = []
        dia_ids: list[str] = []
        chunk_caption_count = 0

        for ordinal, record in enumerate(draft.records, start=1):
            block = render_source_turn(record)
            block_bytes = block.encode("utf-8")
            character_cursor += len(TURN_SEPARATOR)
            byte_cursor += len(TURN_SEPARATOR.encode("utf-8"))
            start_character = character_cursor
            start_byte = byte_cursor
            character_cursor += len(block)
            byte_cursor += len(block_bytes)
            source_index[record["locator"]] = {
                "chunk_file": filename,
                "dia_id": record["dia_id"],
                "end_byte_exclusive": byte_cursor,
                "end_character_exclusive": character_cursor,
                "global_chunk_index": global_chunk_index,
                "global_turn_index": record["global_turn_index"],
                "ordinal_in_chunk": ordinal,
                "raw_turn_sha256": record["raw_turn_sha256"],
                "rendered_sha256": _sha256_bytes(block_bytes),
                "session_chunk_index": draft.session_chunk_index,
                "session_index": draft.session_index,
                "source_sha256": record["source_sha256"],
                "start_byte": start_byte,
                "start_character": start_character,
                "turn_index": record["turn_index"],
            }
            locators.append(record["locator"])
            dia_ids.append(record["dia_id"])
            has_caption = record["media"]["blip_caption"] is not None
            chunk_caption_count += int(has_caption)
            caption_count += int(has_caption)

        if character_cursor != len(draft.text) or byte_cursor != len(payload):
            raise S3ChunkBuildError(f"Internal offset accounting failed for {filename}")
        chunk_manifest.append(
            {
                "bytes": len(payload),
                "caption_count": chunk_caption_count,
                "characters": len(draft.text),
                "dia_ids": dia_ids,
                "filename": filename,
                "first_global_turn_index": draft.records[0]["global_turn_index"],
                "first_locator": draft.records[0]["locator"],
                "global_chunk_index": global_chunk_index,
                "last_global_turn_index": draft.records[-1]["global_turn_index"],
                "last_locator": draft.records[-1]["locator"],
                "locators": locators,
                "session_chunk_index": draft.session_chunk_index,
                "session_date": draft.records[0]["session_date"],
                "session_index": draft.session_index,
                "sha256": _sha256_bytes(payload),
                "turn_count": len(draft.records),
            }
        )

    if len(source_index) != len(records) or set(source_index) != {
        record["locator"] for record in records
    }:
        raise S3ChunkBuildError("S3 source index does not cover every canonical record once")
    flattened_global_indices = [
        source_index[locator]["global_turn_index"]
        for chunk in chunk_manifest
        for locator in chunk["locators"]
    ]
    if flattened_global_indices != list(range(1, len(records) + 1)):
        raise S3ChunkBuildError("S3 chunks do not preserve canonical chronological order")
    if any(
        chunk["turn_count"] > CHUNK_MAX_TURNS
        or chunk["characters"] > CHUNK_MAX_CHARS
        for chunk in chunk_manifest
    ):
        raise S3ChunkBuildError("Generated S3 chunks violate the frozen dual cap")

    stream_index = [
        {"filename": chunk["filename"], "sha256": chunk["sha256"]}
        for chunk in chunk_manifest
    ]
    stream_sha256 = _sha256_bytes(_canonical_json_bytes(stream_index))
    manifest = {
        "schema_version": S3_CHUNK_SCHEMA_VERSION,
        "artifact_id": (
            f"locomo/{conversation_id}/s3-management-stream/"
            f"v{S3_CHUNK_SCHEMA_VERSION}"
        ),
        "generator": {
            "module": "fs_memory_lab.s3_chunks",
            "version": S3_CHUNK_GENERATOR_VERSION,
        },
        "input": {
            "canonical_filename": canonical_path.name,
            "canonical_schema_version": records[0]["schema_version"],
            "canonical_sha256": canonical_sha256,
            "expected_canonical_sha256": expected_canonical_sha256,
            "gold_bearing_files_read": False,
        },
        "selection": {
            "conversation_id": conversation_id,
            "speakers": speakers,
        },
        "paper_alignment": {
            "explicit_rules": [
                "consecutive dialogue turns",
                "at most 8 turns per chunk",
                "3000-character cap",
                "one management build episode per chunk",
            ],
            "session_boundary_evidence": (
                "inferred from Prompt 8's example session-scoped filename pattern, which the "
                "authors say was revised to match the store, and the 85-step LoCoMo build "
                "trajectory; not stated as a standalone sentence"
            ),
            "source": "Appendix C.1, Table 11, Prompt 8, and Figure 5",
            "byte_exact_author_chunker_found_in_paper_or_official_links": False,
            "public_material_check_date": "2026-10-06",
        },
        "renderer": {
            "version": TURN_RENDERER_VERSION,
            "semantic_fields": ["speaker", "text", "media.blip_caption"],
            "context_fields": ["session_index", "session_date"],
            "source_fields": ["locator", "dia_id"],
            "excluded_media_fields": [
                "media.img_url",
                "media.query",
                "media.re-download",
            ],
            "image_policy": "render official BLIP caption as text; never fetch image URLs",
            "session_header_template": SESSION_HEADER_TEMPLATE,
            "turn_separator": TURN_SEPARATOR,
            "terminal_newline": False,
        },
        "chunking": {
            "unit": "source_turn (one speaker utterance; one canonical JSONL record)",
            "max_turns": CHUNK_MAX_TURNS,
            "max_characters": CHUNK_MAX_CHARS,
            "character_metric": "Python len(str): Unicode code points",
            "character_cap_scope": (
                "exact chunk payload, including session header and separators; excludes system "
                "prompt and the not-yet-frozen per-episode user wrapper"
            ),
            "session_boundary_policy": "hard reset; chunks never cross natural sessions",
            "greedy_rule": (
                "append the next complete source turn only if both caps remain satisfied"
            ),
            "oversize_source_turn_policy": "reject; never split or truncate a source turn",
            "one_management_episode_per_chunk": True,
        },
        "counts": {
            "bytes": sum(chunk["bytes"] for chunk in chunk_manifest),
            "characters": sum(chunk["characters"] for chunk in chunk_manifest),
            "chunks": len(chunk_manifest),
            "max_chunk_characters": max(chunk["characters"] for chunk in chunk_manifest),
            "max_turns_per_chunk": max(chunk["turn_count"] for chunk in chunk_manifest),
            "min_chunk_characters": min(chunk["characters"] for chunk in chunk_manifest),
            "min_turns_per_chunk": min(chunk["turn_count"] for chunk in chunk_manifest),
            "sessions": len(sessions),
            "source_turns": len(records),
            "turns_with_caption": caption_count,
        },
        "chunks": chunk_manifest,
        "source_index": source_index,
        "stream": {
            "directory_name": output_dir.name,
            "ordered_index": stream_index,
            "sha256": stream_sha256,
        },
        "build_cost": {
            "llm_calls": 0,
            "model_tokens": 0,
            "tool_calls": 0,
        },
        "verification": {
            "all_source_turns_covered_once": True,
            "canonical_order_preserved": True,
            "closed_field_allowlist_enforced": True,
            "gold_inputs_read": False,
            "gold_inputs_sent_to_model": False,
            "image_urls_fetched": False,
            "natural_session_boundaries_preserved": True,
            "source_turns_split_or_truncated": False,
            "turn_and_character_caps_satisfied": True,
        },
    }
    manifest_bytes = _pretty_json_bytes(manifest)
    write_status = _publish_or_verify(
        output_dir, manifest_path, desired_files, manifest_bytes
    )
    return {
        "captions": caption_count,
        "chunks": len(chunk_manifest),
        "conversation_id": conversation_id,
        "manifest_sha256": _sha256_bytes(manifest_bytes),
        "sessions": len(sessions),
        "source_turns": len(records),
        "stream_sha256": stream_sha256,
        "write_status": write_status,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build the deterministic LoCoMo S3 management input stream"
    )
    parser.add_argument(
        "--canonical", type=Path, default=Path("data/processed/conv-50.jsonl")
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(
            "experiments/locomo-conv50-v1/streams/s3-management-v1"
        ),
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path(
            "experiments/locomo-conv50-v1/manifests/s3-management-stream.json"
        ),
    )
    args = parser.parse_args()
    report = build_s3_management_chunks(
        args.canonical,
        args.output_dir,
        args.manifest,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
