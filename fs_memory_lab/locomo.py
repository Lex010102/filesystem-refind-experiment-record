from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1
GENERATOR_VERSION = "locomo-canonical-v1"

OFFICIAL_REPOSITORY = "https://github.com/snap-research/locomo"
OFFICIAL_DATA_PATH = "data/locomo10.json"
OFFICIAL_DATA_COMMIT = "cbfbc1dba6bc53d00625212a0f22d55ffee7c1fc"
OFFICIAL_DATA_URL = (
    "https://raw.githubusercontent.com/snap-research/locomo/"
    f"{OFFICIAL_DATA_COMMIT}/{OFFICIAL_DATA_PATH}"
)
OFFICIAL_DATA_SHA256 = "79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4"
OFFICIAL_DATA_BYTES = 2_805_274
OFFICIAL_LICENSE = "CC BY-NC 4.0"
OFFICIAL_LICENSE_COMMIT = "a9f0a462c37e3c2e5285aec393e0598e03fc9e4d"
OFFICIAL_LICENSE_SHA256 = "41003d4a74749c0220e33dd415042164b5a1093ed401f36277234f772d22d3d0"
OFFICIAL_LICENSE_BYTES = 19_347
OFFICIAL_LICENSE_URL = (
    "https://github.com/snap-research/locomo/blob/"
    f"{OFFICIAL_LICENSE_COMMIT}/LICENSE.txt"
)

CATEGORY_NAMES = {
    "1": "multi-hop",
    "2": "temporal",
    "3": "open-domain",
    "4": "single-hop",
    "5": "adversarial",
}

_SESSION_RE = re.compile(r"^session_(\d+)$")
_DIA_ID_RE = re.compile(r"^D(\d+):(\d+)$")
_DATE_RE = re.compile(
    r"^(\d{1,2}):(\d{2})\s+(am|pm)\s+on\s+(\d{1,2})\s+([A-Za-z]+),\s+(\d{4})$",
    re.IGNORECASE,
)
_MONTHS = {
    name: index
    for index, name in enumerate(
        (
            "January",
            "February",
            "March",
            "April",
            "May",
            "June",
            "July",
            "August",
            "September",
            "October",
            "November",
            "December",
        ),
        start=1,
    )
}
_OPTIONAL_TURN_FIELDS = ("img_url", "blip_caption", "query", "re-download")

CANONICAL_RECORD_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "LoCoMo canonical turn record v1",
    "type": "object",
    "additionalProperties": False,
    "required": [
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
    ],
    "properties": {
        "schema_version": {"type": "integer", "const": SCHEMA_VERSION},
        "conversation_id": {"type": "string"},
        "session_id": {"type": "string", "pattern": "^session_[1-9][0-9]*$"},
        "session_index": {"type": "integer", "minimum": 1},
        "session_date": {"type": "string", "format": "date"},
        "session_datetime": {
            "type": "string",
            "pattern": "^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}$",
        },
        "session_datetime_raw": {"type": "string"},
        "turn_index": {"type": "integer", "minimum": 1},
        "global_turn_index": {"type": "integer", "minimum": 1},
        "locator": {"type": "string", "pattern": "^\\[S[1-9][0-9]*T[1-9][0-9]*\\]$"},
        "dia_id": {"type": "string", "pattern": "^D[1-9][0-9]*:[1-9][0-9]*$"},
        "speaker": {"type": "string", "minLength": 1},
        "text": {"type": "string", "minLength": 1},
        "media": {
            "type": "object",
            "additionalProperties": False,
            "required": list(_OPTIONAL_TURN_FIELDS),
            "properties": {
                "img_url": {
                    "oneOf": [
                        {"type": "array", "items": {"type": "string"}},
                        {"type": "null"},
                    ]
                },
                "blip_caption": {"type": ["string", "null"]},
                "query": {"type": ["string", "null"]},
                "re-download": {"type": ["boolean", "null"]},
            },
        },
        "source_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        "raw_turn_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
    },
}


class LocomoDataError(ValueError):
    """Raised when the pinned LoCoMo data violates the expected structural contract."""


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


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


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        temporary.write_bytes(payload)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def parse_session_datetime(raw_value: str) -> datetime:
    match = _DATE_RE.fullmatch(raw_value.strip())
    if not match:
        raise LocomoDataError(f"Unsupported LoCoMo session datetime: {raw_value!r}")
    hour_text, minute_text, meridiem, day_text, month_text, year_text = match.groups()
    month = _MONTHS.get(month_text.title())
    if month is None:
        raise LocomoDataError(f"Unsupported month in LoCoMo datetime: {raw_value!r}")
    hour = int(hour_text)
    if not 1 <= hour <= 12:
        raise LocomoDataError(f"Invalid hour in LoCoMo datetime: {raw_value!r}")
    if meridiem.lower() == "am":
        hour = 0 if hour == 12 else hour
    else:
        hour = 12 if hour == 12 else hour + 12
    try:
        return datetime(int(year_text), month, int(day_text), hour, int(minute_text))
    except ValueError as exc:
        raise LocomoDataError(f"Invalid LoCoMo session datetime: {raw_value!r}") from exc


def _find_conversation(dataset: Any, conversation_id: str) -> tuple[int, dict[str, Any]]:
    if not isinstance(dataset, list):
        raise LocomoDataError("LoCoMo root must be a JSON list")
    matches = [
        (index, sample)
        for index, sample in enumerate(dataset)
        if isinstance(sample, dict) and sample.get("sample_id") == conversation_id
    ]
    if len(matches) != 1:
        raise LocomoDataError(
            f"Expected exactly one sample_id={conversation_id!r}; found {len(matches)}"
        )
    return matches[0]


def _session_numbers(conversation: dict[str, Any]) -> list[int]:
    numbers = sorted(
        int(match.group(1))
        for key in conversation
        if (match := _SESSION_RE.fullmatch(key)) is not None
    )
    if not numbers:
        raise LocomoDataError("Conversation has no session_N lists")
    expected = list(range(1, numbers[-1] + 1))
    if numbers != expected:
        raise LocomoDataError(f"Session indices are not contiguous: {numbers}")
    return numbers


def _safe_evidence_alias(raw_id: str, known_ids: set[str]) -> str | None:
    match = _DIA_ID_RE.fullmatch(raw_id)
    if not match:
        return None
    normalized = f"D{int(match.group(1))}:{int(match.group(2))}"
    if normalized != raw_id and normalized in known_ids:
        return normalized
    return None


def _audit_qa(
    qa_items: Any, known_ids: set[str]
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    if not isinstance(qa_items, list):
        raise LocomoDataError("Sample qa field must be a list")

    categories: Counter[str] = Counter()
    aliases: dict[str, dict[str, Any]] = {}
    unresolved: list[dict[str, Any]] = []
    empty_evidence_questions = 0
    duplicate_evidence_questions = 0
    evidence_reference_count = 0

    for qa_index, item in enumerate(qa_items):
        if not isinstance(item, dict):
            raise LocomoDataError(f"QA item {qa_index} must be an object")
        category = str(item.get("category"))
        if category not in CATEGORY_NAMES:
            raise LocomoDataError(f"QA item {qa_index} has unsupported category {category!r}")
        categories[category] += 1
        evidence = item.get("evidence")
        if not isinstance(evidence, list) or not all(isinstance(value, str) for value in evidence):
            raise LocomoDataError(f"QA item {qa_index} evidence must be a list of strings")
        evidence_reference_count += len(evidence)
        if not evidence:
            empty_evidence_questions += 1
        if len(evidence) != len(set(evidence)):
            duplicate_evidence_questions += 1

        for raw_id in evidence:
            if raw_id in known_ids:
                continue
            normalized = _safe_evidence_alias(raw_id, known_ids)
            if normalized is None:
                unresolved.append({"qa_index": qa_index, "qa_number": qa_index + 1, "dia_id": raw_id})
                continue
            entry = aliases.setdefault(
                raw_id,
                {
                    "canonical_dia_id": normalized,
                    "reason": "zero-padded numeric component in official QA evidence",
                    "qa_indices": [],
                    "qa_numbers": [],
                },
            )
            if entry["canonical_dia_id"] != normalized:
                raise LocomoDataError(f"Ambiguous evidence alias {raw_id!r}")
            entry["qa_indices"].append(qa_index)
            entry["qa_numbers"].append(qa_index + 1)

    if unresolved:
        raise LocomoDataError(f"QA evidence contains unresolved dialog ids: {unresolved}")

    non_adversarial = sum(categories[str(index)] for index in range(1, 5))
    audit = {
        "qa_total": len(qa_items),
        "qa_non_adversarial": non_adversarial,
        "qa_adversarial": categories["5"],
        "qa_by_category": {key: categories[key] for key in sorted(CATEGORY_NAMES)},
        "qa_category_names": CATEGORY_NAMES,
        "evidence_reference_count": evidence_reference_count,
        "empty_evidence_questions": empty_evidence_questions,
        "duplicate_evidence_questions": duplicate_evidence_questions,
        "evidence_alias_count": len(aliases),
        "unresolved_evidence_count": 0,
    }
    return audit, aliases


def prepare_locomo(
    dataset_path: Path,
    processed_path: Path,
    source_map_path: Path,
    manifest_path: Path,
    *,
    conversation_id: str = "conv-50",
    expected_raw_sha256: str | None = OFFICIAL_DATA_SHA256,
    license_path: Path | None = Path("data/LICENSE.locomo.txt"),
) -> dict[str, Any]:
    dataset_path = Path(dataset_path)
    processed_path = Path(processed_path)
    source_map_path = Path(source_map_path)
    manifest_path = Path(manifest_path)
    license_path = Path(license_path) if license_path is not None else None
    protected_paths = [dataset_path, processed_path, source_map_path, manifest_path]
    if license_path is not None:
        protected_paths.append(license_path)
    if len({path.resolve() for path in protected_paths}) != len(protected_paths):
        raise LocomoDataError(
            "Raw, license, processed, source-map, and manifest paths must be distinct"
        )

    raw_bytes = dataset_path.read_bytes()
    raw_sha256 = sha256_bytes(raw_bytes)
    if expected_raw_sha256 is not None and raw_sha256 != expected_raw_sha256:
        raise LocomoDataError(
            f"Raw dataset SHA-256 mismatch: expected {expected_raw_sha256}, got {raw_sha256}"
        )
    try:
        dataset = json.loads(raw_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LocomoDataError(f"Cannot parse LoCoMo JSON: {exc}") from exc

    sample_index, sample = _find_conversation(dataset, conversation_id)
    conversation = sample.get("conversation")
    if not isinstance(conversation, dict):
        raise LocomoDataError("Selected sample conversation must be an object")
    speakers = (conversation.get("speaker_a"), conversation.get("speaker_b"))
    if not all(isinstance(value, str) and value for value in speakers):
        raise LocomoDataError("conversation speaker_a and speaker_b must be non-empty strings")

    records: list[dict[str, Any]] = []
    sessions: dict[str, dict[str, Any]] = {}
    by_locator: dict[str, dict[str, Any]] = {}
    by_dia_id: dict[str, dict[str, Any]] = {}
    media_counts: Counter[str] = Counter()
    session_numbers = _session_numbers(conversation)

    for session_index in session_numbers:
        session_key = f"session_{session_index}"
        date_key = f"{session_key}_date_time"
        turns = conversation.get(session_key)
        raw_datetime = conversation.get(date_key)
        if not isinstance(turns, list) or not turns:
            raise LocomoDataError(f"{session_key} must be a non-empty list")
        if not isinstance(raw_datetime, str):
            raise LocomoDataError(f"{date_key} must be a string")
        parsed_datetime = parse_session_datetime(raw_datetime)
        first_jsonl_line = len(records) + 1

        for turn_index, raw_turn in enumerate(turns, start=1):
            if not isinstance(raw_turn, dict):
                raise LocomoDataError(f"{session_key} turn {turn_index} must be an object")
            expected_dia_id = f"D{session_index}:{turn_index}"
            dia_id = raw_turn.get("dia_id")
            speaker = raw_turn.get("speaker")
            text = raw_turn.get("text")
            if dia_id != expected_dia_id:
                raise LocomoDataError(
                    f"{session_key} turn {turn_index} expected dia_id {expected_dia_id!r}, got {dia_id!r}"
                )
            if not isinstance(speaker, str) or speaker not in speakers:
                raise LocomoDataError(
                    f"{session_key} turn {turn_index} has unexpected speaker {speaker!r}"
                )
            if not isinstance(text, str) or not text:
                raise LocomoDataError(f"{session_key} turn {turn_index} has empty/non-string text")

            locator = f"[S{session_index}T{turn_index}]"
            if locator in by_locator or dia_id in by_dia_id:
                raise LocomoDataError(f"Duplicate source id at {locator} / {dia_id}")
            media = {key: raw_turn.get(key) for key in _OPTIONAL_TURN_FIELDS}
            for key, value in media.items():
                if value is not None:
                    media_counts[key] += 1
            source_sha256 = sha256_bytes(text.encode("utf-8"))
            raw_turn_sha256 = sha256_bytes(_canonical_json_bytes(raw_turn))
            jsonl_line = len(records) + 1
            record = {
                "schema_version": SCHEMA_VERSION,
                "conversation_id": conversation_id,
                "session_id": session_key,
                "session_index": session_index,
                "session_date": parsed_datetime.date().isoformat(),
                "session_datetime": parsed_datetime.isoformat(timespec="seconds"),
                "session_datetime_raw": raw_datetime,
                "turn_index": turn_index,
                "global_turn_index": jsonl_line,
                "locator": locator,
                "dia_id": dia_id,
                "speaker": speaker,
                "text": text,
                "media": media,
                "source_sha256": source_sha256,
                "raw_turn_sha256": raw_turn_sha256,
            }
            records.append(record)
            map_entry = {
                "dia_id": dia_id,
                "jsonl_line": jsonl_line,
                "raw_json_pointer": f"/{sample_index}/conversation/{session_key}/{turn_index - 1}",
                "raw_turn_sha256": raw_turn_sha256,
                "session_id": session_key,
                "session_index": session_index,
                "source_sha256": source_sha256,
                "speaker": speaker,
                "turn_index": turn_index,
            }
            by_locator[locator] = map_entry
            by_dia_id[dia_id] = {"jsonl_line": jsonl_line, "locator": locator}

        sessions[session_key] = {
            "first_jsonl_line": first_jsonl_line,
            "last_jsonl_line": len(records),
            "session_date": parsed_datetime.date().isoformat(),
            "session_datetime": parsed_datetime.isoformat(timespec="seconds"),
            "session_datetime_raw": raw_datetime,
            "session_index": session_index,
            "turn_count": len(turns),
        }

    qa_audit, dia_id_aliases = _audit_qa(sample.get("qa"), set(by_dia_id))
    for alias, details in dia_id_aliases.items():
        canonical = details["canonical_dia_id"]
        details["locator"] = by_dia_id[canonical]["locator"]

    jsonl_bytes = (
        "".join(
            json.dumps(record, ensure_ascii=False, allow_nan=False, separators=(",", ":")) + "\n"
            for record in records
        )
    ).encode("utf-8")
    canonical_sha256 = sha256_bytes(jsonl_bytes)
    source_map = {
        "schema_version": SCHEMA_VERSION,
        "conversation_id": conversation_id,
        "record_artifact_id": f"locomo/{conversation_id}/canonical-turns/v{SCHEMA_VERSION}",
        "record_filename": processed_path.name,
        "record_count": len(records),
        "record_bytes": len(jsonl_bytes),
        "record_sha256": canonical_sha256,
        "jsonl_line_numbering": "1-based",
        "locator_scheme": "[S{session_index}T{turn_index}] (derived by this project)",
        "official_source_key": "dia_id",
        "source_data_commit": OFFICIAL_DATA_COMMIT,
        "source_data_sha256": raw_sha256,
        "sessions": sessions,
        "by_locator": by_locator,
        "by_dia_id": by_dia_id,
        "dia_id_aliases": dia_id_aliases,
    }
    source_map_bytes = _pretty_json_bytes(source_map)

    license_details: dict[str, Any] = {
        "name": OFFICIAL_LICENSE,
        "source_commit": OFFICIAL_LICENSE_COMMIT,
        "source_url": OFFICIAL_LICENSE_URL,
    }
    if license_path is not None:
        if not license_path.exists():
            raise LocomoDataError(f"License file does not exist: {license_path}")
        license_sha256 = sha256_file(license_path)
        if (
            license_sha256 != OFFICIAL_LICENSE_SHA256
            or license_path.stat().st_size != OFFICIAL_LICENSE_BYTES
        ):
            raise LocomoDataError(
                "License file does not match the pinned official CC BY-NC 4.0 text"
            )
        license_details.update(
            {
                "local_filename": license_path.name,
                "bytes": license_path.stat().st_size,
                "sha256": license_sha256,
            }
        )

    output_details = {
        "canonical_records": {
            "artifact_id": f"locomo/{conversation_id}/canonical-turns/v{SCHEMA_VERSION}",
            "filename": processed_path.name,
            "format": "JSON Lines; one immutable conversation turn per line",
            "records": len(records),
            "bytes": len(jsonl_bytes),
            "sha256": canonical_sha256,
        },
        "source_map": {
            "artifact_id": f"locomo/{conversation_id}/source-map/v{SCHEMA_VERSION}",
            "filename": source_map_path.name,
            "bytes": len(source_map_bytes),
            "sha256": sha256_bytes(source_map_bytes),
        },
    }
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "generator": {
            "module": "fs_memory_lab.locomo",
            "version": GENERATOR_VERSION,
        },
        "source": {
            "repository": OFFICIAL_REPOSITORY,
            "path": OFFICIAL_DATA_PATH,
            "data_file_commit": OFFICIAL_DATA_COMMIT,
            "immutable_download_url": OFFICIAL_DATA_URL,
            "local_filename": dataset_path.name,
            "bytes": len(raw_bytes),
            "sha256": raw_sha256,
            "license": license_details,
        },
        "selection": {
            "conversation_id": conversation_id,
            "raw_sample_index": sample_index,
            "speakers": list(speakers),
        },
        "counts": {
            "dataset_conversations": len(dataset),
            "conversation_sessions": len(session_numbers),
            "conversation_turns": len(records),
            **qa_audit,
            "turns_with_media_fields": {key: media_counts[key] for key in _OPTIONAL_TURN_FIELDS},
        },
        "normalization": {
            "raw_dataset_modified": False,
            "turn_text_modified": False,
            "derived_locator_count": len(records),
            "datetime_policy": "preserve raw string and add timezone-naive ISO datetime/date",
            "dia_id_aliases": dia_id_aliases,
        },
        "canonical_record_field_order": list(records[0]),
        "canonical_record_schema": CANONICAL_RECORD_SCHEMA,
        "outputs": output_details,
        "verification": {
            "session_indices_contiguous": True,
            "locators_unique": len(by_locator) == len(records),
            "dia_ids_unique_and_position_matched": len(by_dia_id) == len(records),
            "all_qa_evidence_resolves_after_aliases": True,
            "qa_content_excluded_from_canonical_records": True,
        },
    }
    manifest_bytes = _pretty_json_bytes(manifest)

    _atomic_write(processed_path, jsonl_bytes)
    _atomic_write(source_map_path, source_map_bytes)
    _atomic_write(manifest_path, manifest_bytes)

    return {
        "conversation_id": conversation_id,
        "sessions": len(session_numbers),
        "turns": len(records),
        "qa_total": qa_audit["qa_total"],
        "raw_sha256": raw_sha256,
        "canonical_sha256": output_details["canonical_records"]["sha256"],
        "source_map_sha256": output_details["source_map"]["sha256"],
        "dia_id_aliases": {key: value["canonical_dia_id"] for key, value in dia_id_aliases.items()},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare pinned LoCoMo canonical records")
    subparsers = parser.add_subparsers(dest="command", required=True)
    prepare = subparsers.add_parser("prepare", help="canonicalize one LoCoMo conversation")
    prepare.add_argument("--input", type=Path, default=Path("data/raw/locomo10.json"))
    prepare.add_argument("--conversation-id", default="conv-50")
    prepare.add_argument("--processed", type=Path, default=Path("data/processed/conv-50.jsonl"))
    prepare.add_argument("--source-map", type=Path, default=Path("data/manifests/source_map.json"))
    prepare.add_argument(
        "--manifest", type=Path, default=Path("data/manifests/locomo-conv-50-v1.json")
    )
    prepare.add_argument("--license", type=Path, default=Path("data/LICENSE.locomo.txt"))
    args = parser.parse_args()

    if args.command == "prepare":
        report = prepare_locomo(
            args.input,
            args.processed,
            args.source_map,
            args.manifest,
            conversation_id=args.conversation_id,
            expected_raw_sha256=OFFICIAL_DATA_SHA256,
            license_path=args.license,
        )
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
