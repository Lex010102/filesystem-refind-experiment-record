"""Hash-pinned inputs for formal R1 retrieval cells.

The loader is intentionally repository-relative: a formal store must occupy its
reviewed publication path and match an externally pinned manifest.  A
byte-identical staging or quarantine copy is not accepted as a substitute.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from .evidence import (
    EvidenceValidationError,
    QuestionInput,
    SourceCatalog,
    StoreSnapshotRef,
    VerifiedStoreManifest,
    canonical_json_bytes,
    sha256_bytes,
)


R1_INPUT_PROTOCOL_VERSION = "locomo-conv50-r1-inputs-v1"
FROZEN_R1_INPUT_CONTRACT_SHA256 = (
    "4fd5555fc5a1eb5793e6e84405c6a5c9fcb89a6c3377d1da550ded168bf5bef3"
)
CONVERSATION_ID = "conv-50"
SOURCE_MAP_SHA256 = "6e99115961bae06a48bfb7e82dbdcc18dc32ccf6c5ce57e3c266dfc7a5d4d574"
RECORDS_SHA256 = "130a5a1e1b75083358ef27a98dd215a4e75c819ace6f2ee9b560ba394e0f0394"
QUESTION_SET_MANIFEST_SHA256 = (
    "a58f07b3341ed7c79009fc233e7a9fc52ec2ba6f8ee59bc00c4602da759ba997"
)


@dataclass(frozen=True)
class R1StoreSpec:
    store_id: str
    store_relative_path: str
    manifest_relative_path: str
    manifest_sha256: str
    marker_relative_path: str | None
    marker_sha256: str | None
    path_map_relative_path: str | None
    trace_relative_path: str | None


R1_STORE_SPECS: Mapping[str, R1StoreSpec] = MappingProxyType(
    {
        "s1": R1StoreSpec(
            store_id="s1",
            store_relative_path="experiments/locomo-conv50-v1/stores/s1-flat",
            manifest_relative_path="experiments/locomo-conv50-v1/manifests/s1-flat.json",
            manifest_sha256="5c5900c333c8f85463f038448560cb4357f1161d6ed43e9fbc86809ba7916d3c",
            marker_relative_path=None,
            marker_sha256=None,
            path_map_relative_path=None,
            trace_relative_path=None,
        ),
        "s2": R1StoreSpec(
            store_id="s2",
            store_relative_path="experiments/locomo-conv50-v1/stores/s2-foldered",
            manifest_relative_path="experiments/locomo-conv50-v1/manifests/s2-foldered.json",
            manifest_sha256="4858e430f3c197d4f718ea5839596597c3dbbd885e3d1fc654e982a90dc707ac",
            marker_relative_path="experiments/locomo-conv50-v1/manifests/s2-foldered.COMMITTED",
            marker_sha256="af329bf6749b5909d809d81f52e41079d898a18d86c8bb2d80db0170fbb8b6a9",
            path_map_relative_path="experiments/locomo-conv50-v1/manifests/s2-foldered-path-map.json",
            trace_relative_path="experiments/locomo-conv50-v1/traces/s2-foldering.json",
        ),
        "s3": R1StoreSpec(
            store_id="s3",
            store_relative_path="experiments/locomo-conv50-v1/stores/s3-curated",
            manifest_relative_path="experiments/locomo-conv50-v1/manifests/s3-curated.json",
            manifest_sha256="70fb5ad56ff11bb849ce60b193cd6db29be601e613ca3afb76aac336e3b36e00",
            marker_relative_path="experiments/locomo-conv50-v1/manifests/s3-curated.COMMITTED",
            marker_sha256="5128d8f8624452dd07eb103e643a183e63fae7e0da3ee03ef87dbd08a4f3ef12",
            path_map_relative_path=None,
            trace_relative_path="experiments/locomo-conv50-v1/traces/s3-management",
        ),
    }
)

QUESTION_INPUTS: Mapping[str, Mapping[str, Any]] = MappingProxyType(
    {
        "dev-6": MappingProxyType(
            {
                "relative_path": "experiments/locomo-conv50-v1/question-sets/dev-6-input.jsonl",
                "sha256": "512921c38ccfccdfe14043aecc7475f75a74b36987027c230a26f95ad697481a",
                "count": 6,
                "question_set_id": "locomo-conv50-dev6-v1",
            }
        ),
        "main-40": MappingProxyType(
            {
                "relative_path": "experiments/locomo-conv50-v1/question-sets/main-40-input.jsonl",
                "sha256": "31a65ab18797abb4491cf8de2e172050d25000eb5c1f6ddb77383d3900b757af",
                "count": 40,
                "question_set_id": "locomo-conv50-main40-v1",
            }
        ),
    }
)


@dataclass(frozen=True)
class LoadedR1Store:
    protocol_version: str
    repo_root: Path
    root: Path
    catalog: SourceCatalog
    verified_manifest: VerifiedStoreManifest
    snapshot: StoreSnapshotRef

    def __post_init__(self) -> None:
        if self.protocol_version != R1_INPUT_PROTOCOL_VERSION:
            raise EvidenceValidationError("R1 input protocol version mismatch")
        if self.snapshot.store_id != self.verified_manifest.store_id:
            raise EvidenceValidationError("Loaded R1 store identities differ")
        if self.snapshot.conversation_id != CONVERSATION_ID:
            raise EvidenceValidationError("Loaded R1 store conversation differs")


def _repo_root(value: Path) -> Path:
    raw = Path(value)
    if raw.is_symlink() or not raw.is_dir():
        raise EvidenceValidationError("R1 repo root must be a non-symlink directory")
    root = raw.resolve()
    required = (root / "data", root / "experiments", root / "fs_memory_lab")
    if any(path.is_symlink() or not path.exists() for path in required):
        raise EvidenceValidationError("R1 repo root lacks the reviewed layout")
    return root


def load_r1_catalog(repo_root: Path) -> SourceCatalog:
    verify_r1_input_contract()
    root = _repo_root(repo_root)
    return SourceCatalog.load(
        root / "data/manifests/source_map.json",
        root / "data/processed/conv-50.jsonl",
        expected_source_map_sha256=SOURCE_MAP_SHA256,
        expected_records_sha256=RECORDS_SHA256,
        expected_conversation_id=CONVERSATION_ID,
    )


def load_r1_store(repo_root: Path, store_id: str) -> LoadedR1Store:
    verify_r1_input_contract()
    root = _repo_root(repo_root)
    if not isinstance(store_id, str):
        raise EvidenceValidationError("R1 store_id must be text")
    normalized = store_id.casefold()
    try:
        spec = R1_STORE_SPECS[normalized]
    except KeyError as exc:
        raise EvidenceValidationError("R1 store_id must be s1, s2, or s3") from exc
    catalog = load_r1_catalog(root)
    store_root = root / spec.store_relative_path
    if store_root.resolve() != (root / spec.store_relative_path).resolve():
        raise EvidenceValidationError("R1 store publication path is invalid")
    marker = root / spec.marker_relative_path if spec.marker_relative_path else None
    path_map = (
        root / spec.path_map_relative_path if spec.path_map_relative_path else None
    )
    trace = root / spec.trace_relative_path if spec.trace_relative_path else None
    manifest = VerifiedStoreManifest.load(
        root=store_root,
        store_id=normalized,
        catalog=catalog,
        manifest_path=root / spec.manifest_relative_path,
        expected_manifest_sha256=spec.manifest_sha256,
        commit_marker_path=marker,
        expected_commit_marker_sha256=spec.marker_sha256,
        path_map_path=path_map,
        trace_path=trace,
    )
    snapshot = StoreSnapshotRef.capture(
        root=store_root,
        catalog=catalog,
        verified_manifest=manifest,
    )
    return LoadedR1Store(
        protocol_version=R1_INPUT_PROTOCOL_VERSION,
        repo_root=root,
        root=store_root,
        catalog=catalog,
        verified_manifest=manifest,
        snapshot=snapshot,
    )


def load_question_inputs(
    repo_root: Path, question_set: str
) -> tuple[QuestionInput, ...]:
    verify_r1_input_contract()
    root = _repo_root(repo_root)
    try:
        spec = QUESTION_INPUTS[question_set]
    except (KeyError, TypeError) as exc:
        raise EvidenceValidationError("Unknown R1 question set") from exc
    manifest_path = root / "experiments/locomo-conv50-v1/question-sets/manifest.json"
    manifest_payload = manifest_path.read_bytes()
    if sha256_bytes(manifest_payload) != QUESTION_SET_MANIFEST_SHA256:
        raise EvidenceValidationError("Question-set manifest differs from frozen hash")
    manifest = json.loads(manifest_payload.decode("utf-8"))
    path = root / spec["relative_path"]
    payload = path.read_bytes()
    if sha256_bytes(payload) != spec["sha256"]:
        raise EvidenceValidationError("Question input differs from frozen hash")
    output_key = "development_input" if question_set == "dev-6" else "main_input"
    output = manifest.get("outputs", {}).get(output_key)
    if not isinstance(output, dict) or output.get("sha256") != spec["sha256"]:
        raise EvidenceValidationError("Question input is not bound by its manifest")
    questions: list[QuestionInput] = []
    for line_number, raw_line in enumerate(payload.splitlines(), 1):
        try:
            value = json.loads(raw_line.decode("utf-8"))
            question = QuestionInput.from_mapping(value)
        except (UnicodeError, json.JSONDecodeError, EvidenceValidationError) as exc:
            raise EvidenceValidationError(
                f"Question input line {line_number} is invalid"
            ) from exc
        questions.append(question)
    if len(questions) != spec["count"]:
        raise EvidenceValidationError("Question input count differs from frozen count")
    if tuple(item.run_position for item in questions) != tuple(
        range(1, len(questions) + 1)
    ):
        raise EvidenceValidationError("Question run positions are not contiguous")
    if len({item.question_id for item in questions}) != len(questions):
        raise EvidenceValidationError("Question input repeats a question_id")
    if any(
        item.question_set_id != spec["question_set_id"]
        or item.conversation_id != CONVERSATION_ID
        for item in questions
    ):
        raise EvidenceValidationError("Question input identity differs")
    return tuple(questions)


def r1_input_contract_sha256() -> str:
    body = {
        "protocol_version": R1_INPUT_PROTOCOL_VERSION,
        "conversation_id": CONVERSATION_ID,
        "source_map_sha256": SOURCE_MAP_SHA256,
        "records_sha256": RECORDS_SHA256,
        "question_set_manifest_sha256": QUESTION_SET_MANIFEST_SHA256,
        "stores": {
            key: {
                "store_relative_path": value.store_relative_path,
                "manifest_relative_path": value.manifest_relative_path,
                "manifest_sha256": value.manifest_sha256,
                "marker_relative_path": value.marker_relative_path,
                "marker_sha256": value.marker_sha256,
                "path_map_relative_path": value.path_map_relative_path,
                "trace_relative_path": value.trace_relative_path,
            }
            for key, value in R1_STORE_SPECS.items()
        },
        "question_inputs": {key: dict(value) for key, value in QUESTION_INPUTS.items()},
    }
    return sha256_bytes(canonical_json_bytes(body))


def verify_r1_input_contract() -> None:
    if r1_input_contract_sha256() != FROZEN_R1_INPUT_CONTRACT_SHA256:
        raise EvidenceValidationError(
            "Reviewed R1 input contract changed without a hash update"
        )
