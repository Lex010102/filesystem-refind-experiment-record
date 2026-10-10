"""Machine-verifiable freeze contract for the main-40 formal-v1 experiment.

The manifest produced by this module is intentionally descriptive and read-only:
it never opens an API connection and never starts a benchmark episode.  It binds
the reviewed stores, question order, prompts, runtime limits, model deployment,
fusion contract, and evaluation rules into one content-addressed object.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Mapping

from .agent import (
    RETRYABLE_HTTP_STATUS_CODES,
    TRANSIENT_HTTP_MAX_ATTEMPTS,
    TRANSIENT_HTTP_RETRY_BACKOFF_SECONDS,
)
from .answerer import (
    ANSWERER_FORMAT_REPAIR_LIMIT,
    ANSWERER_HTTP_BACKOFF_SECONDS,
    ANSWERER_HTTP_MAX_ATTEMPTS,
    ANSWERER_MAX_COMPLETION_TOKENS,
    ANSWERER_PROTOCOL_VERSION,
    ANSWERER_SYSTEM_PROMPT,
    ANSWERER_SYSTEM_PROMPT_SHA256,
    ANSWERER_TEMPERATURE,
    ANSWERER_TIMEOUT_BACKOFF_SECONDS,
    ANSWERER_TIMEOUT_MAX_ATTEMPTS,
)
from .evidence import EvidenceValidationError, canonical_json_bytes, sha256_bytes
from .evaluation import (
    EVALUATION_PROTOCOL_VERSION,
    LOCOMO_EVALUATOR_COMMIT,
    LOCOMO_EVALUATOR_PATH,
    LOCOMO_EVALUATOR_REPOSITORY,
    LOCOMO_EVALUATOR_SHA256,
    LOCOMO_NLTK_VERSION,
    RELIABLE_POOL_CATEGORY_COUNTS,
)
from .fusion import FUSION_CONTRACT, FUSION_CONTRACT_SHA256, FUSION_PROTOCOL_VERSION
from .r1_agent import (
    FROZEN_R1_AGENT_LIMITS_SHA256,
    R1_AGENT_LIMITS,
    R1_AGENT_PROTOCOL_VERSION,
)
from .r1_inputs import QUESTION_INPUTS, load_question_inputs, load_r1_store
from .r1_orchestration import R1_ROUND_LIMIT_BY_STORE
from .r1_prompts import current_prompt_hashes, verify_r1_prompts
from .r2_prompts import r2_prompt_hashes, verify_r2_prompts
from .r2_protocol import (
    FROZEN_R2_PROTOCOL_SHA256,
    R2_PARAMETERS,
    R2_PROTOCOL_VERSION,
    R2_RUNTIME_LIMITS,
    verify_r2_protocol,
)
from .r3_prompts import r3_prompt_hashes, verify_r3_prompts
from .r3_protocol import (
    FROZEN_R3_PROTOCOL_SHA256,
    R3_PARAMETERS,
    R3_PROTOCOL_VERSION,
    R3_RUNTIME_LIMITS,
    verify_r3_protocol,
)
from .run_records import CONDITION_IDS, build_execution_order


FORMAL_PROTOCOL_VERSION = "locomo-conv50-formal-v1"
FORMAL_MANIFEST_RELATIVE_PATH = (
    "experiments/locomo-conv50-v1/formal-v1/manifest.json"
)
FORMAL_EVIDENCE_BUDGET_UNIT = "characters"
FORMAL_EVIDENCE_BUDGET_LIMIT = 16_000
FORMAL_REQUESTED_MODEL_ALIAS = "coding"
FORMAL_SERVED_MODEL = "qwen3.8:27b"
FORMAL_API_STYLE = "portable"
FORMAL_REQUEST_TIMEOUT_SECONDS = 300
FORMAL_MAX_RESPONSE_BYTES = 20_000_000
FORMAL_CONCURRENCY = 1

PILOT_PROVENANCE = {
    "retrieval_run_id": "stage3-dev6-b16000-20261010T074000Z",
    "retrieval_summary_id": (
        "summary-50f06ee8226af615bd595c007cc7a0156d7d52e674de418efd9e152c631451c7"
    ),
    "retrieval_manifest_sha256": (
        "f08a2eaec054b8f2e0fea4d1c22f557a263277a836b0b32fcb6597a1f3d3bc51"
    ),
    "retrieval_summary_sha256": (
        "617a8630ebc6e4e9546a46da0d6d946874f10fafdeec4e8a5bbb178d46e4d074"
    ),
    "pilot_run_id": "stage4-dev6-e1-e7-b16000-20261010T074000Z",
    "pilot_audit_id": (
        "pilot-audit-f14d85476acb00a936cd0be311d3b691149ef9b66e7cce420f9600856e7e00a7"
    ),
    "pilot_manifest_sha256": (
        "ff6e3de98f6c9fda03924de4a32c13d6ae3b632c113bc02ae1faa9c8441d1962"
    ),
    "pilot_plan_sha256": (
        "74e2933eb7b73ba3b878b839b3ddcfde9c575dcc9297e89908c017f6fc2130c4"
    ),
    "pilot_audit_sha256": (
        "329777f54e9f6d8c47ccaf484a95bda8afdd76eee77f038c3f74a1fefb63fe8e"
    ),
    "pilot_evaluation_sha256": (
        "19366c363a75e6f270ddc1872b49686ea71e6ff44dda891e87a3a0063a5d5f2a"
    ),
    "records": 42,
    "system_failure_rate": 0.0,
    "served_models": [FORMAL_SERVED_MODEL],
    "acceptance_checks_all_passed": True,
}

# These files contain the algorithms and contracts that may affect a formal
# result.  Their individual hashes make accidental post-freeze drift visible
# even when a verifier is run outside the original Git checkout.
FORMAL_CORE_FILES = (
    "pyproject.toml",
    "fs_memory_lab/agent.py",
    "fs_memory_lab/answerer.py",
    "fs_memory_lab/dev_retrieval.py",
    "fs_memory_lab/evaluation.py",
    "fs_memory_lab/evidence.py",
    "fs_memory_lab/fusion.py",
    "fs_memory_lab/pilot.py",
    "fs_memory_lab/r1_agent.py",
    "fs_memory_lab/r1_artifacts.py",
    "fs_memory_lab/r1_inputs.py",
    "fs_memory_lab/r1_orchestration.py",
    "fs_memory_lab/r1_prompts.py",
    "fs_memory_lab/r1_runner.py",
    "fs_memory_lab/r1_tools.py",
    "fs_memory_lab/r2_agent.py",
    "fs_memory_lab/r2_artifacts.py",
    "fs_memory_lab/r2_index.py",
    "fs_memory_lab/r2_inputs.py",
    "fs_memory_lab/r2_prompts.py",
    "fs_memory_lab/r2_protocol.py",
    "fs_memory_lab/r2_runner.py",
    "fs_memory_lab/r2_tools.py",
    "fs_memory_lab/r3_agent.py",
    "fs_memory_lab/r3_artifacts.py",
    "fs_memory_lab/r3_index.py",
    "fs_memory_lab/r3_inputs.py",
    "fs_memory_lab/r3_prompts.py",
    "fs_memory_lab/r3_protocol.py",
    "fs_memory_lab/r3_runner.py",
    "fs_memory_lab/r3_tools.py",
    "fs_memory_lab/run_records.py",
    "fs_memory_lab/vendor/locomo_porter.py",
)

_COMMIT = re.compile(r"[0-9a-f]{40}\Z")


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _core_file_hashes(repo_root: Path) -> dict[str, str]:
    output: dict[str, str] = {}
    for relative in FORMAL_CORE_FILES:
        path = repo_root / relative
        if path.is_symlink() or not path.is_file():
            raise EvidenceValidationError(f"Formal core file is missing: {relative}")
        output[relative] = _file_sha256(path)
    return output


def _json_safe(value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: list(nested) if isinstance(nested, tuple) else nested
        for key, nested in value.items()
    }


def formal_manifest_body(repo_root: Path, implementation_commit: str) -> dict[str, Any]:
    """Build the canonical freeze body without writing or calling an API."""
    root = Path(repo_root).resolve()
    if _COMMIT.fullmatch(implementation_commit) is None:
        raise EvidenceValidationError("Formal implementation commit must be a full Git SHA")

    verify_r1_prompts()
    verify_r2_prompts()
    verify_r3_prompts()
    verify_r2_protocol()
    verify_r3_protocol()

    stores = {
        store_id: load_r1_store(root, store_id).snapshot.to_dict()
        for store_id in ("s1", "s2", "s3")
    }
    questions = load_question_inputs(root, "main-40")
    if len(questions) != 40:
        raise EvidenceValidationError("formal-v1 requires exactly 40 main questions")
    question_order = [
        {
            "run_position": index,
            "question_id": question.question_id,
            "question_sha256": question.sha256,
            "question": question.question,
        }
        for index, question in enumerate(questions, start=1)
    ]
    execution_order = [
        item.to_dict()
        for item in build_execution_order(
            tuple(question.question_id for question in questions), CONDITION_IDS
        )
    ]
    if len(execution_order) != 280:
        raise EvidenceValidationError("formal-v1 execution order must contain 280 keys")

    core_hashes = _core_file_hashes(root)
    core_tree_sha256 = sha256_bytes(canonical_json_bytes(core_hashes))
    main_input = root / str(QUESTION_INPUTS["main-40"]["relative_path"])
    main_gold = root / "experiments/locomo-conv50-v1/question-sets/main-40-gold.jsonl"

    return {
        "schema_version": 1,
        "protocol_version": FORMAL_PROTOCOL_VERSION,
        "status": "frozen",
        "implementation_git_commit": implementation_commit,
        "core_files": core_hashes,
        "core_files_tree_sha256": core_tree_sha256,
        "pilot_provenance": dict(PILOT_PROVENANCE),
        "stores": stores,
        "question_set": {
            "question_set_id": "locomo-conv50-main40-v1",
            "input_relative_path": str(QUESTION_INPUTS["main-40"]["relative_path"]),
            "input_sha256": _file_sha256(main_input),
            "gold_relative_path": (
                "experiments/locomo-conv50-v1/question-sets/main-40-gold.jsonl"
            ),
            "gold_sha256": _file_sha256(main_gold),
            "question_count": 40,
            "question_order": question_order,
            "condition_order": list(CONDITION_IDS),
            "execution_order_policy": "question-major-rotated-e1-e6-then-e7",
            "execution_order": execution_order,
            "execution_order_sha256": sha256_bytes(
                canonical_json_bytes(execution_order)
            ),
        },
        "retrieval": {
            "condition_map": {
                "E1": {"store": "s1", "method": "r1"},
                "E2": {"store": "s1", "method": "r2"},
                "E3": {"store": "s2", "method": "r1"},
                "E4": {"store": "s2", "method": "r2"},
                "E5": {"store": "s3", "method": "r1"},
                "E6": {"store": "s3", "method": "r3"},
                "E7": {"store": "e2-plus-e6", "method": "fusion"},
            },
            "evidence_budget": {
                "unit": FORMAL_EVIDENCE_BUDGET_UNIT,
                "single_source_limit": FORMAL_EVIDENCE_BUDGET_LIMIT,
                "e7_per_source_limit": FORMAL_EVIDENCE_BUDGET_LIMIT,
                "e7_total_limit": 2 * FORMAL_EVIDENCE_BUDGET_LIMIT,
            },
            "r1": {
                "protocol_version": R1_AGENT_PROTOCOL_VERSION,
                "prompt_hashes": current_prompt_hashes(),
                "round_cap_by_condition": {"E1": 20, "E3": 20, "E5": 40},
                "round_cap_by_store": dict(R1_ROUND_LIMIT_BY_STORE),
                "limits_sha256": FROZEN_R1_AGENT_LIMITS_SHA256,
                "limits": _json_safe(R1_AGENT_LIMITS),
            },
            "r2": {
                "protocol_version": R2_PROTOCOL_VERSION,
                "protocol_sha256": FROZEN_R2_PROTOCOL_SHA256,
                "prompt_hashes": r2_prompt_hashes(),
                "action_cap": int(R2_PARAMETERS["agent_action_cap"]),
                "parameters": _json_safe(R2_PARAMETERS),
                "runtime_limits": _json_safe(R2_RUNTIME_LIMITS),
            },
            "r3": {
                "protocol_version": R3_PROTOCOL_VERSION,
                "protocol_sha256": FROZEN_R3_PROTOCOL_SHA256,
                "prompt_hashes": r3_prompt_hashes(),
                "action_cap": int(R3_PARAMETERS["agent_action_cap"]),
                "parameters": _json_safe(R3_PARAMETERS),
                "runtime_limits": _json_safe(R3_RUNTIME_LIMITS),
            },
        },
        "answerer": {
            "protocol_version": ANSWERER_PROTOCOL_VERSION,
            "prompt_id": "project-defined-shared-evidence-answerer-v1",
            "prompt_sha256": ANSWERER_SYSTEM_PROMPT_SHA256,
            "system_prompt": ANSWERER_SYSTEM_PROMPT,
            "max_completion_tokens": ANSWERER_MAX_COMPLETION_TOKENS,
            "temperature": ANSWERER_TEMPERATURE,
            "format_repair_limit": ANSWERER_FORMAT_REPAIR_LIMIT,
            "timeout_max_attempts": ANSWERER_TIMEOUT_MAX_ATTEMPTS,
            "timeout_retry_backoff_seconds": list(ANSWERER_TIMEOUT_BACKOFF_SECONDS),
            "http_max_attempts": ANSWERER_HTTP_MAX_ATTEMPTS,
            "http_retry_backoff_seconds": list(ANSWERER_HTTP_BACKOFF_SECONDS),
        },
        "e7_fusion": {
            "protocol_version": FUSION_PROTOCOL_VERSION,
            "contract_sha256": FUSION_CONTRACT_SHA256,
            "contract": dict(FUSION_CONTRACT),
            "retrieval": "reuse E2 and E6 EvidenceBundles; no new search or LLM",
            "cost_rule": (
                "count E2+E6 retrieval exactly once plus E7 Answerer; exclude "
                "E2/E6 Answerer costs"
            ),
        },
        "deployment": {
            "requested_model_alias": FORMAL_REQUESTED_MODEL_ALIAS,
            "required_served_model": FORMAL_SERVED_MODEL,
            "served_model_policy": "every model response must match exactly or fail closed",
            "api_style": FORMAL_API_STYLE,
            "request_timeout_seconds": FORMAL_REQUEST_TIMEOUT_SECONDS,
            "request_timeout_semantics": "socket-idle-and-POSIX-main-thread-wall-clock",
            "max_response_bytes": FORMAL_MAX_RESPONSE_BYTES,
            "concurrency": FORMAL_CONCURRENCY,
            "concurrency_policy": "serial API episodes and serial Answerer calls",
            "retry": {
                "timeout_max_attempts": 3,
                "timeout_backoff_seconds": [2, 4],
                "retryable_http_statuses": sorted(RETRYABLE_HTTP_STATUS_CODES),
                "http_max_attempts": TRANSIENT_HTTP_MAX_ATTEMPTS,
                "http_backoff_seconds": list(TRANSIENT_HTTP_RETRY_BACKOFF_SECONDS),
                "scope": "only before a complete provider response returns",
                "completed_actions_are_never_replayed": True,
            },
            "resume": (
                "stop on failure; resume skips only content-verified completed records"
            ),
        },
        "scoring": {
            "protocol_version": EVALUATION_PROTOCOL_VERSION,
            "primary_metric": "official LoCoMo category-aware token F1",
            "primary_aggregate": "per-condition micro_f1 over all 40 questions",
            "official_evaluator": {
                "repository": LOCOMO_EVALUATOR_REPOSITORY,
                "commit": LOCOMO_EVALUATOR_COMMIT,
                "path": LOCOMO_EVALUATOR_PATH,
                "sha256": LOCOMO_EVALUATOR_SHA256,
                "nltk_version": LOCOMO_NLTK_VERSION,
            },
            "category_rules": {
                "1": "comma-split multi-answer F1",
                "2": "stemmed token F1",
                "3": "truncate gold at first semicolon, then stemmed token F1",
                "4": "stemmed token F1",
            },
            "reported_answer_aggregates": [
                "micro_f1",
                "category_f1",
                "category_macro_f1",
                "post_stratified_f1",
            ],
            "post_stratification_pool_counts": {
                str(key): value for key, value in RELIABLE_POOL_CATEGORY_COUNTS.items()
            },
            "secondary_metrics": [
                "evidence_recall",
                "any_hit_rate",
                "all_hit_rate",
                "citation_validity",
                "total_tokens",
                "retrieval_rounds_or_actions",
                "cap_rate",
            ],
            "anonymous_llm_judge": {
                "enabled": False,
                "reason": "not exercised by the accepted pilot; excluded from formal-v1",
            },
            "gold_access": "post-run evaluation only after all 280 records verify",
            "incomplete_run_policy": "fail closed; no partial condition score",
        },
        "change_control": {
            "main40_retuning_forbidden": True,
            "forbidden_after_freeze": [
                "prompt changes",
                "evidence budget changes",
                "search parameter changes",
                "cap changes",
                "question reordering",
                "model or scoring changes",
            ],
            "substantive_bug_rule": (
                "create a new formal version and rerun every affected condition; "
                "never mix records from different formal versions"
            ),
        },
    }


def _manifest_from_body(body: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "formal_manifest_id": "formal-" + sha256_bytes(canonical_json_bytes(body)),
        **dict(body),
    }


def write_formal_manifest(
    repo_root: Path, *, implementation_commit: str,
    destination: Path | None = None,
) -> Path:
    """Exclusively publish the formal manifest. Existing files are never replaced."""
    root = Path(repo_root).resolve()
    path = (
        Path(destination).resolve()
        if destination is not None
        else root / FORMAL_MANIFEST_RELATIVE_PATH
    )
    value = _manifest_from_body(formal_manifest_body(root, implementation_commit))
    payload = canonical_json_bytes(value) + b"\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags, 0o644)
    except FileExistsError as exc:
        raise EvidenceValidationError("Formal manifest already exists") from exc
    try:
        offset = 0
        while offset < len(payload):
            written = os.write(descriptor, payload[offset:])
            if written <= 0:
                raise OSError("short formal manifest write")
            offset += written
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return path


def verify_formal_manifest(repo_root: Path, manifest_path: Path | None = None) -> dict[str, Any]:
    """Recompute every repository-derived field and reject any drift."""
    root = Path(repo_root).resolve()
    path = (
        Path(manifest_path).resolve()
        if manifest_path is not None
        else root / FORMAL_MANIFEST_RELATIVE_PATH
    )
    if path.is_symlink() or not path.is_file():
        raise EvidenceValidationError("Formal manifest is missing or not a regular file")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise EvidenceValidationError("Formal manifest must be a JSON object")
    manifest_id = value.get("formal_manifest_id")
    implementation_commit = value.get("implementation_git_commit")
    if not isinstance(implementation_commit, str):
        raise EvidenceValidationError("Formal implementation commit is missing")
    expected = _manifest_from_body(formal_manifest_body(root, implementation_commit))
    if value != expected:
        raise EvidenceValidationError("Formal manifest or frozen repository inputs drifted")
    if manifest_id != expected["formal_manifest_id"]:
        raise EvidenceValidationError("Formal manifest content hash differs")
    return {
        "status": "verified",
        "protocol_version": FORMAL_PROTOCOL_VERSION,
        "formal_manifest_id": manifest_id,
        "implementation_git_commit": implementation_commit,
        "question_count": 40,
        "planned_records": 280,
        "evidence_budget": {
            "unit": FORMAL_EVIDENCE_BUDGET_UNIT,
            "limit": FORMAL_EVIDENCE_BUDGET_LIMIT,
        },
        "served_model": FORMAL_SERVED_MODEL,
    }
