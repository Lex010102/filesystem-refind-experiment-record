from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Any


S1_SCHEMA_VERSION = 1
S1_GENERATOR_VERSION = "locomo-s1-flat-v1"
TURN_RENDERER_VERSION = "locomo-text-caption-v1"
MEDIA_FIELDS = ("img_url", "blip_caption", "query", "re-download")

_LOCATOR_RE = re.compile(r"^\[S([1-9][0-9]*)T([1-9][0-9]*)\]$")
_DIA_ID_RE = re.compile(r"^D([1-9][0-9]*):([1-9][0-9]*)$")
_FORBIDDEN_GOLD_FIELDS = {
    "question",
    "answer",
    "adversarial_answer",
    "category",
    "evidence",
    "gold_answer",
    "gold_evidence",
    "qa",
}
_REQUIRED_RECORD_FIELDS = {
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


class StoreBuildError(ValueError):
    """Raised when a store cannot be built without violating its fixed protocol."""


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


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


def _body_bytes(payload: bytes) -> bytes:
    """Return everything after the YAML frontmatter, with a stable boundary."""
    delimiter = b"---\n\n"
    if not payload.startswith(b"---\n") or delimiter not in payload:
        raise StoreBuildError("Generated session file is missing its YAML frontmatter boundary")
    return payload.split(delimiter, 1)[1]


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        temporary.write_bytes(payload)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def load_canonical_records(path: Path) -> tuple[list[dict[str, Any]], str]:
    path = Path(path)
    payload = path.read_bytes()
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise StoreBuildError(f"Canonical records are not valid UTF-8: {exc}") from exc
    if not text.endswith("\n"):
        raise StoreBuildError("Canonical JSONL must end with a newline")

    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line:
            raise StoreBuildError(f"Canonical JSONL contains a blank line at {line_number}")
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise StoreBuildError(f"Cannot parse canonical JSONL line {line_number}: {exc}") from exc
        if not isinstance(record, dict):
            raise StoreBuildError(f"Canonical JSONL line {line_number} is not an object")
        missing = _REQUIRED_RECORD_FIELDS - set(record)
        forbidden = _FORBIDDEN_GOLD_FIELDS & set(record)
        if missing:
            raise StoreBuildError(
                f"Canonical JSONL line {line_number} is missing fields: {sorted(missing)}"
            )
        if forbidden:
            raise StoreBuildError(
                f"Canonical JSONL line {line_number} leaks gold fields: {sorted(forbidden)}"
            )
        records.append(record)
    if not records:
        raise StoreBuildError("Canonical JSONL contains no records")
    return records, _sha256_bytes(payload)


def render_source_turn(record: dict[str, Any]) -> str:
    """Render one immutable LoCoMo utterance for every text-only store and index."""
    speaker = record.get("speaker")
    text = record.get("text")
    locator = record.get("locator")
    dia_id = record.get("dia_id")
    media = record.get("media")
    if not isinstance(speaker, str) or not speaker or "\n" in speaker or ":" in speaker:
        raise StoreBuildError(f"Invalid speaker for {locator!r}: {speaker!r}")
    if not isinstance(text, str) or not text:
        raise StoreBuildError(f"Invalid text for {locator!r}")
    if "\r" in text:
        raise StoreBuildError(f"Carriage returns are not supported in {locator!r}")
    locator_match = _LOCATOR_RE.fullmatch(locator) if isinstance(locator, str) else None
    dia_match = _DIA_ID_RE.fullmatch(dia_id) if isinstance(dia_id, str) else None
    if locator_match is None or dia_match is None:
        raise StoreBuildError(f"Invalid source ids: locator={locator!r}, dia_id={dia_id!r}")
    if locator_match.groups() != dia_match.groups():
        raise StoreBuildError(f"Source ids disagree: {locator!r} vs {dia_id!r}")
    if not isinstance(media, dict):
        raise StoreBuildError(f"Invalid media object for {locator}")

    lines = [f"{speaker}: {text}"]
    caption = media.get("blip_caption")
    if caption is not None:
        if not isinstance(caption, str) or not caption or "\n" in caption or "\r" in caption:
            raise StoreBuildError(f"Invalid BLIP caption for {locator}")
        lines.append(f"[Image caption: {caption}]")
    lines.append(f"{locator} (dia_id: {dia_id})")
    return "\n".join(lines)


def _validate_records(
    records: list[dict[str, Any]], source_map: dict[str, Any], canonical_sha256: str
) -> tuple[str, list[str], dict[int, list[dict[str, Any]]]]:
    if source_map.get("record_sha256") != canonical_sha256:
        raise StoreBuildError("Canonical JSONL hash does not match source_map.json")
    if source_map.get("record_count") != len(records):
        raise StoreBuildError("Canonical record count does not match source_map.json")
    by_locator = source_map.get("by_locator")
    by_dia_id = source_map.get("by_dia_id")
    if not isinstance(by_locator, dict) or not isinstance(by_dia_id, dict):
        raise StoreBuildError("source_map.json is missing its lookup tables")

    conversation_ids = {record["conversation_id"] for record in records}
    if len(conversation_ids) != 1:
        raise StoreBuildError(f"S1 accepts exactly one conversation, got {conversation_ids}")
    conversation_id = next(iter(conversation_ids))
    if source_map.get("conversation_id") != conversation_id:
        raise StoreBuildError("Conversation id does not match source_map.json")

    speakers: list[str] = []
    sessions: dict[int, list[dict[str, Any]]] = defaultdict(list)
    seen_locators: set[str] = set()
    seen_dia_ids: set[str] = set()

    for line_number, record in enumerate(records, start=1):
        if record["global_turn_index"] != line_number:
            raise StoreBuildError(f"global_turn_index mismatch on JSONL line {line_number}")
        session_index = record["session_index"]
        turn_index = record["turn_index"]
        if not isinstance(session_index, int) or session_index < 1:
            raise StoreBuildError(f"Invalid session_index on JSONL line {line_number}")
        if not isinstance(turn_index, int) or turn_index < 1:
            raise StoreBuildError(f"Invalid turn_index on JSONL line {line_number}")
        if record["session_id"] != f"session_{session_index}":
            raise StoreBuildError(f"session_id mismatch on JSONL line {line_number}")
        locator = record["locator"]
        dia_id = record["dia_id"]
        locator_match = _LOCATOR_RE.fullmatch(locator) if isinstance(locator, str) else None
        dia_match = _DIA_ID_RE.fullmatch(dia_id) if isinstance(dia_id, str) else None
        expected_ids = (str(session_index), str(turn_index))
        if (
            locator_match is None
            or dia_match is None
            or locator_match.groups() != expected_ids
            or dia_match.groups() != expected_ids
        ):
            raise StoreBuildError(
                f"Source ids do not match session/turn indices on JSONL line {line_number}"
            )
        if locator in seen_locators or dia_id in seen_dia_ids:
            raise StoreBuildError(f"Duplicate source id on JSONL line {line_number}")
        seen_locators.add(locator)
        seen_dia_ids.add(dia_id)
        mapped = by_locator.get(locator)
        if not isinstance(mapped, dict):
            raise StoreBuildError(f"source_map locator entry is invalid for {locator}")
        if mapped.get("jsonl_line") != line_number:
            raise StoreBuildError(f"source_map locator mismatch for {locator}")
        if mapped.get("dia_id") != dia_id:
            raise StoreBuildError(f"source_map dia_id mismatch for {locator}")
        if by_dia_id.get(dia_id) != {"jsonl_line": line_number, "locator": locator}:
            raise StoreBuildError(f"source_map reverse lookup mismatch for {dia_id}")
        expected_source_hash = _sha256_bytes(record["text"].encode("utf-8"))
        if record["source_sha256"] != expected_source_hash:
            raise StoreBuildError(f"Source text hash mismatch for {locator}")
        media = record["media"]
        if not isinstance(media, dict) or set(media) != set(MEDIA_FIELDS):
            raise StoreBuildError(f"Canonical media fields are invalid for {locator}")
        raw_turn = {"speaker": record["speaker"]}
        raw_turn.update({key: media[key] for key in MEDIA_FIELDS if media[key] is not None})
        raw_turn.update({"dia_id": dia_id, "text": record["text"]})
        expected_raw_turn_hash = _sha256_bytes(_canonical_json_bytes(raw_turn))
        if record["raw_turn_sha256"] != expected_raw_turn_hash:
            raise StoreBuildError(f"Raw turn hash mismatch for {locator}")
        expected_mapped_values = {
            "dia_id": dia_id,
            "jsonl_line": line_number,
            "raw_turn_sha256": expected_raw_turn_hash,
            "session_id": record["session_id"],
            "session_index": session_index,
            "source_sha256": expected_source_hash,
            "speaker": record["speaker"],
            "turn_index": turn_index,
        }
        if any(mapped.get(key) != value for key, value in expected_mapped_values.items()):
            raise StoreBuildError(f"source_map metadata mismatch for {locator}")
        if record["speaker"] not in speakers:
            speakers.append(record["speaker"])
        render_source_turn(record)
        sessions[session_index].append(record)

    session_numbers = sorted(sessions)
    if session_numbers != list(range(1, session_numbers[-1] + 1)):
        raise StoreBuildError(f"Session indices are not contiguous: {session_numbers}")
    prior_global_index = 0
    for session_index in session_numbers:
        session_records = sessions[session_index]
        if [item["turn_index"] for item in session_records] != list(
            range(1, len(session_records) + 1)
        ):
            raise StoreBuildError(f"Turn indices are not contiguous in session {session_index}")
        if any(
            item["session_index"] != session_index
            or item["session_date"] != session_records[0]["session_date"]
            or item["session_datetime"] != session_records[0]["session_datetime"]
            or item["session_datetime_raw"] != session_records[0]["session_datetime_raw"]
            for item in session_records
        ):
            raise StoreBuildError(f"Session metadata is inconsistent in session {session_index}")
        for item in session_records:
            if item["global_turn_index"] <= prior_global_index:
                raise StoreBuildError("Canonical records are not in chronological order")
            prior_global_index = item["global_turn_index"]

    if set(by_locator) != seen_locators or set(by_dia_id) != seen_dia_ids:
        raise StoreBuildError("source_map.json lookup keys do not exactly match canonical records")

    if len(speakers) != 2:
        raise StoreBuildError(f"Expected exactly two conversation speakers, got {speakers}")
    return conversation_id, speakers, dict(sessions)


def _render_session_file(
    conversation_id: str,
    session_index: int,
    records: list[dict[str, Any]],
    speakers: list[str],
    filename_width: int,
) -> tuple[str, bytes, dict[str, dict[str, Any]]]:
    first = records[0]
    stem = f"session-{session_index:0{filename_width}d}"
    filename = f"{stem}.md"
    description = (
        f"Session {session_index} on {first['session_date']} between "
        f"{speakers[0]} and {speakers[1]}."
    )
    lines = [
        "---",
        f"name: {stem}",
        f"description: {description}",
        "---",
        "",
        f"# Session {session_index}",
        "",
        f"Date: {first['session_datetime_raw']}",
        f"Speakers: {speakers[0]}, {speakers[1]}",
        f"Conversation: {conversation_id}",
        "",
    ]
    source_index: dict[str, dict[str, Any]] = {}
    for record in records:
        start_line = len(lines) + 1
        rendered_lines = render_source_turn(record).split("\n")
        lines.extend(rendered_lines)
        end_line = len(lines)
        source_index[record["locator"]] = {
            "dia_id": record["dia_id"],
            "end_line": end_line,
            "file": filename,
            "global_turn_index": record["global_turn_index"],
            "raw_turn_sha256": record["raw_turn_sha256"],
            "source_sha256": record["source_sha256"],
            "start_line": start_line,
            "turn_index": record["turn_index"],
        }
        lines.append("")
    payload = "\n".join(lines).encode("utf-8")
    return filename, payload, source_index


def _ensure_store_bytes(output_dir: Path, desired_files: dict[str, bytes]) -> str:
    if output_dir.exists():
        if output_dir.is_symlink() or not output_dir.is_dir():
            raise StoreBuildError(f"S1 output exists but is not a directory: {output_dir}")
        entries = list(output_dir.iterdir())
        if any(path.is_symlink() or not path.is_file() for path in entries):
            raise StoreBuildError(
                "Existing S1 store must contain only flat, regular session files"
            )
        actual_paths = {path.name: path for path in entries}
        if set(actual_paths) != set(desired_files):
            raise StoreBuildError(
                "Existing S1 store has missing or unexpected files; choose a new output directory"
            )
        changed = [
            name for name, payload in desired_files.items() if actual_paths[name].read_bytes() != payload
        ]
        if changed:
            raise StoreBuildError(
                f"Existing S1 store differs from the deterministic build: {changed[:5]}"
            )
        return "verified-existing"

    output_dir.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(
        tempfile.mkdtemp(prefix=f".{output_dir.name}.tmp-", dir=output_dir.parent)
    )
    try:
        for relative_name, payload in desired_files.items():
            target = temporary / relative_name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)
        os.replace(temporary, output_dir)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return "created"


def build_s1_store(
    canonical_path: Path,
    source_map_path: Path,
    output_dir: Path,
    manifest_path: Path,
) -> dict[str, Any]:
    canonical_path = Path(canonical_path)
    source_map_path = Path(source_map_path)
    output_dir = Path(output_dir)
    manifest_path = Path(manifest_path)
    if output_dir.resolve() in manifest_path.resolve().parents:
        raise StoreBuildError("S1 manifest must live outside the store directory")
    if len({canonical_path.resolve(), source_map_path.resolve(), manifest_path.resolve()}) != 3:
        raise StoreBuildError("Canonical, source-map, and manifest paths must be distinct")

    records, canonical_sha256 = load_canonical_records(canonical_path)
    source_map_bytes = source_map_path.read_bytes()
    try:
        source_map = json.loads(source_map_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise StoreBuildError(f"Cannot parse source_map.json: {exc}") from exc
    if not isinstance(source_map, dict):
        raise StoreBuildError("source_map.json must contain an object")

    conversation_id, speakers, sessions = _validate_records(
        records, source_map, canonical_sha256
    )
    filename_width = max(2, len(str(max(sessions))))
    desired_files: dict[str, bytes] = {}
    source_index: dict[str, dict[str, Any]] = {}
    file_manifest: dict[str, dict[str, Any]] = {}
    caption_count = 0

    for session_index in sorted(sessions):
        session_records = sessions[session_index]
        filename, payload, session_source_index = _render_session_file(
            conversation_id,
            session_index,
            session_records,
            speakers,
            filename_width,
        )
        desired_files[filename] = payload
        body = _body_bytes(payload)
        source_index.update(session_source_index)
        session_caption_count = sum(
            record["media"].get("blip_caption") is not None for record in session_records
        )
        caption_count += session_caption_count
        file_manifest[filename] = {
            "body_bytes": len(body),
            "body_sha256": _sha256_bytes(body),
            "bytes": len(payload),
            "caption_count": session_caption_count,
            "first_dia_id": session_records[0]["dia_id"],
            "first_locator": session_records[0]["locator"],
            "last_dia_id": session_records[-1]["dia_id"],
            "last_locator": session_records[-1]["locator"],
            "session_date": session_records[0]["session_date"],
            "session_index": session_index,
            "sha256": _sha256_bytes(payload),
            "turn_count": len(session_records),
        }

    if len(source_index) != len(records):
        raise StoreBuildError("S1 source index does not cover every canonical record")
    store_sha256 = _sha256_bytes(
        _canonical_json_bytes(
            {name: _sha256_bytes(payload) for name, payload in sorted(desired_files.items())}
        )
    )
    manifest = {
        "schema_version": S1_SCHEMA_VERSION,
        "artifact_id": f"locomo/{conversation_id}/s1-flat/v{S1_SCHEMA_VERSION}",
        "generator": {
            "module": "fs_memory_lab.stores",
            "version": S1_GENERATOR_VERSION,
        },
        "input": {
            "canonical_filename": canonical_path.name,
            "canonical_sha256": canonical_sha256,
            "source_map_filename": source_map_path.name,
            "source_map_sha256": _sha256_bytes(source_map_bytes),
        },
        "selection": {
            "conversation_id": conversation_id,
            "speakers": speakers,
        },
        "renderer": {
            "version": TURN_RENDERER_VERSION,
            "semantic_fields": ["speaker", "text", "media.blip_caption"],
            "source_fields": ["locator", "dia_id"],
            "excluded_media_fields": ["media.img_url", "media.query", "media.re-download"],
            "image_policy": "render official BLIP caption as text; never fetch image URLs",
        },
        "counts": {
            "files": len(desired_files),
            "sessions": len(sessions),
            "source_turns": len(records),
            "turns_with_caption": caption_count,
            "bytes": sum(len(payload) for payload in desired_files.values()),
        },
        "files": file_manifest,
        "source_index": source_index,
        "store": {
            "directory_name": output_dir.name,
            "sha256": store_sha256,
        },
        "build_cost": {
            "llm_calls": 0,
            "model_tokens": 0,
            "tool_calls": 0,
        },
        "verification": {
            "all_source_turns_covered_once": True,
            "canonical_order_preserved": True,
            "gold_fields_accessed": False,
            "image_urls_fetched": False,
            "one_file_per_natural_session": True,
        },
    }
    manifest_bytes = _pretty_json_bytes(manifest)
    write_status = _ensure_store_bytes(output_dir, desired_files)
    _atomic_write(manifest_path, manifest_bytes)

    return {
        "captions": caption_count,
        "conversation_id": conversation_id,
        "files": len(desired_files),
        "manifest_sha256": _sha256_bytes(manifest_bytes),
        "sessions": len(sessions),
        "source_turns": len(records),
        "store_sha256": store_sha256,
        "write_status": write_status,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build deterministic LoCoMo experiment stores")
    subparsers = parser.add_subparsers(dest="command", required=True)
    s1 = subparsers.add_parser("build-s1", help="build flat verbatim session files")
    s1.add_argument(
        "--canonical", type=Path, default=Path("data/processed/conv-50.jsonl")
    )
    s1.add_argument(
        "--source-map", type=Path, default=Path("data/manifests/source_map.json")
    )
    s1.add_argument(
        "--output-dir",
        type=Path,
        default=Path("experiments/locomo-conv50-v1/stores/s1-flat"),
    )
    s1.add_argument(
        "--manifest",
        type=Path,
        default=Path("experiments/locomo-conv50-v1/manifests/s1-flat.json"),
    )
    args = parser.parse_args()

    if args.command == "build-s1":
        report = build_s1_store(
            args.canonical,
            args.source_map,
            args.output_dir,
            args.manifest,
        )
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
